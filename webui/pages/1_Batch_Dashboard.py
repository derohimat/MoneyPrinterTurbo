import streamlit as st
import pandas as pd
import time
import subprocess
import sys
import os
from datetime import datetime, timedelta

# Add root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.utils import db

st.set_page_config(page_title="Batch Dashboard", page_icon="📊", layout="wide")

st.title("📊 Batch Processing Dashboard")

# Sidebar: Controls
with st.sidebar:
    st.header("🚀 Start New Batch")
    
    # JSON File Selection
    try:
        json_files = [f for f in os.listdir(root_dir) if f.endswith(".json") and f.startswith("tasks")]
    except Exception:
        json_files = []
        
    selected_file = st.selectbox("Select Tasks File", json_files)
    
    category_input = st.text_input("Category (Optional)", help="Override category name")
    
    st.divider()
    
    # Smart Scheduling
    st.subheader("⏰ Smart Scheduling")
    enable_schedule = st.checkbox("Enable Schedule")
    force_rebuild = st.checkbox("Force Rebuild (Ignore history)")
    delay_seconds = 0

    
    if enable_schedule:
        schedule_time = st.time_input("Start Time", value=datetime.now().time())
        # Calculate delay
        now = datetime.now()
        target_dt = datetime.combine(now.date(), schedule_time)
        if target_dt < now:
            target_dt += timedelta(days=1)
        delay_seconds = int((target_dt - now).total_seconds())
        st.info(f"Scheduled: {target_dt.strftime('%d %b %H:%M')}\n(Runs in {delay_seconds//3600}h {(delay_seconds%3600)//60}m)")

    if st.button("Start Batch Processing", type="primary"):
        if selected_file:
            # Check for venv python
            python_exe = sys.executable
            venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
            if os.path.exists(venv_python):
                python_exe = venv_python

            cmd = [python_exe, os.path.join(root_dir, "batch_run_category.py"), selected_file]
            if category_input:
                cmd.extend(["--category", category_input])
            
            if force_rebuild:
                cmd.append("--force")

            if enable_schedule and delay_seconds > 0:

                cmd.extend(["--delay", str(delay_seconds)])
                msg = f"Batch scheduled! Will run in {delay_seconds}s."
            else:
                msg = f"Batch started for {selected_file}!"
                
            subprocess.Popen(cmd, cwd=root_dir)
            st.toast(msg, icon="🚀")
            
            if not enable_schedule:
                time.sleep(1)
                st.rerun()
        else:
            st.error("Please select a tasks file.")

    st.divider()
    if st.button("🔄 Refresh Data"):
        st.rerun()

# Main: Job History
st.subheader("Job History")

try:
    jobs = db.get_all_jobs(limit=100)
    if jobs:
        df = pd.DataFrame(jobs)
        
        # Select and Rename columns for display
        display_cols = {
            "status": "Status",
            "topic": "Topic", 
            "category": "Category",
            "created_at": "Created At",
            "attempts": "Attempts",
            "output_path": "Output",
            "error_message": "Error"
        }
        
        # Filter available columns
        available_cols = [c for c in display_cols.keys() if c in df.columns]
        df = df[available_cols].rename(columns=display_cols)
        
        # Status Color Logic
        def highlight_status(val):
            color = ''
            if val == 'success':
                color = 'background-color: #d4edda; color: #155724' # Green
            elif val == 'failed':
                color = 'background-color: #f8d7da; color: #721c24' # Red
            elif val == 'processing':
                color = 'background-color: #cce5ff; color: #004085' # Blue
            return color

        st.dataframe(
            df.style.applymap(highlight_status, subset=['Status']),
            use_container_width=True,
            height=600,
            column_config={
                "Output": st.column_config.LinkColumn("Video Link"),
                "Created At": st.column_config.DatetimeColumn(format="D MMM, HH:mm:ss"),
            }
        )
        
        # Summary Metrics
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total Jobs", len(df))
        with c2:
            success_count = len(df[df['Status'] == 'success'])
            st.metric("Success", success_count)
        with c3:
            failed_count = len(df[df['Status'] == 'failed'])
            st.metric("Failed", failed_count)
            
    else:
        st.info("No jobs found in database. Start a batch to see history.")
        
except Exception as e:
    st.error(f"Error loading database: {str(e)}")
