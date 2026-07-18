import itertools
import io
import os
import random
import gc
import shutil
import numpy as np
import re
import json
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import ExitStack, redirect_stdout
from functools import lru_cache
from typing import List
from loguru import logger
import numpy as np
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    vfx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

from app.config import config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import bgm as bgm_service
from app.services.utils import video_effects
from app.utils import file_security, utils, hook_generator, number_counter, progress_overlay
from app.services.utils import video_effects, pacing, sfx

class SubClippedVideoClip:
    def __init__(
        self,
        file_path,
        start_time=None,
        end_time=None,
        width=None,
        height=None,
        duration=None,
        source_file_path=None,
    ):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        self.source_file_path = source_file_path or file_path
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
import multiprocessing

def get_best_video_codec():
    """Custom tuned for i5-9400F + RX 550 4GB setup (macOS/Win10)"""
    try:
        result = subprocess.run(['ffmpeg', '-encoders'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        encoders = result.stdout.lower()
        
        # CPU is i5-9400F (No iGPU), so we strictly rely on the AMD RX 550 4GB.
        if sys.platform == 'darwin':
            # macOS Big Sur uses VideoToolbox for AMD GPUs natively
            if 'h264_videotoolbox' in encoders:
                logger.info("Hardware Acceleration: Apple VideoToolbox (macOS + RX 550) detected.")
                return 'h264_videotoolbox'
        elif sys.platform == 'win32':
            # Windows uses AMF for AMD GPUs
            if 'h264_amf' in encoders:
                logger.info("Hardware Acceleration: AMD AMF (Windows + RX 550) detected.")
                return 'h264_amf'
    except Exception as e:
        logger.warning(f"Failed to probe ffmpeg encoders: {str(e)}")
    
    logger.info("Hardware Acceleration not found or OS not matched, falling back to libx264 (CPU).")
    return 'libx264'

video_codec = get_best_video_codec()
# Use a compatible preset for AMD AMF (medium fails because it's only for x264/x265)
video_preset = "quality" if video_codec == "h264_amf" else "medium"
# Optimization for 32GB RAM & 6-Core i5-9400F: Increase thread count
optimal_threads = min(6, multiprocessing.cpu_count()) if multiprocessing.cpu_count() else 4

# Docker 里的 ffmpeg/AAC 组合在默认配置下更容易出现音频质量波动，
# 这里显式抬高音频码率，避免成片阶段因为默认值过低而引入明显失真。
audio_bitrate = "192k"
fps = 30
# FFmpeg 按帧率拼接/转码时，最终时长可能比 MoviePy 读到的理论时长短几十毫秒。
# 这里给视频素材多留一个很小的安全余量，避免音频末尾因为帧舍入出现黑屏、
# 卡顿或最后一小段旁白没有画面的情况。
_VIDEO_DURATION_SAFETY_MARGIN = 0.1
_MIN_MATERIAL_DIMENSION = 480
# 消息类应用和部分编码器会把画面尺寸向下取整，例如 WhatsApp 会把 9:16 的
# 素材压成 478x850，比 480 少两个像素。直接按 480 硬卡会让这类素材全部被
# 丢弃，最终以 "no valid materials found" 整体失败。这里留一个很小的容差，
# 既能放行仅仅因为取整而略低于阈值的素材，也仍然能挡住真正的低清素材。
_MIN_DIMENSION_TOLERANCE = 10
_DEFAULT_VIDEO_CODEC = "libx264"
_SUPPORTED_VIDEO_CODECS = (
    "libx264",
    "h264_nvenc",
    "h264_amf",
    "h264_qsv",
    "h264_mf",
    "h264_videotoolbox",
)
_runtime_disabled_video_codecs = set()


def _get_required_video_duration(audio_duration: float) -> float:
    """
    返回视频素材拼接的目标时长。

    使用场景：合成视频时需要素材时长覆盖旁白音频。只做到“刚好等于”
    音频时长时，FFmpeg 可能因为帧率舍入让最终视频略短，因此统一加一个
    轻量余量。函数独立出来，便于测试和后续按实际反馈调整余量大小。
    """
    return max(0.0, float(audio_duration) + _VIDEO_DURATION_SAFETY_MARGIN)


def is_material_resolution_acceptable(width: int, height: int) -> bool:
    """
    判断素材分辨率是否足够用于合成。

    标称最小值是 480x480，但允许比它低 `_MIN_DIMENSION_TOLERANCE` 个像素，
    以兼容编码器/消息应用向下取整导致的尺寸（例如 WhatsApp 的 478x850）。
    """
    min_dimension = _MIN_MATERIAL_DIMENSION - _MIN_DIMENSION_TOLERANCE
    return width >= min_dimension and height >= min_dimension


def _prioritize_unique_source_clips(
    subclipped_items: List[SubClippedVideoClip],
    concat_mode: VideoConcatMode,
) -> List[SubClippedVideoClip]:
    """
    优先让每个源素材只出现一次，降低成片里同一素材反复出现的概率。

    线上素材经常会遇到“一个长视频被切成多个短片段”的情况。旧逻辑在
    random 模式下直接打乱所有短片段，导致同一个源视频的多个切片可能
    分布在开头和中间，用户会感知为素材重复。本函数只调整片段顺序：
    先放每个源文件里最长的一个片段，剩余片段作为兜底；当素材总时长不足时，
    仍然允许后续片段补齐音频长度，避免破坏视频生成成功率。优先选择最长
    片段是为了避免随机选中视频尾部的零碎短片段，导致明明有足够素材却过早复用。
    """
    if not subclipped_items:
        return []

    concat_mode_value = getattr(concat_mode, "value", concat_mode)
    if concat_mode_value != VideoConcatMode.random.value:
        return subclipped_items

    grouped_items: dict[str, list[SubClippedVideoClip]] = {}
    for item in subclipped_items:
        grouped_items.setdefault(item.source_file_path, []).append(item)

    primary_items = []
    overflow_items = []
    for items in grouped_items.values():
        primary_item = max(items, key=lambda item: item.duration)
        primary_items.append(primary_item)
        overflow_items.extend(item for item in items if item is not primary_item)

    random.shuffle(primary_items)
    random.shuffle(overflow_items)
    logger.info(
        "prioritized unique video materials, "
        f"sources: {len(grouped_items)}, "
        f"primary clips: {len(primary_items)}, "
        f"fallback clips: {len(overflow_items)}"
    )
    return primary_items + overflow_items


def get_ffmpeg_binary():
    """
    兼容历史上直接从 video 服务读取 FFmpeg 路径的调用方。

    真正的解析逻辑已经抽到 `app.utils.utils.get_ffmpeg_binary()`，视频、语音
    和后续新增链路都应复用同一套优先级；这里保留薄包装，避免外部脚本或
    旧测试直接导入 `app.services.video.get_ffmpeg_binary` 时出现 AttributeError。
    """
    return utils.get_ffmpeg_binary()


def _get_configured_video_codec() -> str:
    """
    读取用户配置的视频编码器。

    该配置面向高级用户，用于尝试启用 NVENC/AMF/QSV/VideoToolbox 等硬件
    编码。这里刻意只允许固定白名单，避免开放任意 FFmpeg 参数后，用户填错
    参数导致输出格式不可控，甚至让生成任务在后续阶段才失败。
    """
    configured_codec = str(
        config.app.get("video_codec", _DEFAULT_VIDEO_CODEC) or _DEFAULT_VIDEO_CODEC
    ).strip()
    if configured_codec not in _SUPPORTED_VIDEO_CODECS:
        logger.warning(
            f"unsupported video codec configured: {configured_codec}, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC
    return configured_codec


@lru_cache(maxsize=16)
def _ffmpeg_encoder_exists(ffmpeg_binary: str, codec: str) -> bool:
    """
    检查当前 FFmpeg 是否声明支持指定编码器。

    这只能证明 FFmpeg 编译时包含该 encoder，不能证明当前机器硬件和驱动
    一定可用。因此实际编码失败时仍会再回退到 libx264。
    """
    try:
        result = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "failed to inspect ffmpeg encoders, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}: {str(exc)}"
        )
        return False

    if result.returncode != 0:
        logger.warning(
            "failed to inspect ffmpeg encoders, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}: {(result.stderr or result.stdout or '').strip()}"
        )
        return False
    return codec in result.stdout


def _get_effective_video_codec(preferred_codec: str | None = None) -> str:
    """
    返回本次实际使用的视频编码器。

    用户选择硬件编码器时，先做 FFmpeg encoder 列表检测；如果本进程里已经
    实际编码失败过，也直接回退，避免一个任务里每个片段都重复失败。
    """
    selected_codec = preferred_codec or _get_configured_video_codec()
    if selected_codec == _DEFAULT_VIDEO_CODEC:
        return _DEFAULT_VIDEO_CODEC

    if selected_codec in _runtime_disabled_video_codecs:
        logger.warning(
            f"video codec {selected_codec} was disabled after a runtime failure, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC

    ffmpeg_binary = utils.get_ffmpeg_binary()
    if not _ffmpeg_encoder_exists(ffmpeg_binary, selected_codec):
        logger.warning(
            f"ffmpeg encoder {selected_codec} is not available, "
            f"fallback to {_DEFAULT_VIDEO_CODEC}"
        )
        return _DEFAULT_VIDEO_CODEC

    return selected_codec


def _disable_runtime_video_codec(codec: str, reason: str):
    if codec == _DEFAULT_VIDEO_CODEC:
        return
    _runtime_disabled_video_codecs.add(codec)
    logger.warning(
        f"video codec {codec} failed, fallback to {_DEFAULT_VIDEO_CODEC}. "
        f"reason: {reason}"
    )


def _get_temp_audio_dir(output_dir: str) -> str:
    """
    Return the directory to use for MoviePy's temporary audio file.

    On Windows, Windows Defender can lock files written to the task output
    directory while scanning them, causing MoviePy to fail with a
    PermissionError (WinError 32) on the TEMP_MPY_wvf_snd temp file and
    leaving the final MP4 at 0 bytes.  Using the system temp directory
    sidesteps the scan without changing behaviour on other platforms.

    On Linux/macOS/Docker the output directory is returned unchanged so
    existing behaviour is preserved.
    """
    if sys.platform == "win32":
        return tempfile.gettempdir()
    return output_dir


def _fallback_write_videofile(clip, output_file: str, failed_codec: str, reason: str, **kwargs):
    """
    硬件编码失败后用 libx264 重试，只有重试成功才禁用该硬件编码器。

    Windows 上 FFmpeg 失败原因比较复杂：可能是显卡/驱动不支持，也可能是输出
    文件被占用、目录权限、杀软拦截等通用 IO 问题。只有 libx264 能成功写出时，
    才能判断原始失败大概率来自硬件编码器本身，避免误伤后续任务。
    """
    clip.write_videofile(output_file, codec=_DEFAULT_VIDEO_CODEC, **kwargs)
    _disable_runtime_video_codec(failed_codec, reason)
    return _DEFAULT_VIDEO_CODEC


def _write_videofile_with_codec_fallback(clip, output_file: str, codec: str, **kwargs):
    """
    使用指定编码器写出视频，失败时自动用 libx264 重试一次。

    硬件编码器是否可用不仅取决于 FFmpeg，还取决于显卡、驱动和当前运行环境。
    生成任务不能因为高级编码器不可用而整体失败，所以这里把回退集中处理。
    """
    effective_codec = _get_effective_video_codec(codec)
    try:
        clip.write_videofile(output_file, codec=effective_codec, **kwargs)
        return effective_codec
    except Exception as exc:
        if effective_codec == _DEFAULT_VIDEO_CODEC:
            raise
        return _fallback_write_videofile(
            clip,
            output_file,
            failed_codec=effective_codec,
            reason=str(exc),
            **kwargs,
        )


def _escape_ffmpeg_concat_path(file_path: str) -> str:
    # concat demuxer 使用单引号包裹路径，路径中的单引号需要先转义。
    return file_path.replace("'", "'\\''")


def _format_ffmpeg_concat_path(file_path: str) -> str:
    """
    生成 concat demuxer 文件列表中的路径。

    FFmpeg 官方文档要求 concat list 中的特殊字符和空格需要转义；Windows
    绝对路径里的反斜杠也容易被解析成转义字符。这里统一转成正斜杠形式，
    让 `C:\\Users\\...` 变成 `C:/Users/...`，再处理单引号，兼容 macOS/Linux。
    """
    absolute_path = os.path.abspath(file_path)
    return _escape_ffmpeg_concat_path(absolute_path.replace("\\", "/"))


def concat_video_clips_with_ffmpeg(
    clip_files: List[str],
    output_file: str,
    threads: int,
    output_dir: str,
    max_duration: float | None = None,
):
    concat_list_file = os.path.join(output_dir, "ffmpeg-concat-list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as fp:
        for clip_file in clip_files:
            fp.write(f"file '{_format_ffmpeg_concat_path(clip_file)}'\n")

    def build_command(codec: str) -> list[str]:
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list_file,
            "-c:v",
            codec,
            "-threads",
            str(threads or 2),
            "-pix_fmt",
            "yuv420p",
        ]
        if max_duration is not None and max_duration > 0:
            command.extend(["-t", f"{max_duration:.3f}"])
        command.append(output_file)
        return command

    def run_concat(codec: str):
        command = build_command(codec)
        # 使用 ffmpeg 只做一次串联与编码，避免 MoviePy 逐段合并时反复重编码，
        # 从而降低画质劣化与颜色偏移风险。
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_message or "ffmpeg concat failed")
        return codec

    try:
        effective_codec = _get_effective_video_codec()
        try:
            return run_concat(effective_codec)
        except Exception as exc:
            if effective_codec == _DEFAULT_VIDEO_CODEC:
                raise
            result_codec = run_concat(_DEFAULT_VIDEO_CODEC)
            _disable_runtime_video_codec(effective_codec, str(exc))
            return result_codec
    finally:
        delete_files(concat_list_file)


def _sanitize_image_file(image_path: str) -> str:
    # 某些本地图片虽然能被 Pillow 打开，但会因为损坏的 EXIF/eXIf 元数据导致
    # ImageClip 在解析阶段直接抛异常。这里重新导出一份“干净图片”，把坏元数据剥离掉。
    image_root, _ = os.path.splitext(image_path)
    sanitized_path = f"{image_root}.sanitized.png"

    with Image.open(image_path) as image:
        image.load()
        # 统一导出为 PNG，避免 JPEG/PNG 不同元数据路径继续把坏块带过去。
        cleaned_image = Image.new(image.mode, image.size)
        cleaned_image.putdata(list(image.getdata()))
        cleaned_image.save(sanitized_path)

    return sanitized_path


def _open_image_clip_with_fallback(image_path: str):
    # 优先直接打开原始图片；如果因为损坏元数据失败，再尝试生成无元数据副本。
    try:
        return ImageClip(image_path), image_path
    except Exception as exc:
        logger.warning(
            f"failed to open image directly, trying sanitized copy: {image_path}, error: {str(exc)}"
        )
        sanitized_path = _sanitize_image_file(image_path)
        return ImageClip(sanitized_path), sanitized_path


def _open_video_clip_quietly(video_path: str, audio: bool = False) -> VideoFileClip:
    """
    安静地打开视频文件，避免 MoviePy 2.1.x 把 ffmpeg 探测信息直接打印到 stdout。

    背景：
    当前依赖版本的 `FFMPEG_VideoReader` 内部存在 `print(self.infos)` 和
    `print(ffmpeg command)`，读取无音轨的中间视频时会输出
    `audio_found: False`。这只是输入素材 metadata，不代表最终成片没有音频，
    但会误导 WebUI/终端用户以为生成失败。

    实现：
    1. 只在打开 VideoFileClip 的短窗口内重定向 stdout；
    2. 默认 `audio=False`，因为项目视频素材阶段不需要保留素材原声，
       最终音频会在 `generate_video()` 阶段统一挂载；
    3. 如果依赖库确实输出了内容，降级为 debug 日志，便于必要时排查。
    """
    captured_stdout = io.StringIO()
    with redirect_stdout(captured_stdout):
        clip = VideoFileClip(video_path, audio=audio)

    moviepy_stdout = captured_stdout.getvalue().strip()
    if moviepy_stdout:
        logger.debug(
            "suppressed MoviePy video reader stdout for "
            f"{video_path}, chars: {len(moviepy_stdout)}"
        )

    return clip


def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]

    for file in files:
        try:
            os.remove(file)
        except Exception as e:
            logger.debug(f"failed to delete file {file}: {str(e)}")


def _get_mood_from_script(script_text: str) -> str:
    text = script_text.lower()
    moods = {
        'horror': ['scary', 'blood', 'ghost', 'dark', 'evil', 'creepy', 'nightmare', 'misteri', 'seram', 'hantu'],
        'epic': ['history', 'battle', 'war', 'empire', 'king', 'ancient', 'hero', 'sejarah', 'perang', 'kerajaan'],
        'happy': ['funny', 'laugh', 'joke', 'smile', 'happy', 'lucu', 'tawa', 'senang'],
        'sad': ['cry', 'tears', 'heartbreak', 'tragedy', 'sedih', 'tangis', 'tragedi'],
        'calm': ['peace', 'relax', 'nature', 'meditation', 'tenang', 'damai', 'alam'],
        'tech': ['future', 'robot', 'ai', 'cyber', 'technology', 'teknologi', 'masa depan'],
    }
    for mood, keywords in moods.items():
        if any(kw in text for kw in keywords):
            return mood
    return "general"

def _download_dynamic_bgm(mood: str, song_dir: str) -> str:
    """Dynamically download background music from YouTube using yt-dlp."""
    import subprocess
    import os
    import glob
    import uuid
    
    mood_dir = os.path.join(song_dir, mood)
    os.makedirs(mood_dir, exist_ok=True)
    
    # Check if we already have songs, maybe reuse them 80% of the time
    existing_songs = glob.glob(os.path.join(mood_dir, "*.mp3"))
    if existing_songs and random.random() < 0.8:
        return random.choice(existing_songs)
        
    search_query = f"{mood} background music no copyright"
    logger.info(f"Dynamically downloading BGM for mood '{mood}' via YouTube (query: {search_query})")
    
    output_template = os.path.join(mood_dir, f"{mood}_{uuid.uuid4().hex[:8]}.%(ext)s")
    
    try:
        # Require yt-dlp to be installed or available in PATH
        subprocess.run([
            "yt-dlp",
            "ytsearch1:" + search_query,
            "-x", "--audio-format", "mp3",
            "--audio-quality", "5",
            "--match-filter", "duration < 600", # Less than 10 mins
            "-o", output_template
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        new_songs = glob.glob(os.path.join(mood_dir, "*.mp3"))
        if new_songs:
            return sorted(new_songs, key=os.path.getctime, reverse=True)[0]
    except Exception as e:
        logger.warning(f"Failed to dynamically download BGM: {e}")
        if existing_songs:
            return random.choice(existing_songs)
            
    return ""

def get_bgm_file(bgm_type: str = "random", bgm_file: str = "", script_text: str = ""):
    if not bgm_type:
        return ""

    if bgm_file:
        try:
            resolved_bgm_file = bgm_service.resolve_bgm_file(bgm_file)
        except ValueError as exc:
            # API 请求里的 bgm_file 来自用户输入，只允许解析到用户 BGM 或内置
            # 歌曲目录，阻止 MoviePy 读取配置、密钥等任意服务器文件。
            logger.warning(
                f"reject unsafe bgm file: {bgm_file}, error: {str(exc)}"
            )
            return ""
        return resolved_bgm_file

    song_dir = utils.song_dir()
    
    if script_text and bgm_type == "random":
        mood = _get_mood_from_script(script_text)
        logger.info(f"Smart BGM Matcher detected mood: {mood}")
        
        dynamic_bgm = _download_dynamic_bgm(mood, song_dir)
        if dynamic_bgm:
            logger.info(f"Selected Dynamic BGM: {dynamic_bgm}")
            return dynamic_bgm

    # Fallback to random in root song_dir
    if bgm_type == "random":
        files = bgm_service.list_bgm_files()
        if not files:
            logger.warning("no background music files found")
            return ""
        chosen = random.choice(files)
        logger.info(f"Selected fallback random BGM: {chosen}")
        return chosen

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    pacing_mode: str = "default",
    transition_speed: float = 0.5,
    apply_ken_burns: bool = True,
    color_enhancement: bool = True,
    enable_pattern_interrupts: bool = True,
    clip_speed: float = 1.0,
) -> str:


    audio_clip = AudioFileClip(audio_file)
    # [FIX] VBR MP3 duration bug in MoviePy: Use ffprobe/pydub for accurate audio duration
    def get_accurate_audio_duration(file_path):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(file_path)
            return len(audio) / 1000.0
        except Exception as e:
            logger.warning(f"pydub failed to get accurate audio duration: {e}")
            import subprocess
            try:
                status = utils.check_ffmpeg_status()
                if status["ffprobe"]:
                    ffprobe_exe = status["ffprobe_path"]
                    cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    return float(result.stdout.strip())
            except Exception:
                pass
        return audio_clip.duration

    audio_duration = get_accurate_audio_duration(audio_file)
    logger.info(f"Accurate audio duration fixed: {audio_duration} seconds (was {audio_clip.duration})")
    close_clip(audio_clip)
    
    logger.info(f"maximum clip duration: {max_clip_duration} seconds")
    required_video_duration = _get_required_video_duration(audio_duration)
    logger.info(
        f"required video duration: {required_video_duration:.2f} seconds "
        f"(audio duration + {_VIDEO_DURATION_SAFETY_MARGIN:.2f}s safety margin)"
    )

    transition_value = getattr(video_transition_mode, "value", video_transition_mode)
    normalized_clip_speed = utils.normalize_clip_speed(clip_speed)
    if normalized_clip_speed != 1.0:
        logger.info(f"clip playback speed: {normalized_clip_speed:.2f}x")
    source_clip_duration = max_clip_duration * normalized_clip_speed
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []

    
    # T4-1: Init Pattern Interrupt state
    last_interrupt_time = 0.0
    available_effects = []
    
    # T4-2: Pacing Curve (Chop on Demand)
    # Instead of pre-chopping, we Select -> Chop -> Add based on current timeline position.
    
    # helper to track source usage if sequential
    source_states = {}
    for vp in video_paths:
        try:
            with VideoFileClip(vp) as c:
               dur = c.duration
               size = c.size
            source_states[vp] = {
                "duration": dur,
                "current_pos": 0.0,
                "size": size
            }
        except Exception as e:
            logger.error(f"failed to read video {vp}: {e}")
            
    if not source_states:
        raise ValueError("No valid video sources found")

    video_duration = 0.0
    subclipped_items = []
    seq_idx = 0
    
    while video_duration < audio_duration:
        req_dur = pacing.get_clip_duration(pacing_mode, video_duration, audio_duration)
        req_dur = min(req_dur, max_clip_duration)
        if req_dur < 1.0: req_dur = 1.0
        
        selected_path = None
        clip_start, clip_end = 0.0, 0.0
        
        if video_concat_mode.value == VideoConcatMode.random.value:
             selected_path = random.choice(video_paths)
             v_info = source_states.get(selected_path)
             if not v_info: continue
             
             max_start = max(0, v_info["duration"] - req_dur)
             clip_start = random.uniform(0, max_start)
             clip_end = min(clip_start + req_dur, v_info["duration"])
             
        else: # Sequential
             # Try current sequence video
             found = False
             for _ in range(len(video_paths) * 2): # Try to find a valid segment
                 selected_path = video_paths[seq_idx % len(video_paths)]
                 v_info = source_states.get(selected_path)
                 if not v_info:
                     seq_idx += 1
                     continue

                 if v_info["current_pos"] < v_info["duration"] - 0.5:
                     clip_start = v_info["current_pos"]
                     clip_end = min(clip_start + req_dur, v_info["duration"])
                     v_info["current_pos"] = clip_end
                     found = True
                     break
                 else:
                     # Exhausted, move next and reset this one for valid looping
                     v_info["current_pos"] = 0
                     seq_idx += 1
             
             if not found:
                 # Fallback
                 selected_path = video_paths[0]
                 v_info = source_states[selected_path]
                 clip_start = 0
                 clip_end = min(req_dur, v_info["duration"])

        if selected_path:
             v_info = source_states[selected_path]
             dur = clip_end - clip_start
             if dur > 0.1:
                 subclipped_items.append(SubClippedVideoClip(
                     file_path=selected_path,
                     start_time=clip_start,
                     end_time=clip_end,
                     width=v_info["size"][0],
                     height=v_info["size"][1]
                 ))
                 video_duration += dur

    logger.debug(f"generated {len(subclipped_items)} subclips using {pacing_mode} pacing")
    
    # Create a new list for the final processed clips
    processed_clips = []

    # Process the generated clips
    video_duration = 0.0 # Track processed duration
    for i, subclipped_item in enumerate(subclipped_items):
        if video_duration >= required_video_duration:
            break
        
        logger.debug(
            f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, "
            f"source: {os.path.basename(subclipped_item.source_file_path)}, "
            f"current duration: {video_duration:.2f}s, "
            f"remaining: {required_video_duration - video_duration:.2f}s"
        )
        
        try:
            clip = _open_video_clip_quietly(subclipped_item.file_path).subclipped(
                subclipped_item.start_time, subclipped_item.end_time
            )
            # 播放速度属于素材本身属性，应在转场前应用。这样 Fade/Slide 等一秒转场
            # 不会跟随素材速度变成 0.5 秒或 2 秒；后续最大时长裁剪继续作为
            # 浮点误差或异常素材时长的安全兜底，保证最终片段不突破配置上限。
            if normalized_clip_speed != 1.0:
                clip = clip.with_speed_scaled(normalized_clip_speed)
            clip_duration = clip.duration
            
            # T1-5: Color Enhancement (Auto-normalization/Boost)
            if color_enhancement:
                # Apply slight saturation boost and contrast
                clip = clip.with_effects([vfx.MultiplyColor(1.05)]) # Slight localized brightness/saturation boost
                # Note: True auto-normalization is expensive. This heuristic improves vibrancy.

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")
                
                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    # T0-1: Use blurred background instead of black bars
                    try:
                        from PIL import Image, ImageFilter
                        bg_clip = clip.resized(new_size=(video_width, video_height))
                        def blur_frame(get_frame, t):
                            frame = get_frame(t)
                            img = Image.fromarray(frame)
                            blurred = img.filter(ImageFilter.GaussianBlur(radius=30))
                            return np.array(blurred)
                        bg_clip = bg_clip.transform(blur_frame).with_duration(clip_duration)
                    except Exception as blur_err:
                        logger.warning(f"blur background failed, falling back to black: {blur_err}")
                        bg_clip = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)

                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([bg_clip, clip_resized])
            
            # T1-1: Ken Burns Effect
            if apply_ken_burns:
                # Apply to static images or clips where we want dynamic motion
                # Since we don't know if source is static, we apply subtly to add production value
                clip = video_effects.zoomin_transition(clip, 0)

            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if not video_transition_mode or video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            else:
                transition_val = video_transition_mode.value
                if transition_val == VideoTransitionMode.fade_in.value:
                    clip = video_effects.fadein_transition(clip, transition_speed)
                elif transition_val == VideoTransitionMode.fade_out.value:
                    clip = video_effects.fadeout_transition(clip, transition_speed)
                elif transition_val == VideoTransitionMode.slide_in.value:
                    clip = video_effects.slidein_transition(clip, transition_speed, shuffle_side)
                elif transition_val == VideoTransitionMode.slide_out.value:
                    clip = video_effects.slideout_transition(clip, transition_speed, shuffle_side)
                elif transition_val == VideoTransitionMode.whip_pan.value:
                    clip = video_effects.slidein_transition(clip, transition_speed, shuffle_side)
                elif transition_val == VideoTransitionMode.zoom.value:
                    clip = video_effects.zoomin_transition(clip, transition_speed)
                elif transition_val == VideoTransitionMode.shuffle.value:
                    transition_funcs = [
                        lambda c: video_effects.fadein_transition(c, transition_speed),
                        lambda c: video_effects.fadeout_transition(c, transition_speed),
                        lambda c: video_effects.slidein_transition(c, transition_speed, shuffle_side),
                        lambda c: video_effects.slideout_transition(c, transition_speed, shuffle_side),
                        lambda c: video_effects.zoomin_transition(c, transition_speed),
                        lambda c: video_effects.zoomout_transition(c, transition_speed),
                    ]
                    shuffle_transition = random.choice(transition_funcs)
                    clip = shuffle_transition(clip)

            # T4-1: Pattern Interrupts
            # Check if we should apply effect (every 5-8s)
            if enable_pattern_interrupts and available_effects: # Changed from params.enable_pattern_interrupts
                # video_duration is current start time
                interval = random.uniform(5.0, 8.0)
                if (video_duration - last_interrupt_time) > interval:
                     effect_func = random.choice(available_effects)
                     try:
                         # Apply effect
                         logger.info(f"applying pattern interrupt {effect_func.__name__} at {video_duration:.2f}s")
                         affected_clip = effect_func(clip)
                         
                         # Ensure audio is preserved
                         if clip.audio and not affected_clip.audio:
                             affected_clip = affected_clip.with_audio(clip.audio)
                         
                         clip = affected_clip
                         last_interrupt_time = video_duration
                     except Exception as e:
                         logger.warning(f"failed to apply pattern interrupt: {e}")

            # T3-3: Auto-SFX on transition

            # Remove original audio (stock noise)
            clip = clip.without_audio()
            
            # Add SFX if transition occurred (simple check: mode is not None)
            if video_transition_mode and video_transition_mode != VideoTransitionMode.none:
                sfx_file = sfx.get_random_transition_sfx()
                if sfx_file:
                    try:
                        sfx_audio = AudioFileClip(sfx_file)
                        # Ensure SFX doesn't exceed clip duration (though rare for short SFX)
                        if sfx_audio.duration > clip.duration:
                             sfx_audio = sfx_audio.subclipped(0, clip.duration)
                        
                        # Set audio (replaces existing, which is None/Silent now)
                        clip = clip.with_audio(sfx_audio)
                    except Exception as sfx_err:
                         logger.warning(f"failed to add sfx: {sfx_err}")

            # T1-2: Pacing logic guarantees duration, but if filters changed it, ensure it's correct
            # Wait, Ken Burns uses transform which preserves duration. Transitions might add effects.
            # No clipping needed unless duration grew unexpectedly.
            
            # write clip to temp file (T0-2: bitrate control)
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            clip.write_videofile(clip_file, logger=None, fps=fps, codec=video_codec, preset=video_preset, bitrate="8000k")
            clip_duration_saved = clip.duration
            close_clip(clip)

            processed_clips.append(
                SubClippedVideoClip(
                    file_path=clip_file,
                    duration=clip_duration_saved,
                    width=clip_w,
                    height=clip_h,
                    source_file_path=subclipped_item.source_file_path,
                )
            )
            video_duration += clip_duration_saved
            
        except Exception as e:
            import traceback
            logger.error(f"failed to process clip: {str(e)}\n{traceback.format_exc()}")
    
    # loop processed clips until the video duration covers the audio duration and the small safety margin.
    if video_duration < required_video_duration:
        logger.warning(
            f"video duration ({video_duration:.2f}s) is shorter than required duration "
            f"({required_video_duration:.2f}s), looping clips to match audio length."
        )
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= required_video_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(
            f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, "
            f"required duration: {required_video_duration:.2f}s, "
            f"looped {len(processed_clips)-len(base_clips)} clips"
        )
     
    # T0-4: One-pass concatenation using FFmpeg concat demuxer
    # Instead of iteratively merging clips (N-1 re-encodes = quality loss),
    # use FFmpeg's concat demuxer for a single-pass merge.
    logger.info(f"starting one-pass clip merge ({len(processed_clips)} clips)")
    if not processed_clips:
        logger.error("no clips available for merging")
        raise ValueError("No valid video clips were processed successfully. Check if download failed or files are corrupted.")
    
    # if there is only one clip, use it directly
    if len(processed_clips) == 1:
        logger.info("using single clip directly")
        shutil.copy(processed_clips[0].file_path, combined_video_path)
        delete_files([processed_clips[0].file_path])
        logger.info("video combining completed")
        return combined_video_path
    
    # Write concat list file for FFmpeg
    concat_list_path = f"{output_dir}/concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for clip in processed_clips:
            # FFmpeg concat demuxer requires forward slashes and escaped quotes
            safe_path = clip.file_path.replace("\\", "/")
            f.write(f"file '{safe_path}'\n")
    
    # Single-pass merge via FFmpeg concat demuxer (stream copy = no re-encode)
    import subprocess
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        ffmpeg_cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-t", str(audio_duration),
            "-c", "copy",
            combined_video_path,
        ]
        logger.info(f"running FFmpeg concat: {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning(f"FFmpeg concat failed (rc={result.returncode}): {result.stderr[:500]}")
            logger.info("falling back to moviepy concatenation")
            # Fallback: load all clips and concat via moviepy (single write)
            all_clips = [VideoFileClip(c.file_path) for c in processed_clips]
            merged = concatenate_videoclips(all_clips)
            if merged.duration > audio_duration:
                merged = merged.subclipped(0, audio_duration)

            merged.write_videofile(
                combined_video_path,
                codec=video_codec,
                preset=video_preset,
                threads=optimal_threads if threads == 2 else threads,
                audio_codec="aac",
                fps=fps,
                bitrate="8000k",
            )
            for c in all_clips:
                close_clip(c)
            close_clip(merged)
    except Exception as e:
        logger.error(f"one-pass merge failed: {str(e)}")
        raise
    
    # clean temp files
    clip_files = [clip.file_path for clip in processed_clips]
    clip_files.append(concat_list_path)
    delete_files(clip_files)
            
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # 字幕换行必须在真正创建 TextClip 前完成，否则 MoviePy 只会按原始文本
    # 计算渲染区域。这里用 PIL 按当前字体和字号测量宽度，确保每一行都尽量
    # 控制在视频可用宽度内，避免大字号或中文长句直接溢出画面。
    font = ImageFont.truetype(font, fontsize)
    max_width = int(max_width)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, fontsize
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    def split_long_token(token):
        # 当一个 token 本身就超宽时（常见于中文无空格长句，或英文超长单词），
        # 退化为字符级拆分。关键点是：检测到 candidate 超宽时，先提交上一个
        # 仍然合法的 current，再把当前字符放入下一行，不能把超宽字符塞回上一行。
        lines = []
        current = ""
        for char in token:
            candidate = f"{current}{char}"
            candidate_width, _ = get_text_size(candidate)
            if candidate_width <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
        return lines

    lines = []
    current = ""
    words = text.split(" ")
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)

        word_width, _ = get_text_size(word)
        if word_width <= max_width:
            current = word
        else:
            lines.extend(split_long_token(word))
            current = ""

    if current:
        lines.append(current)

    line_start_punctuation = "，。！？；：、,.!?;:)]}）】》」』”’"
    for index in range(1, len(lines)):
        # 中文长句按字符拆分时，最后一个句号、逗号等闭合标点可能被单独
        # 放到下一行，导致字幕背景被异常撑高，视觉上像一个小点掉在正文
        # 下方。这里在不重新设计换行算法的前提下，把上一行最后一个字
        # 移到标点行前面，让标点跟随文字显示，兼容中英文常见闭合标点。
        if not lines[index] or lines[index][0] not in line_start_punctuation:
            continue
        if len(lines[index - 1]) <= 1:
            continue

        candidate = f"{lines[index - 1][-1]}{lines[index]}"
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            lines[index] = candidate
            lines[index - 1] = lines[index - 1][:-1]

    result = "\n".join(line.strip() for line in lines if line.strip()).strip()
    height = len(lines) * height
    return result, height


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    # 字幕背景色来自 API/WebUI 参数，可能为空或格式不规范。这里统一只接受
    # #RRGGBB 形式，非法值回退为黑色，避免 PIL 渲染阶段抛出异常中断任务。
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        try:
            return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        except ValueError:
            pass
    return (0, 0, 0)


