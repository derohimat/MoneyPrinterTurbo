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
from app.utils import utils

# Set page config
st.set_page_config(page_title="Task History", page_icon="📜", layout="wide")

# Ensure worker is running
@st.cache_resource
def start_worker():
    worker = TaskWorker.get_instance()
    worker.start()
    return worker

start_worker()

st.title("📜 Task History & Progress")

if st.button("🔄 Refresh History"):
    st.rerun()
    
tasks, total = sm.state.get_all_tasks(page=1, page_size=50) # Increased default view size
if not tasks:
    st.info("No tasks found.")
else:
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
            if state == 4: # PROCESSING
                st.progress(progress / 100, text=f"Processing: {int(progress)}%")
            elif state == 0: # QUEUED
                st.info("⏳ Queued")
            elif state == 1: # COMPLETE
                st.success("✅ Completed")
            elif state == -1: # FAILED
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

# Auto-refresh if any task is running
p_tasks, _ = sm.state.get_all_tasks(1, 100)
if any(t.get("state") in [0, 4] for t in p_tasks): # Auto refresh for Queued (0) or Processing (4)
    time.sleep(2)
    st.rerun()
