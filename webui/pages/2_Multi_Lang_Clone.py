import streamlit as st
import subprocess
import sys
import os
import json

# Add root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

st.set_page_config(page_title="Multi-Language Clone", page_icon="🌐", layout="wide")

st.title("🌐 Multi-Language Video Clone")
st.caption("Generate the same video content in multiple languages simultaneously.")

# Language presets (mirrors multi_lang_clone.py)
LANGUAGE_PRESETS = {
    "en": ("en-US-ChristopherNeural", "🇺🇸 English"),
    "id": ("id-ID-ArdiNeural", "🇮🇩 Indonesian"),
    "ar": ("ar-SA-HamedNeural", "🇸🇦 Arabic"),
    "es": ("es-ES-AlvaroNeural", "🇪🇸 Spanish"),
    "fr": ("fr-FR-HenriNeural", "🇫🇷 French"),
    "de": ("de-DE-ConradNeural", "🇩🇪 German"),
    "pt": ("pt-BR-AntonioNeural", "🇧🇷 Portuguese"),
    "hi": ("hi-IN-MadhurNeural", "🇮🇳 Hindi"),
    "ja": ("ja-JP-KeitaNeural", "🇯🇵 Japanese"),
    "ko": ("ko-KR-InJoonNeural", "🇰🇷 Korean"),
    "zh": ("zh-CN-YunxiNeural", "🇨🇳 Chinese"),
    "tr": ("tr-TR-AhmetNeural", "🇹🇷 Turkish"),
    "ru": ("ru-RU-DmitryNeural", "🇷🇺 Russian"),
    "ms": ("ms-MY-OsmanNeural", "🇲🇾 Malay"),
}

# --- Video Source Selection (like Upload page) ---
with st.container(border=True):
    st.subheader("📹 Select Source Video / Topic")
    
    select_mode = st.radio(
        "Source Mode",
        ["Browse batch_outputs", "Browse task files (JSON)", "Manual input"],
        horizontal=True,
        key="mlc_source_mode"
    )
    
    video_subject = ""
    category = "General"
    
    if select_mode == "Browse batch_outputs":
        batch_dir = os.path.join(root_dir, "batch_outputs")
        
        if os.path.exists(batch_dir):
            categories = sorted([d for d in os.listdir(batch_dir) 
                                if os.path.isdir(os.path.join(batch_dir, d))])
            
            if categories:
                category = st.selectbox("Category", categories, key="mlc_cat")
                cat_path = os.path.join(batch_dir, category)
                
                # Find all mp4 files
                videos = []
                for rp, dirs, files in os.walk(cat_path):
                    for f in files:
                        if f.endswith(".mp4"):
                            full_path = os.path.join(rp, f)
                            rel_path = os.path.relpath(full_path, cat_path)
                            name = os.path.splitext(f)[0]
                            size_mb = os.path.getsize(full_path) / (1024 * 1024)
                            videos.append((name, rel_path, full_path, size_mb))
                
                if videos:
                    video_options = [f"{v[0]} ({v[3]:.1f} MB)" for v in videos]
                    selected_idx = st.selectbox(
                        "Select Video to Clone",
                        range(len(videos)),
                        format_func=lambda x: video_options[x],
                        key="mlc_video_select"
                    )
                    video_subject = videos[selected_idx][0]
                    
                    # Preview
                    if videos[selected_idx][2] and os.path.exists(videos[selected_idx][2]):
                        with st.expander("🎬 Preview", expanded=False):
                            st.video(videos[selected_idx][2])
                    
                    st.success(f"📝 Subject: **{video_subject}**")
                else:
                    st.info("No .mp4 files found in this category.")
            else:
                st.info("No category folders found in batch_outputs.")
        else:
            st.warning("batch_outputs directory not found.")
    
    elif select_mode == "Browse task files (JSON)":
        # Find all JSON task files
        json_files = [f for f in os.listdir(root_dir) if f.startswith("tasks_") and f.endswith(".json")]
        
        if json_files:
            selected_json = st.selectbox("Task File", sorted(json_files), key="mlc_json_file")
            
            try:
                with open(os.path.join(root_dir, selected_json), "r", encoding="utf-8") as f:
                    topics = json.load(f)
                
                if topics:
                    topic_options = [t.get("topic", t.get("subject", str(t))) if isinstance(t, dict) else str(t) 
                                   for t in topics]
                    selected_topic_idx = st.selectbox(
                        "Select Topic",
                        range(len(topic_options)),
                        format_func=lambda x: topic_options[x],
                        key="mlc_topic_select"
                    )
                    video_subject = topic_options[selected_topic_idx]
                    
                    # Extract category from filename (tasks_misteri.json -> Misteri)
                    cat_name = selected_json.replace("tasks_", "").replace(".json", "").capitalize()
                    category = cat_name
                    
                    st.success(f"📝 Subject: **{video_subject}** | Category: **{category}**")
                else:
                    st.info("No topics found in selected file.")
            except Exception as e:
                st.error(f"Error reading JSON: {str(e)}")
        else:
            st.info("No tasks_*.json files found in project root.")
    
    else:  # Manual input
        col_m1, col_m2 = st.columns([2, 1])
        with col_m1:
            video_subject = st.text_input(
                "Video Subject / Topic",
                placeholder="e.g. Mystery - Bermuda Triangle Mystery Solved Or Not",
                help="The topic that will be used to generate video content in each language"
            )
        with col_m2:
            category = st.text_input(
                "Category",
                value="General",
                help="Category folder name for organizing outputs"
            )