def _rounded_subtitle_background_clip(
    width: int,
    height: int,
    color: str,
    alpha: int = 140,
    radius: int = 16,
) -> ImageClip:
    # 新字幕背景仅在用户显式开启时使用：通过 RGBA 图片绘制圆角半透明底板，
    # 再交给 MoviePy 作为透明 ImageClip 参与合成。这样默认路径完全不变，
    # 同时可以低成本试验更柔和的字幕视觉效果。
    rgb = _hex_to_rgb(color)
    safe_alpha = max(0, min(255, int(alpha)))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, max(0, width - 1), max(0, height - 1)],
        radius=max(0, int(radius)),
        fill=(rgb[0], rgb[1], rgb[2], safe_alpha),
    )
    return ImageClip(np.array(img), transparent=True)


def _get_visible_center_position(
    text_clip: TextClip,
    container_width: int,
    container_height: int,
) -> tuple[int, int]:
    """
    按文字真实可见像素把 TextClip 放到背景容器中心。

    MoviePy 的 TextClip 会按字体行高和 baseline 创建透明画布。很多字体的
    可见字形并不在这个画布的几何中心，直接 `with_position("center")`
    会把整块透明画布居中，导致字幕看起来偏上或偏下。这里读取 TextClip
    的透明 mask，只根据实际有像素的 bbox 计算偏移，让用户看到的文字
    在字幕背景里视觉居中。
    """
    x = int(round((container_width - text_clip.w) / 2))
    y = int(round((container_height - text_clip.h) / 2))

    try:
        if text_clip.mask is None:
            return x, y

        mask_frame = text_clip.mask.get_frame(0)
        ys, _ = np.where(mask_frame > 0.01)
        if len(ys) == 0:
            return x, y

        visible_top = int(ys.min())
        visible_bottom = int(ys.max())
        visible_height = visible_bottom - visible_top + 1
        y = int(round((container_height - visible_height) / 2 - visible_top))
    except Exception as exc:
        logger.debug(f"failed to center subtitle text by visible mask: {str(exc)}")

    return x, y


