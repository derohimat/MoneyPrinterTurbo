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
st.caption("Upload generated videos to TikTok, Instagram, and YouTube.")

# Get venv python paths
venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
venv_upload_python = os.path.join(root_dir, "venv-upload", "Scripts", "python.exe")

# ============================================================
# CAPTION AUTO-GENERATION
# ============================================================
CAPTION_STYLES = {
    "🔥 Viral Hook": {
        "template": "🤯 {topic}!\n\nMost people don't know this... Watch till the end! 👀\n\n{hashtags}",
        "impact": "High engagement — creates curiosity gap, encourages watch-through",
        "hashtags": ["#viral", "#fyp", "#facts", "#mindblowing", "#mustwatch"],
    },
    "📚 Educational": {
        "template": "📚 {topic}\n\nHere's what you need to know ⬇️\n\n{hashtags}",
        "impact": "Steady reach — positions as informative content, attracts save/shares",
        "hashtags": ["#education", "#learning", "#facts", "#knowledge", "#didyouknow"],
    },
    "😱 Shock Value": {
        "template": "You won't believe this about {topic}! 😱\n\nDrop a 🔥 if this blew your mind!\n\n{hashtags}",
        "impact": "Maximum comments — triggers emotional reaction, drives engagement",
        "hashtags": ["#shocking", "#unbelievable", "#omg", "#wow", "#crazyfacts"],
    },
    "🎯 Minimalist": {
        "template": "{topic}\n\n{hashtags}",
        "impact": "Clean look — lets content speak for itself, professional feel",
        "hashtags": ["#shorts", "#reels", "#fyp"],
    },
    "💬 Question Hook": {
        "template": "Did you know about {topic}? 🤔\n\nComment your thoughts below! 👇\n\n{hashtags}",
        "impact": "High comments — questions invite responses, boosts algorithm ranking",
        "hashtags": ["#question", "#debate", "#whatdoyouthink", "#opinion", "#facts"],
    },
    "📖 Storytelling": {
        "template": "The untold story of {topic}... 📖\n\nFollow for more stories like this! ✨\n\n{hashtags}",
        "impact": "Follow growth — narrative format builds anticipation for more content",
        "hashtags": ["#story", "#history", "#untold", "#mystery", "#storytime"],
    },
    "🇮🇩 Bahasa Indo": {
        "template": "🤯 {topic}!\n\nKebanyakan orang nggak tahu ini... Tonton sampai habis! 👀\n\n{hashtags}",
        "impact": "Indonesian audience — localized content for ID market",
        "hashtags": ["#viral", "#fyp", "#fakta", "#indonesia", "#faktaunik"],
    },
}

def generate_caption(video_name: str, style_key: str, custom_hashtags: str = "") -> str:
    """Generate a caption based on video name and selected style."""
    style = CAPTION_STYLES[style_key]
    
    # Clean topic from video filename
    topic = video_name.replace("_", " ").replace("-", " ")
    # Remove common prefixes like "Mystery_01 - "
    if " - " in topic:
        topic = topic.split(" - ", 1)[1]
    
    # Build hashtags
    hashtags = " ".join(style["hashtags"])
    if custom_hashtags:
        hashtags += " " + custom_hashtags
    
    return style["template"].format(topic=topic.strip(), hashtags=hashtags)


# ============================================================
# VIDEO SELECTION
# ============================================================
with st.container(border=True):
    st.subheader("📹 Select Video")
    
    select_mode = st.radio(
        "Selection Mode",
        ["Browse batch_outputs", "Manual path"],
        horizontal=True
    )
    
    selected_video = ""
    video_basename = ""
    
    if select_mode == "Browse batch_outputs":
        batch_dir = os.path.join(root_dir, "batch_outputs")
        
        if os.path.exists(batch_dir):
            categories = sorted([d for d in os.listdir(batch_dir) 
                                if os.path.isdir(os.path.join(batch_dir, d))])
            
            if categories:
                selected_category = st.selectbox("Category", categories, key="up_cat")
                cat_path = os.path.join(batch_dir, selected_category)
                
                # Find all mp4 files
                videos = []
                for rp, dirs, files in os.walk(cat_path):
                    for f in files:
                        if f.endswith(".mp4"):
                            full_path = os.path.join(rp, f)
                            rel_path = os.path.relpath(full_path, cat_path)
                            size_mb = os.path.getsize(full_path) / (1024 * 1024)
                            videos.append((rel_path, full_path, size_mb))
                
                if videos:
                    video_options = [f"{v[0]} ({v[2]:.1f} MB)" for v in videos]
                    selected_idx = st.selectbox(
                        "Select Video",
                        range(len(videos)),
                        format_func=lambda x: video_options[x],
                        key="up_video_select"
                    )
                    selected_video = videos[selected_idx][1]
                    video_basename = os.path.splitext(os.path.basename(selected_video))[0]
                    
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
        elif selected_video:
            video_basename = os.path.splitext(os.path.basename(selected_video))[0]

    if selected_video:
        st.success(f"📹 Selected: `{os.path.basename(selected_video)}`")

