import streamlit as st
import subprocess
import sys
import os
import glob

# Add root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

st.set_page_config(page_title="Upload Videos", page_icon="📤", layout="wide")

st.title("📤 Upload Videos")
st.caption("Upload generated videos to TikTok and Instagram.")

# Get venv python paths
venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
venv_upload_python = os.path.join(root_dir, "venv-upload", "Scripts", "python.exe")

# --- Video Selection ---
with st.container(border=True):
    st.subheader("📹 Select Video")
    
    select_mode = st.radio(
        "Selection Mode",
        ["Browse batch_outputs", "Manual path"],
        horizontal=True
    )
    
    selected_video = ""
    
    if select_mode == "Browse batch_outputs":
        batch_dir = os.path.join(root_dir, "batch_outputs")
        
        if os.path.exists(batch_dir):
            # Get all categories
            categories = [d for d in os.listdir(batch_dir) 
                         if os.path.isdir(os.path.join(batch_dir, d))]
            
            if categories:
                selected_category = st.selectbox("Category", sorted(categories))
                cat_path = os.path.join(batch_dir, selected_category)
                
                # Find all mp4 files (including subdirectories)
                videos = []
                for root_path, dirs, files in os.walk(cat_path):
                    for f in files:
                        if f.endswith(".mp4"):
                            full_path = os.path.join(root_path, f)
                            rel_path = os.path.relpath(full_path, cat_path)
                            size_mb = os.path.getsize(full_path) / (1024 * 1024)
                            videos.append((rel_path, full_path, size_mb))
                
                if videos:
                    video_options = [f"{v[0]} ({v[2]:.1f} MB)" for v in videos]
                    selected_idx = st.selectbox(
                        "Select Video",
                        range(len(videos)),
                        format_func=lambda x: video_options[x]
                    )
                    selected_video = videos[selected_idx][1]
                    
                    # Preview
                    if selected_video and os.path.exists(selected_video):
                        with st.expander("🎬 Preview", expanded=False):
                            st.video(selected_video)
                else:
                    st.info("No .mp4 files found in this category.")
            else:
                st.info("No category folders found in batch_outputs.")
        else:
            st.warning("batch_outputs directory not found.")
    
    else:
        selected_video = st.text_input(
            "Video File Path",
            placeholder=r"C:\path\to\video.mp4"
        )
        if selected_video and not os.path.exists(selected_video):
            st.error("File not found!")
            selected_video = ""

    if selected_video:
        st.success(f"📹 Selected: `{os.path.basename(selected_video)}`")

# --- Platform Upload Tabs ---
st.divider()

tiktok_tab, instagram_tab = st.tabs(["🎵 TikTok", "📷 Instagram"])

# ========== TikTok ==========
with tiktok_tab:
    st.subheader("🎵 TikTok Upload")
    
    # Check venv availability
    if not os.path.exists(venv_python):
        st.error(f"Main venv not found at `{venv_python}`. Please set up the environment first.")
    else:
        tiktok_desc = st.text_area(
            "Video Description",
            placeholder="#mystery #facts #viral",
            help="Include hashtags for better reach",
            height=100
        )
        
        col_tk1, col_tk2, col_tk3 = st.columns(3)
        
        with col_tk1:
            if st.button("🔑 Login to TikTok", use_container_width=True, type="secondary"):
                cmd = [venv_python, os.path.join(root_dir, "upload_videos.py"), "tiktok", "--login"]
                try:
                    subprocess.Popen(cmd, cwd=root_dir)
                    st.toast("TikTok login process started!", icon="🔑")
                    st.info("A browser window should open for TikTok login. Complete the login there.")
                except Exception as e:
                    st.error(f"Failed: {str(e)}")
        
        with col_tk2:
            upload_tk = st.button(
                "📤 Upload to TikTok",
                use_container_width=True,
                type="primary",
                disabled=not selected_video
            )
            
            if upload_tk:
                if not selected_video:
                    st.error("Please select a video first!")
                else:
                    cmd = [venv_python, os.path.join(root_dir, "upload_videos.py"), 
                           "tiktok", selected_video]
                    if tiktok_desc:
                        cmd.extend(["--desc", tiktok_desc])
                    
                    try:
                        subprocess.Popen(cmd, cwd=root_dir)
                        st.toast("TikTok upload started!", icon="🎵")
                        st.success(f"Uploading `{os.path.basename(selected_video)}` to TikTok...")
                    except Exception as e:
                        st.error(f"Upload failed: {str(e)}")
        
        with col_tk3:
            st.write("")  # spacer

# ========== Instagram ==========
with instagram_tab:
    st.subheader("📷 Instagram Reels Upload")
    
    # Check venv-upload availability
    if not os.path.exists(venv_upload_python):
        st.warning(f"Upload venv not found at `{venv_upload_python}`.")
        st.info("To set up, run:\n```\npython -m venv venv-upload\nvenv-upload\\Scripts\\pip install instagrapi\n```")
    else:
        st.success("✅ Upload environment ready")
    
    ig_col1, ig_col2 = st.columns(2)
    
    with ig_col1:
        ig_user = st.text_input("Instagram Username", key="ig_user")
    with ig_col2:
        ig_pass = st.text_input("Instagram Password", type="password", key="ig_pass")
    
    ig_caption = st.text_area(
        "Caption",
        placeholder="#reels #mystery #facts #viral\n\nFollow for more!",
        height=100
    )
    
    upload_ig = st.button(
        "📤 Upload to Instagram Reels",
        type="primary",
        use_container_width=True,
        disabled=not selected_video or not ig_user or not ig_pass
    )
    
    if upload_ig:
        if not selected_video:
            st.error("Please select a video first!")
        elif not ig_user or not ig_pass:
            st.error("Please enter Instagram credentials!")
        else:
            cmd = [
                venv_upload_python if os.path.exists(venv_upload_python) else venv_python,
                os.path.join(root_dir, "upload_videos.py"),
                "instagram",
                selected_video,
                "--user", ig_user,
                "--passw", ig_pass,
            ]
            if ig_caption:
                cmd.extend(["--caption", ig_caption])
            
            try:
                subprocess.Popen(cmd, cwd=root_dir)
                st.toast("Instagram upload started!", icon="📷")
                st.success(f"Uploading `{os.path.basename(selected_video)}` to Instagram Reels...")
            except Exception as e:
                st.error(f"Upload failed: {str(e)}")

# --- Bulk Upload Section ---
st.divider()
with st.expander("📦 Bulk Upload (Coming Soon)", expanded=False):
    st.info("Bulk upload feature will allow you to upload multiple videos at once with scheduled posting times.")
    st.caption("Stay tuned for this feature in a future update!")