def subtitle_colors_are_indistinguishable(params: VideoParams) -> bool:
    """判断字幕文字和背景是否同色，提醒用户可能无法看清字幕。"""
    if not params.subtitle_enabled or not params.text_background_color:
        return False

    def normalize_color(value):
        if isinstance(value, bool):
            return "#000000" if value else ""
        return str(value or "").strip().lower()

    text_color = normalize_color(params.text_fore_color)
    background_color = normalize_color(params.text_background_color)
    return bool(text_color and text_color == background_color)


@lru_cache(maxsize=64)
def _subtitle_font_supports_sample(font_path: str, sample: str) -> bool:
    """检查字体是否包含样本文字需要的字形，并缓存重复检查结果。"""
    try:
        font = ImageFont.truetype(font_path, 30)
        missing_mask = font.getmask("\U0010ffff")
        missing_signature = (
            missing_mask.size,
            missing_mask.getbbox(),
            bytes(missing_mask),
        )
        for char in sample:
            char_mask = font.getmask(char)
            char_signature = (
                char_mask.size,
                char_mask.getbbox(),
                bytes(char_mask),
            )
            if char_mask.getbbox() is None or char_signature == missing_signature:
                return False
        return True
    except Exception as e:
        # 字体探测失败不应阻止用户生成；保留日志供环境兼容问题排查。
        logger.warning(f"failed to inspect subtitle font glyphs: {font_path}, {e}")
        return True