# ============================================================
# AUTO-CAPTION GENERATOR
# ============================================================
with st.container(border=True):
    st.subheader("✍️ Auto-Caption Generator")
    
    cap_col1, cap_col2 = st.columns([1, 2])
    
    with cap_col1:
        caption_style = st.selectbox(
            "Caption Style",
            list(CAPTION_STYLES.keys()),
            key="cap_style"
        )
        
        # Show impact
        style_info = CAPTION_STYLES[caption_style]
        st.caption(f"**Impact:** {style_info['impact']}")
    
    with cap_col2:
        custom_hashtags = st.text_input(
            "Additional Hashtags (optional)",
            placeholder="#mystery #bermuda #ocean",
            key="custom_hashtags"
        )
    
    # Generate preview
    topic_name = video_basename if video_basename else "Your Video Topic"
    generated_caption = generate_caption(topic_name, caption_style, custom_hashtags)
    
    st.text_area(
        "Generated Caption (editable)",
        value=generated_caption,
        height=120,
        key="final_caption"
    )
    
    # Show all styles comparison
    with st.expander("📊 Compare All Caption Styles", expanded=False):
        for style_name, style_data in CAPTION_STYLES.items():
            preview = generate_caption(topic_name, style_name)
            st.markdown(f"**{style_name}**")
            st.caption(f"Impact: {style_data['impact']}")
            st.code(preview, language=None)
            st.divider()

# Get final caption from session state
final_caption = st.session_state.get("final_caption", generated_caption)

# ============================================================
# PLATFORM UPLOAD TABS
# ============================================================
st.divider()

tiktok_tab, instagram_tab, youtube_tab = st.tabs(["🎵 TikTok", "📷 Instagram", "🎬 YouTube"])