# --- Language Selection ---
with st.container(border=True):
    st.subheader("🗣️ Select Languages")
    
    # Quick selection buttons
    quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
    
    with quick_col1:
        if st.button("Select All", use_container_width=True):
            st.session_state["selected_langs"] = list(LANGUAGE_PRESETS.keys())
            st.rerun()
    with quick_col2:
        if st.button("Deselect All", use_container_width=True):
            st.session_state["selected_langs"] = []
            st.rerun()
    with quick_col3:
        if st.button("Top 3 (EN, ID, AR)", use_container_width=True):
            st.session_state["selected_langs"] = ["en", "id", "ar"]
            st.rerun()
    with quick_col4:
        if st.button("Asian Pack", use_container_width=True):
            st.session_state["selected_langs"] = ["id", "ja", "ko", "zh", "hi", "ms"]
            st.rerun()
    
    # Initialize session state
    if "selected_langs" not in st.session_state:
        st.session_state["selected_langs"] = ["en", "id", "ar"]
    
    # Language checkboxes in grid
    lang_cols = st.columns(4)
    selected_languages = []
    
    for i, (code, (voice, label)) in enumerate(LANGUAGE_PRESETS.items()):
        col = lang_cols[i % 4]
        with col:
            checked = code in st.session_state.get("selected_langs", [])
            if st.checkbox(f"{label}", value=checked, key=f"lang_{code}"):
                selected_languages.append(code)
    
    st.info(f"**{len(selected_languages)} languages selected** — Each video takes ~2-5 minutes to generate.")

# --- Start Generation ---
st.divider()

# Get venv python
python_exe = sys.executable
venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
if os.path.exists(venv_python):
    python_exe = venv_python

start_col1, start_col2 = st.columns([3, 1])

with start_col1:
    start_button = st.button(
        "🚀 Start Multi-Language Generation",
        type="primary",
        use_container_width=True,
        disabled=not video_subject or not selected_languages
    )

with start_col2:
    est_time = len(selected_languages) * 3
    st.metric("Est. Time", f"~{est_time} min")

if start_button:
    if not video_subject:
        st.error("Please enter a video subject!")
        st.stop()
    
    if not selected_languages:
        st.error("Please select at least one language!")
        st.stop()
    
    cmd = [
        python_exe,
        os.path.join(root_dir, "multi_lang_clone.py"),
        video_subject,
        "--languages", *selected_languages,
        "--category", category,
    ]
    
    st.toast(f"Starting multi-language generation for {len(selected_languages)} languages!", icon="🚀")
    
    try:
        subprocess.Popen(cmd, cwd=root_dir)
        st.success(f"✅ Generation started! Processing {len(selected_languages)} languages in background.")
        st.info(f"**Command:** `{' '.join(cmd[:4])} ...`")
    except Exception as e:
        st.error(f"Failed to start: {str(e)}")

# --- Output Browser ---
st.divider()
st.subheader("📂 Generated Outputs")

multilang_dir = os.path.join(root_dir, "batch_outputs", "multilang")
if os.path.exists(multilang_dir):
    categories_out = [d for d in os.listdir(multilang_dir) if os.path.isdir(os.path.join(multilang_dir, d))]
    
    if categories_out:
        selected_cat = st.selectbox("Select Category", categories_out, key="mlc_out_cat")
        cat_dir = os.path.join(multilang_dir, selected_cat)
        
        if os.path.exists(cat_dir):
            lang_dirs = [d for d in os.listdir(cat_dir) if os.path.isdir(os.path.join(cat_dir, d))]
            
            if lang_dirs:
                out_lang_cols = st.columns(min(len(lang_dirs), 4))
                for i, lang_code in enumerate(sorted(lang_dirs)):
                    col = out_lang_cols[i % len(out_lang_cols)]
                    lang_path = os.path.join(cat_dir, lang_code)
                    videos = [f for f in os.listdir(lang_path) if f.endswith(".mp4")]
                    
                    with col:
                        label = LANGUAGE_PRESETS.get(lang_code, ("", lang_code))[1]
                        st.write(f"**{label}**")
                        st.metric("Videos", len(videos))
                        for v in videos[:3]:
                            st.caption(f"📹 {v[:40]}...")
            else:
                st.info("No language folders found in this category yet.")
    else:
        st.info("No multi-language outputs found yet.")
else:
    st.info("No multi-language outputs directory found. Start a generation to create one.")
