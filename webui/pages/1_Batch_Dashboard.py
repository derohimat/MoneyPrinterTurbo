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
from app.utils import utils
from app.config import config
from app.services.task_worker import TaskWorker


st.set_page_config(page_title="Batch Dashboard", page_icon="📊", layout="wide")

st.title("📊 Batch Processing Dashboard")

# Initialize language
i18n_dir = os.path.join(root_dir, "webui", "i18n")
locales = utils.load_locales(i18n_dir)

def tr(key):
    loc = locales.get(st.session_state.get("ui_language", "en-US"), {})
    return loc.get("Translation", {}).get(key, key)


@st.cache_resource
def start_worker():
    worker = TaskWorker.get_instance()
    worker.start()
    return worker

start_worker()

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

    
    # Veo Hook Setting
    # Veo Hook Setting
    use_veo = False
    veo_prompt_template = ""
    veo_negative_prompt = ""
    veo_resolution = "1080p"
    veo_auto_prompt = False
    
    
    
    veo_config = config.veo
    if veo_config.get("enable", False):
        st.divider()
        st.write("🎥 **AI Video Generation (Veo)**")
        
        # Persistent Settings Logic
        use_veo_val = st.checkbox(tr("Use Veo for Hook (First 8s)"), value=veo_config.get("use_veo", False), help="Generate the first scene using Google Veo AI")
        if use_veo_val != veo_config.get("use_veo", False):
            config.veo["use_veo"] = use_veo_val
            config.save_config()
        use_veo = use_veo_val
        
        if use_veo:
             st.info("Veo will generate the first 8 seconds. The rest will use stock footage.")
             
             auto_prompt_val = st.checkbox(tr("Auto-generate Prompts (LLM)"), value=veo_config.get("auto_prompt", False), help="Let AI write the best cinematic prompts for you based on the video subject.")
             if auto_prompt_val != veo_config.get("auto_prompt", False):
                 config.veo["auto_prompt"] = auto_prompt_val
                 config.save_config()
             veo_auto_prompt = auto_prompt_val
             
        # Faceless Mode
        use_faceless = st.checkbox(tr("Faceless Content Mode"), value=False, help=tr("Avoid showing people's faces. Focus on hands, objects, and scenery."))
             
        if not veo_auto_prompt:
             prompt_val = st.text_area(tr("Veo Prompt Template"), value=veo_config.get("prompt_template", "Cinematic shot of {subject}, 8k resolution, highly detailed"), help="Use {subject} as placeholder")
             if prompt_val != veo_config.get("prompt_template", ""):
                 config.veo["prompt_template"] = prompt_val
                 config.save_config()
             veo_prompt_template = prompt_val

             neg_val = st.text_input(tr("Negative Prompt"), value=veo_config.get("negative_prompt", ""), help="What to avoid (if supported)")
             if neg_val != veo_config.get("negative_prompt", ""):
                 config.veo["negative_prompt"] = neg_val
                 config.save_config()
             veo_negative_prompt = neg_val
        else:
             st.info(tr("Prompts will be auto-generated during processing."))
             
        res_options = ["1080p", "Landscape (16:9)", "Portrait (9:16)"]
        default_res = veo_config.get("resolution", "1080p")
        try:
             res_index = res_options.index(default_res)
        except ValueError:
             res_index = 0
             
        res_val = st.selectbox(tr("Resolution / Aspect"), res_options, index=res_index)
        if res_val != default_res:
             config.veo["resolution"] = res_val
             config.save_config()
        veo_resolution = res_val

        if not veo_config.get("project_id"):
             st.warning("Veo is enabled but 'project_id' is missing in config.toml")

    # Get venv python path
    python_exe = sys.executable
    venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        python_exe = venv_python

    if st.button("▶️ Start Batch Processing", type="primary"):
        if selected_file:
            cmd = [python_exe, os.path.join(root_dir, "batch_run_category.py"), selected_file]
            if category_input:
                cmd.extend(["--category", category_input])
            
            if use_faceless:
                cmd.append("--faceless")
            
            if force_rebuild:
                cmd.append("--force")

            if enable_schedule and delay_seconds > 0:
                cmd.extend(["--delay", str(delay_seconds)])
                msg = f"Batch scheduled! Will run in {delay_seconds}s."
            else:
                msg = f"Batch started for {selected_file}!"

            if use_veo:
                cmd.append("--use-veo")
                if veo_auto_prompt:
                    cmd.append("--veo-auto-prompt")
                else:
                    if veo_prompt_template:
                        cmd.extend(["--veo-prompt", veo_prompt_template])
                    if veo_negative_prompt:
                        cmd.extend(["--veo-negative", veo_negative_prompt])
                
                if veo_resolution:
                    cmd.extend(["--veo-resolution", veo_resolution])
            
            subprocess.Popen(cmd, cwd=root_dir)
            st.toast(msg, icon="🚀")
            
            if not enable_schedule:
                time.sleep(1)
                st.rerun()
        else:
            st.error("Please select a tasks file.")

    st.divider()

    # === Resume Failed Section ===
    st.subheader("🔄 Resume / Retry")
    
    if st.button("🔁 Resume Failed Jobs", type="secondary", help="Retry all failed & stuck jobs from selected tasks file"):
        if selected_file:
            cmd = [python_exe, os.path.join(root_dir, "batch_run_category.py"), selected_file, "--resume"]
            if category_input:
                cmd.extend(["--category", category_input])
            subprocess.Popen(cmd, cwd=root_dir)
            st.toast(f"Resuming failed jobs from {selected_file}!", icon="🔁")
            time.sleep(1)
            st.rerun()
        else:
            st.error("Please select a tasks file.")
            
    if st.button("⚠️ Reset Stuck Jobs (Force)", type="primary", help="Force set all 'processing' jobs to 'failed' so they can be resumed. Use only if worker is not running."):
        db.fail_stuck_jobs(timeout_hours=0) # 0 means reset all processing jobs immediately
        st.toast("Reset all stuck jobs to 'failed'. You can now Resume.", icon="⚠️")
        time.sleep(1)
        st.rerun()

    st.divider()
    if st.button("🔄 Refresh Data"):
        st.rerun()

