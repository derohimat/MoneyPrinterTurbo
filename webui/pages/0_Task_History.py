import streamlit as st
import os
import sys
import time

# Add root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.services import state as sm
from app.services.task_worker import TaskWorker
from app.utils import utils, db

# Set page config
st.set_page_config(page_title="Task History", page_icon="📜", layout="wide")

# Ensure worker is running
@st.cache_resource
def start_worker():
    worker = TaskWorker.get_instance()
    worker.start()
    return worker

start_worker()

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_duration(seconds):
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _eta_label(avg_duration_s, pending_position):
    """Return human-readable ETA string."""
    if avg_duration_s is None:
        return "ETA: unknown (no history)"
    eta_s = avg_duration_s * pending_position
    m, s = divmod(int(eta_s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"⏱️ ETA ~{h}h {m}m"
    elif m:
        return f"⏱️ ETA ~{m}m {s}s"
    else:
        return f"⏱️ ETA ~{s}s"


# ─── Page ────────────────────────────────────────────────────────────────────

st.title("📜 Task History & Progress")

col_refresh, col_stats = st.columns([1, 3])
with col_refresh:
    if st.button("🔄 Refresh"):
        st.rerun()

# [N2] Show average job duration in header
avg_dur = db.get_avg_job_duration(last_n=10)
with col_stats:
    if avg_dur:
        st.caption(f"📊 Avg job duration (last 10): **{_fmt_duration(avg_dur)}**")

# ─── DB Jobs (batch queue) ────────────────────────────────────────────────────
db.init_db()
all_db_jobs = db.get_all_jobs(limit=100)
pending_jobs = [j for j in all_db_jobs if j.get("status") == "pending"]
processing_jobs = [j for j in all_db_jobs if j.get("status") == "processing"]

if all_db_jobs:
    st.subheader("🗂️ Batch Queue")
    for i, job in enumerate(all_db_jobs):
        status = job.get("status", "unknown")
        topic = job.get("topic", "Unknown")
        job_id = job.get("id", "")
        duration = job.get("duration_seconds")
        rating = job.get("rating")
        category = job.get("category", "")

        status_icon = {"success": "✅", "failed": "❌", "processing": "🔄", "pending": "⏳"}.get(status, "❓")

        with st.container():
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            with c1:
                st.write(f"**{topic}**")
                st.caption(f"`{job_id[:8]}` · {category}")
            with c2:
                st.write(f"{status_icon} **{status.title()}**")
                if duration:
                    st.caption(f"⏱ {_fmt_duration(duration)}")
                elif status == "pending":
                    # [N2] ETA: position in queue × avg duration
                    pos = pending_jobs.index(job) + 1 if job in pending_jobs else len(pending_jobs)
                    # Account for currently processing jobs finishing first
                    effective_pos = max(1, pos - len(processing_jobs))
                    st.caption(_eta_label(avg_dur, effective_pos))
                elif status == "processing":
                    st.caption(_eta_label(avg_dur, 1))
            with c3:
                # [N3] Rating buttons
                if status == "success":
                    r_col1, r_col2 = st.columns(2)
                    with r_col1:
                        btn_label = "👍" if rating != 1 else "👍✓"
                        if st.button(btn_label, key=f"up_{job_id}", help="Good video"):
                            db.rate_job(job_id, 1)
                            st.rerun()
                    with r_col2:
                        btn_label = "👎" if rating != -1 else "👎✓"
                        if st.button(btn_label, key=f"dn_{job_id}", help="Bad video"):
                            db.rate_job(job_id, -1)
                            st.rerun()
            with c4:
                if job.get("output_path") and os.path.exists(job["output_path"]):
                    if st.button("📂 Open", key=f"open_db_{job_id}"):
                        utils.open_folder(os.path.dirname(job["output_path"]))
                if job.get("error_message"):
                    st.caption(f"⚠️ {job['error_message'][:60]}")

        st.divider()

# ─── In-Memory Tasks (WebUI tasks) ───────────────────────────────────────────
tasks, total = sm.state.get_all_tasks(page=1, page_size=50)
if tasks:
    st.subheader("🎬 WebUI Tasks")
    for task in tasks:
        task_id = task.get("task_id")
        state = task.get("state")
        progress = task.get("progress", 0)
        subject = task.get("video_subject", "Unknown Subject")

        col1, col2, col3 = st.columns([3, 2, 2])
        with col1:
            st.write(f"**{subject}**")
            st.caption(f"ID: `{task_id[:8]}...`")
        with col2:
            if state == 4:  # PROCESSING
                st.progress(progress / 100, text=f"Processing: {int(progress)}%")
                # [N2] ETA for in-progress WebUI tasks
                if avg_dur:
                    remaining_pct = max(0, 100 - progress) / 100
                    eta_s = avg_dur * remaining_pct
                    st.caption(_eta_label(avg_dur, remaining_pct))
            elif state == 0:
                st.info("⏳ Queued")
            elif state == 1:
                st.success("✅ Completed")
            elif state == -1:
                st.error("❌ Failed")
            else:
                st.write(f"State: {state}")
        with col3:
            if st.button("📂 Open Folder", key=f"btn_open_{task_id}"):
                task_dir = utils.task_dir(task_id)
                utils.open_folder(task_dir)

            if state == 1 and "videos" in task:
                video_url = task["videos"][0]
                if os.path.exists(video_url):
                    st.video(video_url)
                else:
                    st.warning("File not found")

# ─── [N3] Prompt Rating Stats ─────────────────────────────────────────────────
rated_jobs = [j for j in all_db_jobs if j.get("rating") is not None]
if rated_jobs:
    with st.expander("📊 A/B Prompt Rating Stats", expanded=False):
        stats = db.get_prompt_rating_stats()
        if stats:
            st.caption("Grouped by prompt variant (subject + language hash)")
            for s in stats:
                total_rated = s.get("total", 0)
                up = s.get("thumbs_up", 0)
                dn = s.get("thumbs_down", 0)
                avg_d = s.get("avg_duration")
                ph = s.get("prompt_hash", "unknown")[:8]
                score_pct = int(up / total_rated * 100) if total_rated else 0
                st.write(f"**`{ph}`** — 👍 {up} / 👎 {dn} ({score_pct}% positive) · avg {_fmt_duration(avg_d)}")
        else:
            st.info("Rate some completed jobs to see stats here.")

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
p_tasks, _ = sm.state.get_all_tasks(1, 100)
has_active = any(t.get("state") in [0, 4] for t in p_tasks)
has_processing_db = any(j.get("status") in ["pending", "processing"] for j in all_db_jobs)
if has_active or has_processing_db:
    time.sleep(3)
    st.rerun()
