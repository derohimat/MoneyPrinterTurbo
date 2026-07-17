import ast
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from loguru import logger

from app.models import const
from app.models.schema import VideoParams
from app.services import webui_task


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _attribute_name(node):
    """把 ``module.function`` 形式的 AST 调用还原为稳定字符串。"""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return ".".join(reversed(names))


def test_generation_controls_submit_background_task_instead_of_blocking_page():
    """
    WebUI 生成按钮不能重新直接调用同步流水线。

    这是 Issue #1120 白屏的核心回归保护：只要完整页面脚本再次阻塞在
    ``tm.start``，用户在生成期间刷新时仍可能收到指向旧渲染树的 delta。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )
    calls = {
        _attribute_name(node.func)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }

    assert "webui_task.submit_generation" in calls
    assert "tm.start" not in calls


def test_submit_generation_returns_while_pipeline_is_still_running():
    """后台流水线未结束时，提交函数必须已经返回，让 Streamlit 完成本次渲染。"""
    task_id = "background-submit-test"
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_start(**_kwargs):
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"videos": ["/tmp/final-1.mp4"]}

    params = VideoParams(video_subject="异步生成测试")
    try:
        with (
            patch.object(webui_task.tm, "start", side_effect=blocking_start),
            patch.object(
                webui_task.config,
                "runtime_config_lock",
                return_value=nullcontext(),
            ),
        ):
            started_at = time.monotonic()
            webui_task.submit_generation(task_id, params, capture_logs=False)
            elapsed = time.monotonic() - started_at

            assert started.wait(timeout=2)
            assert elapsed < 0.5
            assert not finished.is_set()
            task = webui_task.sm.state.get_task(task_id)
            assert task["state"] == const.TASK_STATE_PROCESSING
    finally:
        release.set()
        assert finished.wait(timeout=2)
        webui_task.sm.state.delete_task(task_id)


def test_submit_generation_copies_params_before_starting_worker():
    """页面后续 rerun 或流水线内部修改参数时，不能反向污染当前表单对象。"""
    params = VideoParams(video_subject="参数隔离测试")
    with patch.object(webui_task._task_manager, "add_task") as add_task:
        webui_task.submit_generation("copied-params-test", params, capture_logs=False)

    submitted_params = add_task.call_args.kwargs["params"]
    assert submitted_params == params
    assert submitted_params is not params
    webui_task.sm.state.delete_task("copied-params-test")


def test_scheduling_failure_is_saved_as_terminal_task_state():
    """队列或线程启动失败时不能让任务管理器永久停留在“生成中”。"""
    task_id = "scheduling-failure-test"
    params = VideoParams(video_subject="调度失败测试")
    with patch.object(
        webui_task._task_manager,
        "add_task",
        side_effect=RuntimeError("worker unavailable"),
    ):
        with pytest.raises(RuntimeError, match="worker unavailable"):
            webui_task.submit_generation(task_id, params, capture_logs=False)

    task = webui_task.sm.state.get_task(task_id)
    assert task["state"] == const.TASK_STATE_FAILED
    assert task["failed_stage"] == "scheduling"
    assert task["error"] == "RuntimeError: worker unavailable"
    webui_task.sm.state.delete_task(task_id)


def test_worker_logs_are_available_without_streamlit_session_state():
    """后台日志写入线程安全缓存，页面只需轮询快照即可恢复实时日志。"""
    task_id = "captured-log-test"
    with webui_task._task_logs_lock:
        webui_task._task_logs.pop(task_id, None)

    def logged_start(**_kwargs):
        logger.info("unique background task log")
        return {"videos": ["/tmp/final-1.mp4"]}

    with (
        patch.object(webui_task.tm, "start", side_effect=logged_start),
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        result = webui_task._run_generation(
            task_id,
            VideoParams(video_subject="日志测试"),
            capture_logs=True,
        )

    assert result == {"videos": ["/tmp/final-1.mp4"]}
    assert webui_task.get_task_logs(task_id) == ["unique background task log"]


def test_worker_wrapper_failure_is_saved_instead_of_leaving_processing_state():
    """日志或配置包装层异常也必须转换成可查询的失败终态。"""
    task_id = "worker-wrapper-failure-test"
    with (
        patch.object(webui_task.tm, "start", side_effect=RuntimeError("lock failed")),
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        result = webui_task._run_generation(
            task_id,
            VideoParams(video_subject="工作线程失败测试"),
            capture_logs=False,
        )

    assert result["state"] == const.TASK_STATE_FAILED
    assert result["failed_stage"] == "webui_worker"
    task = webui_task.sm.state.get_task(task_id)
    assert task["state"] == const.TASK_STATE_FAILED
    assert task["error"] == "RuntimeError: lock failed"
    webui_task.sm.state.delete_task(task_id)