# Main: Job History
st.subheader("Job History")

# Filter controls
col_filter1, col_filter2, col_filter3 = st.columns(3)
with col_filter1:
    status_filter = st.selectbox("Filter by Status", ["All", "success", "failed", "processing", "pending"], index=0)
with col_filter2:
    try:
        all_jobs_for_cats = db.get_all_jobs(limit=500)
        categories = sorted(set(j.get('category', 'Unknown') for j in all_jobs_for_cats if j.get('category')))
        categories.insert(0, "All")
    except Exception:
        categories = ["All"]
    category_filter = st.selectbox("Filter by Category", categories, index=0)
with col_filter3:
    st.write("")  # spacer

try:
    jobs = db.get_all_jobs(limit=500)
    
    if jobs:
        # Apply filters
        if status_filter != "All":
            jobs = [j for j in jobs if j.get('status') == status_filter]
        if category_filter != "All":
            jobs = [j for j in jobs if j.get('category') == category_filter]
        
        if not jobs:
            st.info("No jobs match the current filters.")
        else:
            df = pd.DataFrame(jobs)
            
            # Select and Rename columns for display
            display_cols = {
                "id": "Job ID",
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
            df_display = df[available_cols].rename(columns=display_cols)
            
            # Status Color Logic
            def highlight_status(val):
                color = ''
                if val == 'success':
                    color = 'background-color: #d4edda; color: #155724' # Green
                elif val == 'failed':
                    color = 'background-color: #f8d7da; color: #721c24' # Red
                elif val == 'processing':
                    color = 'background-color: #cce5ff; color: #004085' # Blue
                elif val == 'pending':
                    color = 'background-color: #fff3cd; color: #856404' # Yellow
                return color

            st.dataframe(
                df_display.style.applymap(highlight_status, subset=['Status']),
                use_container_width=True,
                height=400,
                column_config={
                    "Output": st.column_config.LinkColumn("Video Link"),
                    "Created At": st.column_config.DatetimeColumn(format="D MMM, HH:mm:ss"),
                }
            )
            
            # Summary Metrics
            all_jobs_full = db.get_all_jobs(limit=500)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Total Jobs", len(all_jobs_full))
            with c2:
                success_count = sum(1 for j in all_jobs_full if j['status'] == 'success')
                st.metric("✅ Success", success_count)
            with c3:
                failed_count = sum(1 for j in all_jobs_full if j['status'] == 'failed')
                st.metric("❌ Failed", failed_count)
            with c4:
                stuck_count = sum(1 for j in all_jobs_full if j['status'] == 'processing')
                st.metric("⏳ Processing/Stuck", stuck_count)

            # === Retry Individual Jobs Section ===
            retryable_jobs = [j for j in jobs if j.get('status') in ('failed', 'processing')]
            
            if retryable_jobs:
                st.divider()
                st.subheader("🔁 Retry Individual Jobs")
                st.caption("Select failed or stuck jobs to retry individually.")
                
                for job in retryable_jobs:
                    status_icon = "❌" if job['status'] == 'failed' else "⏳"
                    error_info = f" — {job.get('error_message', '')[:80]}" if job.get('error_message') else ""
                    
                    col_info, col_action = st.columns([4, 1])
                    with col_info:
                        st.text(f"{status_icon} {job['topic'][:70]}{error_info}")
                    with col_action:
                        if st.button("🔄 Retry", key=f"retry_{job['id']}", type="secondary"):
                            db.reset_job_for_retry(job['id'])
                            st.toast(f"Job reset: {job['topic'][:40]}...", icon="🔄")
                            time.sleep(0.5)
                            st.rerun()
                
                st.divider()
                # Bulk actions
                col_bulk1, col_bulk2 = st.columns(2)
                with col_bulk1:
                    if st.button("🔄 Reset All Failed/Stuck", type="secondary"):
                        for job in retryable_jobs:
                            db.reset_job_for_retry(job['id'])
                        st.toast(f"Reset {len(retryable_jobs)} jobs!", icon="🔄")
                        time.sleep(0.5)
                        st.rerun()
                with col_bulk2:
                    if st.button("🗑️ Delete All Failed/Stuck", type="secondary"):
                        for job in retryable_jobs:
                            db.delete_job(job['id'])
                        st.toast(f"Deleted {len(retryable_jobs)} jobs!", icon="🗑️")
                        time.sleep(0.5)
                        st.rerun()
    else:
        st.info("No jobs found in database. Start a batch to see history.")
        
except Exception as e:
    st.error(f"Error loading database: {str(e)}")