def subtitle_font_supports_text(font_path: str, text: str) -> bool:
    """检查字体能否绘制文本中的字母和数字，忽略空白及标点符号。"""
    sample = "".join(
        dict.fromkeys(
            char
            for char in str(text or "")
            if unicodedata.category(char)[0] in {"L", "N"}
        )
    )[:64]
    if not sample:
        return True
    return _subtitle_font_supports_sample(font_path, sample)


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
    bgm_file_override: str | None = None,
) -> bool:
    """
    合成最终视频，并返回本次背景音乐处理是否成功。

    返回值只描述 BGM 处理状态：没有请求 BGM 或成功混合时返回 True；请求了
    BGM 但加载、特效或混合失败时返回 False。即使 BGM 失败仍会继续输出只有
    旁白的视频，让任务编排层决定是否向用户展示降级警告。
    """
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    # Determine font path with fallback
    if not params.font_name:
        params.font_name = "STHeitiMedium.ttc"
    
    font_path = os.path.join(utils.font_dir(), params.font_name)
    if os.name == "nt":
        font_path = font_path.replace("\\", "/")

    # Verify font exists and apply fallback if needed
    if not os.path.exists(font_path):
        logger.error(f"  ❌ FONT NOT FOUND: {font_path}")
        # Fallback to a common Linux font if we're in Docker
        if os.name != "nt":
            fallback_fonts = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/MoneyPrinterTurbo/resource/fonts/STHeitiMedium.ttc" # Internal fallback
            ]
            for f in [os.path.join(utils.font_dir(), 'STHeitiMedium.ttc'), os.path.join(utils.font_dir(), 'Charm-Bold.ttf'), '/MoneyPrinterTurbo/resource/fonts/STHeitiMedium.ttc']:
                if os.path.exists(f):
                    logger.warning(f"  ⚠️ falling back to system font: {f}")
                    font_path = f
                    break
    else:
        logger.info(f"  ✅ using font: {font_path}")

    # Log font and subtitle status
    if params.subtitle_enabled:
        logger.info(f"  ⑤ subtitle font: {font_path}")
    else:
        logger.info(f"  ⑤ subtitles disabled, using font for overlays: {font_path}")

    try:
        video_clip = VideoFileClip(video_path) # Keep audio (SFX from combine_videos)
    except Exception as e:
        logger.error(f"failed to load video clip {video_path}: {e}")
        raise

    # Fetch accurate audio duration via imageio_ffmpeg (failsafe)
    true_audio_duration = 0.0
    try:
        status = utils.check_ffmpeg_status()
        if status["ffprobe"]:
            ffprobe_exe = status["ffprobe_path"]
            cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
            import subprocess
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            true_audio_duration = float(result.stdout.strip())
            logger.info(f"Accurate audio duration fixed in generate_video: {true_audio_duration} seconds")
    except Exception as ffprobe_err:
        logger.warning(f"ffprobe failed to get accurate audio duration: {ffprobe_err}")

    # MoviePy's CompositeAudioClip.close() doesn't close child AudioFileClips.
    # Use ExitStack to ensure handles are released.
    with ExitStack() as clip_stack:
        source_video_clip = clip_stack.enter_context(
            _open_video_clip_quietly(video_path)
        )
        voice_source_clip = clip_stack.enter_context(AudioFileClip(audio_path))
        video_clip = source_video_clip
        
        audio_clip = voice_source_clip.with_effects(
            [afx.AudioNormalize(), afx.MultiplyVolume(params.voice_volume)]
        )
        if true_audio_duration > 0.0:
            audio_clip.duration = true_audio_duration
        
        # Strictly trim video duration to match the voice length (prevent overflow)
        if video_clip.duration > audio_clip.duration:
            video_clip = video_clip.subclipped(0, audio_clip.duration)

        overlay_clips = []
        
        # T4-4: Number Counter Animation
        if params.enable_number_counter and subtitle_path and os.path.exists(subtitle_path):
            try:
                from app.services import subtitle
                subs = subtitle.file_to_subtitles(subtitle_path)
                numbers = number_counter.extract_numbers_from_script(None, subs)
                for num in numbers:
                    counter_clip = number_counter.create_counter_clip(
                        target_number=num['value'],
                        duration=1.5,
                        font_path=font_path,
                        color=params.text_fore_color
                    )
                    counter_clip = counter_clip.with_position("center").with_start(num['start'])
                    overlay_clips.append(counter_clip)
            except Exception as e:
                logger.error(f"failed to add number counters: {e}")

        # T4-5: Progress Bar Overlay
        if params.enable_progress_bar and subtitle_path and os.path.exists(subtitle_path):
            try:
                 from app.services import subtitle
                 subs_for_progress = subtitle.file_to_subtitles(subtitle_path)
                 bar_clip = progress_overlay.create_progress_bar_clip(
                     video_size=(video_clip.w, video_clip.h),
                     subtitles=subs_for_progress,
                     video_duration=video_clip.duration,
                     fill_color=params.text_fore_color
                 )
                 if bar_clip:
                     overlay_clips.append(bar_clip)
            except Exception as e:
                logger.error(f"failed to add progress bar: {e}")

        # Combine base video with overlays (no subtitles here, they are burned via ASS later)
        if overlay_clips:
            video_clip = CompositeVideoClip([video_clip, *overlay_clips])
            
        # Audio Mixing: Voice + BGM + SFX
        audio_source = [audio_clip] # Start with normalized voice
        
        # 1. Add SFX (from video track) if present
        if video_clip.audio:
            audio_source.append(video_clip.audio)

        bgm_enabled = bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume)
        bgm_file = ""
        if bgm_enabled:
            bgm_file = (
                bgm_file_override if bgm_file_override is not None
                else get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file, script_text=getattr(params, 'video_subject', getattr(params, 'script', '')))
            )
        
        bgm_mix_succeeded = True
        if bgm_file:
            try:
                bgm_source_clip = clip_stack.enter_context(AudioFileClip(bgm_file))
                bgm_clip = bgm_source_clip
                if bgm_clip.duration and bgm_clip.duration > video_clip.duration:
                    bgm_clip = bgm_clip.subclipped(0, video_clip.duration)
                else:
                    if bgm_file_override is None:
                        bgm_clip = bgm_clip.with_effects([afx.AudioLoop(duration=video_clip.duration)])
                    
                bgm_clip = bgm_clip.with_effects([
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeIn(2),
                    afx.AudioFadeOut(3),
                ])
                audio_source.append(bgm_clip)
            except Exception:
                bgm_mix_succeeded = False
                logger.exception(f"failed to mix background music: type={params.bgm_type}, file={bgm_file}")
                
        try:
            final_audio = CompositeAudioClip(audio_source)
            final_audio = final_audio.with_duration(video_clip.duration)
            video_clip = video_clip.with_audio(final_audio)
        except Exception as e:
            logger.error(f"failed to composite audio: {str(e)}")
            video_clip = video_clip.with_audio(audio_clip)
            
        # Watermark overlay
        watermark_clip = None
        if params.watermark_text:
            logger.info(f"  ⑥ watermark text: {params.watermark_text}")
            wm_font = font_path if font_path else "Arial"
            watermark_clip = TextClip(
                text=params.watermark_text,
                font=wm_font,
                font_size=max(24, int(params.font_size * 0.4)),
                color="#FFFFFF",
            )
            watermark_clip = watermark_clip.with_duration(video_clip.duration)
            watermark_clip = watermark_clip.with_opacity(params.watermark_opacity)
        elif params.watermark_image and os.path.exists(params.watermark_image):
            logger.info(f"  ⑥ watermark image: {params.watermark_image}")
            watermark_clip = ImageClip(params.watermark_image)
            wm_scale = (video_width * 0.15) / watermark_clip.w
            watermark_clip = watermark_clip.resized(wm_scale)
            watermark_clip = watermark_clip.with_duration(video_clip.duration)
            watermark_clip = watermark_clip.with_opacity(params.watermark_opacity)

        if watermark_clip:
            margin = 20
            pos = params.watermark_position or "bottom_right"
            if pos == "top_left":
                wm_pos = (margin, margin)
            elif pos == "top_right":
                wm_pos = (video_width - watermark_clip.w - margin, margin)
            elif pos == "bottom_left":
                wm_pos = (margin, video_height - watermark_clip.h - margin)
            elif pos == "center":
                wm_pos = ("center", "center")
            else:  # bottom_right (default)
                wm_pos = (video_width - watermark_clip.w - margin, video_height - watermark_clip.h - margin)

            watermark_clip = watermark_clip.with_position(wm_pos)
            video_clip = CompositeVideoClip([video_clip, watermark_clip])

        # Hook & CTA
        overlay_clips = [video_clip]
        try:
            hook_text = getattr(params, "hook_text", "")
            if not hook_text and getattr(params, "enable_hook", False):
                hook_text = hook_generator.get_hook_text(
                    category=params.video_subject, 
                    subject=params.video_subject,
                    auto_optimize=getattr(params, "auto_optimize", True)
                )
                
            if hook_text:
                hook_duration = getattr(params, "hook_duration", 3.0)
                hook_font = font_path if font_path else "Arial"
                hook_width = int(video_width * 0.7)
                hook_clip = TextClip(
                    text=hook_text,
                    font=hook_font,
                    font_size=min(70, max(40, int(params.font_size * 1.1))),
                    color="#FFFF00",
                    stroke_color="#000000",
                    stroke_width=2,
                    method="caption",
                    size=(hook_width, None),
                    horizontal_align="center",
                    vertical_align="center",
                    interline=10
                )
                hook_clip = hook_clip.with_start(0).with_duration(hook_duration)
                hook_clip = hook_clip.with_position(("center", "center"))
                
                if hasattr(video_effects, "zoom_burst"):
                    hook_clip = video_effects.zoom_burst(hook_clip, duration=0.8, zoom_to=1.15)
                    
                overlay_clips.append(hook_clip)
                logger.info(f"  ⑦ hook ('burn' styled, {hook_duration:.1f}s): {hook_text}")
        except Exception as e:
            logger.warning(f"Hook overlay failed (non-critical): {str(e)}")

        try:
            cta_text = hook_generator.get_cta_text()
            if cta_text and video_clip.duration > 5:
                cta_font = font_path if font_path else "Arial"
                cta_width = int(video_width * 0.8)
                cta_clip = TextClip(
                    text=cta_text.upper(),
                    font=cta_font,
                    font_size=64,
                    color="#FFD700",
                    stroke_color="#000000",
                    stroke_width=3,
                    method="caption",
                    size=(cta_width, None),
                    horizontal_align="center",
                    vertical_align="center"
                )
                cta_start = max(0, video_clip.duration - 3)
                cta_clip = cta_clip.with_start(cta_start).with_duration(3)
                cta_clip = cta_clip.with_position(("center", "center"))
                overlay_clips.append(cta_clip)
                logger.info(f"  ⑧ CTA: {cta_text}")
        except Exception as e:
            logger.warning(f"CTA overlay failed (non-critical): {str(e)}")

        if len(overlay_clips) > 1:
            video_clip = CompositeVideoClip(overlay_clips)

        clip_stack.callback(video_clip.close)
        
        # Write to temp file without subtitles
        temp_output_file = output_file.replace(".mp4", "_nosub.mp4")
        output_audio_fps = int(getattr(audio_clip, "fps", 0) or 44100)
        
        _write_videofile_with_codec_fallback(
            video_clip,
            output_file=temp_output_file,
            codec=_get_configured_video_codec(),
            audio_codec=audio_codec,
            audio_fps=output_audio_fps,
            audio_bitrate="192k",
            temp_audiofile_path=_get_temp_audio_dir(output_dir),
            threads=params.n_threads or optimal_threads,
            logger=None,
            fps=fps,
        )




    # Step 2: Burn in ASS Subtitles using native FFmpeg (blazingly fast, solves WinError 32)
    ass_subtitle_path = subtitle_path.replace(".srt", ".ass") if subtitle_path else None
    
    if ass_subtitle_path and os.path.exists(ass_subtitle_path):
        logger.info(f"Burning native FFmpeg ASS subtitles: {ass_subtitle_path}")
        
        import subprocess
        import shutil

        # Windows FFmpeg ASS filter path escaping is notoriously difficult.
        # Instead, we copy the ASS file to the output directory and use a relative name.
        ass_basename = "temp_subtitle.ass"
        local_ass_path = os.path.join(output_dir, ass_basename)
        try:
            shutil.copy2(ass_subtitle_path, local_ass_path)
        except shutil.SameFileError:
            pass

        # Use forward slashes for the input video path to be safe
        safe_temp_output = temp_output_file.replace('\\', '/')
        safe_output_file = output_file.replace('\\', '/')

        vf_string = f"ass='{ass_basename}'"
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        ffmpeg_cmd = [
            ffmpeg_exe,
            "-y",
            "-i", safe_temp_output,
            "-vf", vf_string,
            "-c:v", video_codec,
            "-b:v", "8000k",
            "-c:a", "copy",
            safe_output_file
        ]
        
        try:
            # Run ffmpeg from the output directory so it can find the ASS file natively
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=os.path.abspath(output_dir))
            os.remove(temp_output_file) # Clean up temp file
            logger.info(f"Successfully burned native subtitles to: {output_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg ASS burn failed. Target command: {' '.join(ffmpeg_cmd)}")
            logger.error(f"FFmpeg Error Output: {e.stderr.decode('utf-8')}")
            # Fallback: Just rename the video without subtitles so it doesn't fail completely
            if os.path.exists(output_file):
                os.remove(output_file)
            os.rename(temp_output_file, output_file)
    else:
        # No subtitles generated or needed, just rename temp to final
        if os.path.exists(output_file):
             os.remove(output_file)
        os.rename(temp_output_file, output_file)
        logger.info(f"No valid ASS subtitle found, video saved without text overlay.")
    return True


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    # WebUI 在某些二次生成场景下可能传入空素材列表，这里直接返回空结果，避免抛出 NoneType 异常。
    if not materials:
        return []

    # 仅返回通过预处理校验的素材，避免低分辨率图片继续进入后续的视频合成流程。
    valid_materials = []
    local_videos_dir = utils.storage_dir("local_videos", create=True)

    for material in materials:
        if not material.url:
            continue

        try:
            material_source_path = file_security.resolve_path_within_directory(
                local_videos_dir, material.url
            )
        except ValueError as exc:
            # local video_source 的素材路径来自 API 参数，必须限制在专用素材目录。
            # 允许用户传文件名，也兼容历史返回的绝对路径，但不允许逃逸到系统
            # 其他目录，避免任意文件读取或通过 MoviePy 探测本地敏感文件。
            logger.warning(
                f"skip unsafe local material: {material.url}, "
                f"local_videos_dir: {local_videos_dir}, error: {str(exc)}"
            )
            continue

        ext = utils.parse_extension(material_source_path)
        try:
            # 图片素材直接按图片方式读取，避免先走 VideoFileClip 误判后触发不稳定的回退分支。
            if ext in const.FILE_TYPE_IMAGES:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            else:
                clip = _open_video_clip_quietly(material_source_path)
        except Exception:
            # 非标准扩展名或探测失败时再回退到图片模式，兼容历史上直接传本地图片路径的情况。
            try:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            except Exception as exc:
                logger.warning(
                    f"skip unreadable local material: {material.url}, error: {str(exc)}"
                )
                continue
        try:
            width = clip.size[0]
            height = clip.size[1]
            if not is_material_resolution_acceptable(width, height):
                logger.warning(
                    f"low resolution material: {width}x{height}, minimum "
                    f"{_MIN_MATERIAL_DIMENSION}x{_MIN_MATERIAL_DIMENSION} required "
                    f"(tolerance {_MIN_DIMENSION_TOLERANCE}px)"
                )
                # 探测到低分辨率素材后立即关闭资源，并且不要把该素材返回给后续流程。
                close_clip(clip)
                continue

            if ext in const.FILE_TYPE_IMAGES:
                logger.info(f"processing image: {material_source_path}")
                # 探测尺寸时已经打开过一次素材，这里先释放探测句柄，再重新创建用于导出的图片 clip。
                close_clip(clip)
                # Create an image clip and set its duration to 3 seconds
                clip = (
                    ImageClip(material_source_path)
                    .with_duration(clip_duration)
                    .with_position("center")
                )
                # Apply a zoom effect using the resize method.
                # A lambda function is used to make the zoom effect dynamic over time.
                # The zoom effect starts from the original size and gradually scales up to 120%.
                # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
                # Note: 1 represents 100% size, so 1.2 represents 120% size.
                zoom_clip = clip.resized(
                    lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
                )

                final_clip = CompositeVideoClip([zoom_clip])

                # Output the video to a file.
                video_file = f"{material.url}.mp4"
                final_clip.write_videofile(video_file, codec=_get_configured_video_codec(), fps=30, logger=None)
                close_clip(clip)
                close_clip(final_clip)
                material.url = video_file
                logger.success(f"image processed: {video_file}")
            else:
                # 普通视频素材只需要读取尺寸做校验，校验完成后立即释放句柄即可。
                close_clip(clip)
                # Update url to the resolved absolute path so that downstream
                # stages (combine_videos) can open the file without re-resolving.
                material.url = material_source_path
        except Exception:
            close_clip(clip)
            raise

        valid_materials.append(material)

    return valid_materials