# ========== TikTok ==========
with tiktok_tab:
    st.subheader("🎵 TikTok Upload")
    
    cookies_file = os.path.join(root_dir, "tiktok_cookies.txt")
    has_cookies = os.path.exists(cookies_file)
    
    if has_cookies:
        st.success(f"✅ TikTok cookies found: `tiktok_cookies.txt`")
    else:
        st.warning("⚠️ No TikTok cookies found. Please login first.")
    
    # Check venv availability
    if not os.path.exists(venv_python):
        st.error(f"Main venv not found at `{venv_python}`. Please set up the environment first.")
    else:
        tiktok_desc = st.text_area(
            "Video Description",
            value=final_caption,
            help="Include hashtags for better reach",
            height=100,
            key="tiktok_desc"
        )
        
        col_tk1, col_tk2 = st.columns(2)
        
        with col_tk1:
            if st.button("🔑 Login to TikTok", use_container_width=True, type="secondary"):
                # Run tiktok_upload.py directly with --login flag
                script = os.path.join(root_dir, "app", "utils", "tiktok_upload.py")
                cmd = [venv_python, script, "--login"]
                
                try:
                    # Use Popen without shell to properly launch browser
                    process = subprocess.Popen(
                        cmd, 
                        cwd=root_dir,
                        creationflags=subprocess.CREATE_NEW_CONSOLE  # Open in new console window
                    )
                    st.toast("TikTok login browser opening!", icon="🔑")
                    st.info(
                        "🔑 **TikTok Login Instructions:**\n\n"
                        "1. A new console window opened with a Chromium browser\n"
                        "2. Login to your TikTok account in that browser\n"
                        "3. After login, close the browser window\n"
                        "4. Cookies will be saved to `tiktok_cookies.txt`\n"
                        "5. Come back here and upload your video!"
                    )
                except Exception as e:
                    st.error(f"Failed to open TikTok login: {str(e)}")
        
        with col_tk2:
            upload_tk = st.button(
                "📤 Upload to TikTok",
                use_container_width=True,
                type="primary",
                disabled=not selected_video or not has_cookies
            )
            
            if upload_tk:
                script = os.path.join(root_dir, "app", "utils", "tiktok_upload.py")
                cmd = [venv_python, script, selected_video, "--desc", tiktok_desc]
                
                try:
                    process = subprocess.Popen(
                        cmd, 
                        cwd=root_dir,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    st.toast("TikTok upload started!", icon="🎵")
                    st.success(f"Uploading `{os.path.basename(selected_video)}` to TikTok...")
                except Exception as e:
                    st.error(f"Upload failed: {str(e)}")

# ========== Instagram ==========
with instagram_tab:
    st.subheader("📷 Instagram Reels Upload")
    
    # Check venv-upload availability
    if not os.path.exists(venv_upload_python):
        st.warning(f"Upload venv not found at `{venv_upload_python}`.")
        st.info("To set up:\n```\npython -m venv venv-upload\nvenv-upload\\Scripts\\pip install instagrapi\n```")
    else:
        st.success("✅ Upload environment ready")
    
    ig_col1, ig_col2 = st.columns(2)
    
    with ig_col1:
        ig_user = st.text_input("Instagram Username", key="ig_user")
    with ig_col2:
        ig_pass = st.text_input("Instagram Password", type="password", key="ig_pass")
    
    ig_caption = st.text_area(
        "Caption",
        value=final_caption,
        height=100,
        key="ig_caption"
    )
    
    upload_ig = st.button(
        "📤 Upload to Instagram Reels",
        type="primary",
        use_container_width=True,
        disabled=not selected_video or not ig_user or not ig_pass
    )
    
    if upload_ig:
        script = os.path.join(root_dir, "app", "utils", "instagram_upload.py")
        python_to_use = venv_upload_python if os.path.exists(venv_upload_python) else venv_python
        cmd = [python_to_use, script, "--video", selected_video, 
               "--user", ig_user, "--passw", ig_pass]
        if ig_caption:
            cmd.extend(["--caption", ig_caption])
        
        try:
            process = subprocess.Popen(
                cmd, 
                cwd=root_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            st.toast("Instagram upload started!", icon="📷")
            st.success(f"Uploading `{os.path.basename(selected_video)}` to Instagram Reels...")
        except Exception as e:
            st.error(f"Upload failed: {str(e)}")

# ========== YouTube ==========
with youtube_tab:
    st.subheader("🎬 YouTube Upload")
    
    # Check setup status
    client_secret_path = os.path.join(root_dir, "client_secret.json")
    token_path = os.path.join(root_dir, "youtube_token.json")
    has_client_secret = os.path.exists(client_secret_path)
    has_token = os.path.exists(token_path)
    
    # Status indicators
    status_col1, status_col2 = st.columns(2)
    with status_col1:
        if has_client_secret:
            st.success("✅ `client_secret.json` found")
        else:
            st.error("❌ `client_secret.json` not found")
    with status_col2:
        if has_token:
            st.success("✅ `youtube_token.json` found (authenticated)")
        else:
            st.warning("⚠️ Not authenticated yet")
    
    # Setup instructions
    if not has_client_secret:
        with st.expander("📋 YouTube Setup Instructions", expanded=True):
            st.markdown("""
### How to Set Up YouTube Upload

**Step 1: Create Google Cloud Project**
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable **YouTube Data API v3**

**Step 2: Create OAuth Credentials**
1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth 2.0 Client ID**
3. Application type: **Desktop app**
4. Download the JSON file
5. Rename it to `client_secret.json`
6. Place it in: `{root_dir}`

**Step 3: Install Dependencies**
```
.\\venv\\Scripts\\pip install google-auth google-auth-oauthlib google-api-python-client
```

**Step 4: First Authentication**
- Click the "🔑 Authenticate YouTube" button below
- A browser will open for Google OAuth
- Grant permission to upload videos
- Token will be saved as `youtube_token.json`
            """.replace("{root_dir}", root_dir))
    
    # YouTube-specific settings
    yt_col1, yt_col2 = st.columns(2)
    
    with yt_col1:
        yt_title = st.text_input(
            "Video Title",
            value=video_basename.replace("_", " ").replace("-", " ")[:100] if video_basename else "",
            max_chars=100,
            help="Max 100 characters",
            key="yt_title"
        )
        
        yt_categories = {
            "General": "22",           # People & Blogs
            "IslamicPlaces": "19",     # Travel & Events
            "Stoik": "27",             # Education
            "Psikologi": "27",         # Education
            "Misteri": "24",           # Entertainment
            "Fakta": "27",             # Education
            "Kesehatan": "26",         # Howto & Style
            "Horor": "24",             # Entertainment
            "Keuangan": "27",          # Education
        }
        yt_category = st.selectbox(
            "YouTube Category",
            list(yt_categories.keys()),
            key="yt_category"
        )
    
    with yt_col2:
        yt_privacy = st.selectbox(
            "Privacy",
            ["private", "unlisted", "public"],
            index=0,
            help="Start with 'private' to review before publishing",
            key="yt_privacy"
        )
        
        yt_tags = st.text_input(
            "Tags (comma-separated)",
            value="shorts, facts, mystery, viral",
            key="yt_tags"
        )
    
    yt_description = st.text_area(
        "Description",
        value=final_caption,
        height=100,
        key="yt_description"
    )
    
    # Action buttons
    yt_btn_col1, yt_btn_col2 = st.columns(2)
    
    with yt_btn_col1:
        if st.button("🔑 Authenticate YouTube", use_container_width=True, type="secondary", 
                     disabled=not has_client_secret):
            script = os.path.join(root_dir, "app", "utils", "youtube_upload.py")
            # Run a dummy upload to trigger OAuth flow
            cmd = [venv_python, "-c", 
                   f"import sys; sys.path.insert(0, '{root_dir}'); "
                   f"from app.utils.youtube_upload import get_authenticated_service; "
                   f"svc = get_authenticated_service(); "
                   f"print('Auth OK!' if svc else 'Auth FAILED')"]
            
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=root_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
                st.toast("YouTube authentication started!", icon="🔑")
                st.info(
                    "🔑 **YouTube Auth Instructions:**\n\n"
                    "1. A browser window will open for Google login\n"
                    "2. Select your YouTube account\n"  
                    "3. Grant permission to upload videos\n"
                    "4. The token will be saved to `youtube_token.json`\n"
                    "5. Come back here to upload!"
                )
            except Exception as e:
                st.error(f"Failed: {str(e)}")
    
    with yt_btn_col2:
        upload_yt = st.button(
            "📤 Upload to YouTube",
            use_container_width=True,
            type="primary",
            disabled=not selected_video or not has_token
        )
        
        if upload_yt:
            script = os.path.join(root_dir, "app", "utils", "youtube_upload.py")
            tags_list = [t.strip() for t in yt_tags.split(",") if t.strip()]
            
            # Build command with all parameters
            cmd = [
                venv_python, "-c",
                f"import sys; sys.path.insert(0, r'{root_dir}'); "
                f"from app.utils.youtube_upload import upload_video; "
                f"result = upload_video("
                f"video_path=r'{selected_video}', "
                f"title=r'{yt_title}', "
                f"description=r'''{yt_description}''', "
                f"tags={tags_list}, "
                f"category='{yt_category}', "
                f"privacy='{yt_privacy}'); "
                f"print('Result:', result)"
            ]
            
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=root_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
                st.toast("YouTube upload started!", icon="🎬")
                st.success(f"Uploading `{os.path.basename(selected_video)}` to YouTube ({yt_privacy})...")
            except Exception as e:
                st.error(f"Upload failed: {str(e)}")

# ============================================================
# BULK UPLOAD (Coming Soon)
# ============================================================
st.divider()
with st.expander("📦 Bulk Upload (Coming Soon)", expanded=False):
    st.info("Bulk upload feature will allow you to upload multiple videos at once with scheduled posting times.")
    st.caption("Stay tuned for this feature in a future update!")
