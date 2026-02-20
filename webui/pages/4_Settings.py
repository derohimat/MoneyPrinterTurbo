import streamlit as st
import sys
import os
import toml

# Add root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.config import config

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")

st.title("⚙️ Global Settings")
st.caption("Configure default settings for video generation, subtitles, BGM, and more.")

config_path = os.path.join(root_dir, "config.toml")

# Load current config from file
def load_raw_config():
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return toml.load(f)
    except Exception:
        return {}

def save_raw_config(cfg):
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            toml.dump(cfg, f)
        return True
    except Exception as e:
        st.error(f"Failed to save config: {str(e)}")
        return False

raw_config = load_raw_config()

# ============================================================
# TABS
# ============================================================
tab_video, tab_subtitle, tab_bgm, tab_safety, tab_system = st.tabs([
    "🎬 Video Defaults", "📝 Subtitle & Watermark", "🎵 BGM Settings", 
    "🔒 Safety Filters", "⚙️ System"
])

# ============================================================
# TAB 1: Video Defaults
# ============================================================
with tab_video:
    st.subheader("🎬 Video Default Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        with st.container(border=True):
            st.write("**Video Source**")
            video_source = st.selectbox(
                "Default Video Source",
                ["pexels", "pixabay"],
                index=0 if raw_config.get("app", {}).get("video_source", "pexels") == "pexels" else 1,
                key="cfg_video_source"
            )
            
            st.write("**Video Aspect**")
            aspect_options = ["portrait (9:16)", "landscape (16:9)"]
            selected_aspect = st.radio("Default Aspect Ratio", aspect_options, index=0, horizontal=True)
            
            st.write("**Clip Duration**")
            clip_duration = st.slider("Default Clip Duration (seconds)", 2, 10, 3, key="cfg_clip_duration")
    
    with col2:
        with st.container(border=True):
            st.write("**Voice & Language**")
            
            default_voice = raw_config.get("ui", {}).get("voice_name", "en-US-ChristopherNeural")
            voice_name = st.text_input("Default Voice Name", value=default_voice, key="cfg_voice_name")
            
            video_lang_options = ["en", "id", "ar", "es", "fr", "de", "pt", "hi", "ja", "ko", "zh", "tr", "ru", "ms"]
            default_lang = "en"
            video_language = st.selectbox("Default Video Language", video_lang_options, 
                                         index=video_lang_options.index(default_lang), key="cfg_video_lang")
            
            st.write("**Concurrent Tasks**")
            max_tasks = st.number_input(
                "Max Concurrent Tasks",
                min_value=1, max_value=10,
                value=raw_config.get("app", {}).get("max_concurrent_tasks", 1),
                key="cfg_max_tasks"
            )

# ============================================================
# TAB 2: Subtitle & Watermark
# ============================================================
with tab_subtitle:
    st.subheader("📝 Subtitle & Watermark Settings")
    
    col_sub1, col_sub2 = st.columns(2)
    
    with col_sub1:
        with st.container(border=True):
            st.write("**Subtitle Defaults**")
            
            ui_config = raw_config.get("ui", {})
            
            subtitle_provider = st.selectbox(
                "Subtitle Provider",
                ["edge", "whisper", ""],
                index=["edge", "whisper", ""].index(raw_config.get("app", {}).get("subtitle_provider", "edge")),
                help="'edge' for Edge TTS timing, 'whisper' for AI speech recognition, empty to disable",
                key="cfg_subtitle_provider"
            )
            
            # Font selection
            font_dir = os.path.join(root_dir, "resource", "fonts")
            fonts = []
            if os.path.exists(font_dir):
                fonts = [f for f in os.listdir(font_dir) if f.endswith((".ttf", ".ttc", ".otf"))]
            
            current_font = ui_config.get("font_name", "MicrosoftYaHeiBold.ttc")
            font_idx = fonts.index(current_font) if current_font in fonts else 0
            selected_font = st.selectbox("Font", fonts, index=font_idx, key="cfg_font") if fonts else st.text_input("Font Name", value=current_font)
            
            font_size = st.slider("Font Size", 20, 120, ui_config.get("font_size", 60), key="cfg_font_size")
            
            color_cols = st.columns(2)
            with color_cols[0]:
                text_color = st.color_picker("Text Color", ui_config.get("text_fore_color", "#FFFFFF"), key="cfg_text_color")
            with color_cols[1]:
                stroke_color = st.color_picker("Stroke Color", "#000000", key="cfg_stroke_color")
            
            stroke_width = st.slider("Stroke Width", 0.0, 10.0, 1.5, key="cfg_stroke_width")
            
            position_options = ["top", "center", "bottom", "custom"]
            subtitle_position = st.selectbox("Default Position", position_options, index=2, key="cfg_sub_pos")
    
    with col_sub2:
        with st.container(border=True):
            st.write("**Watermark Settings**")
            st.info("Watermark configuration for branding your videos.")
            
            enable_watermark = st.checkbox("Enable Watermark", value=False, key="cfg_watermark_enable")
            
            if enable_watermark:
                watermark_text = st.text_input("Watermark Text", placeholder="@YourChannel", key="cfg_watermark_text")
                
                wm_cols = st.columns(2)
                with wm_cols[0]:
                    wm_position = st.selectbox("Position", ["top-left", "top-right", "bottom-left", "bottom-right"], 
                                               index=3, key="cfg_wm_pos")
                with wm_cols[1]:
                    wm_opacity = st.slider("Opacity", 0.1, 1.0, 0.7, key="cfg_wm_opacity")
                
                wm_font_size = st.slider("Watermark Font Size", 12, 60, 24, key="cfg_wm_font_size")
            else:
                st.caption("Enable watermark to configure settings.")
        
        with st.container(border=True):
            st.write("**Hook Styles**")
            st.info("Customize the opening hook text style for videos.")
            
            hook_styles = {
                "Bold Question": "❓ Did you know...?",
                "Shocking Statement": "🤯 This will blow your mind!",
                "Number List": "📊 Top 5 reasons why...",
                "Story Opener": "📖 Let me tell you a story...",
                "Challenge": "💪 Can you guess what happened?",
            }
            
            selected_hook = st.selectbox("Default Hook Style", list(hook_styles.keys()), key="cfg_hook_style")
            st.caption(f"Preview: *{hook_styles[selected_hook]}*")

        with st.container(border=True):
            st.write("**Subtitle Preview**")
            preview_text = "The Mystery of Bermuda Triangle"
            st.markdown(
                f"""<div style="
                    background: #1a1a2e; 
                    padding: 40px 20px; 
                    border-radius: 8px; 
                    text-align: center;
                    font-family: sans-serif;
                ">
                    <span style="
                        color: {text_color}; 
                        font-size: {min(font_size // 2, 36)}px; 
                        font-weight: bold;
                        text-shadow: {stroke_width}px {stroke_width}px 0 {stroke_color};
                    ">{preview_text}</span>
                </div>""",
                unsafe_allow_html=True
            )

# ============================================================
# TAB 3: BGM Settings
# ============================================================
with tab_bgm:
    st.subheader("🎵 Background Music Settings")
    
    # Show current BGM mapping
    with st.container(border=True):
        st.write("**Category → BGM Mapping**")
        st.caption("Each category has assigned BGM tracks from `resource/songs/`")
        
        # Import BGM matcher config
        try:
            from app.utils.bgm_matcher import CATEGORY_BGM_MAP, get_bgm_for_category
            
            for cat, tracks in CATEGORY_BGM_MAP.items():
                with st.expander(f"🎵 {cat} ({len(tracks)} tracks)"):
                    for track in tracks:
                        song_path = os.path.join(root_dir, "resource", "songs", track)
                        cols = st.columns([3, 1])
                        with cols[0]:
                            st.text(f"🎶 {track}")
                        with cols[1]:
                            if os.path.exists(song_path):
                                st.caption("✅ Found")
                            else:
                                st.caption("❌ Missing")
        except ImportError:
            st.warning("Could not load BGM matcher module.")
    
    # Song directory browser
    with st.container(border=True):
        st.write("**Available BGM Files**")
        song_dir = os.path.join(root_dir, "resource", "songs")
        
        if os.path.exists(song_dir):
            songs = sorted([f for f in os.listdir(song_dir) if f.endswith((".mp3", ".wav", ".ogg"))])
            st.info(f"Total: {len(songs)} BGM files in `resource/songs/`")
            
            if songs:
                selected_song = st.selectbox("Preview Song", songs)
                song_path = os.path.join(song_dir, selected_song)
                if os.path.exists(song_path):
                    st.audio(song_path)
        else:
            st.warning("Song directory not found.")

# ============================================================
# TAB 4: Safety Filters
# ============================================================
with tab_safety:
    st.subheader("🔒 Safety Filters")
    st.caption("Control which terms are excluded from video stock searches to keep content safe.")
    
    try:
        from app.utils.safety_filters import GLOBAL_NEGATIVE_TERMS, CATEGORY_NEGATIVE_TERMS, SCRIPT_UNSAFE_WORDS
        
        with st.container(border=True):
            st.write(f"**Global Negative Terms** ({len(GLOBAL_NEGATIVE_TERMS)} terms)")
            st.caption("These terms are always excluded from video searches across ALL categories.")
            
            # Display in compact format
            terms_text = ", ".join(sorted(GLOBAL_NEGATIVE_TERMS))
            st.text_area("Global Terms (read-only)", value=terms_text, height=120, disabled=True, key="global_terms_display")
        
        with st.container(border=True):
            st.write("**Per-Category Negative Terms**")
            
            for cat, terms in CATEGORY_NEGATIVE_TERMS.items():
                with st.expander(f"🏷️ {cat} ({len(terms)} terms)"):
                    st.text(", ".join(terms))
        
        with st.container(border=True):
            st.write(f"**Script Safety Words** ({len(SCRIPT_UNSAFE_WORDS)} terms)")
            st.caption("Words checked in generated scripts for post-generation safety validation.")
            st.text(", ".join(SCRIPT_UNSAFE_WORDS))
    
    except ImportError:
        st.warning("Could not load safety_filters module.")

# ============================================================
# TAB 5: System
# ============================================================
with tab_system:
    st.subheader("⚙️ System Configuration")
    
    col_sys1, col_sys2 = st.columns(2)
    
    with col_sys1:
        with st.container(border=True):
            st.write("**LLM Provider**")
            
            providers = ["openai", "deepseek", "gemini", "moonshot", "qwen", "ollama", 
                         "g4f", "azure", "oneapi", "modelscope", "pollinations", "sumopod", "ernie"]
            current_provider = raw_config.get("app", {}).get("llm_provider", "openai")
            provider_idx = providers.index(current_provider) if current_provider in providers else 0
            
            llm_provider = st.selectbox("LLM Provider", providers, index=provider_idx, key="cfg_llm_provider")
            
            # Show current API key (masked)
            api_key = raw_config.get("app", {}).get(f"{llm_provider}_api_key", "")
            new_api_key = st.text_input(f"{llm_provider} API Key", value=api_key, type="password", key="cfg_llm_key")
            
            base_url = raw_config.get("app", {}).get(f"{llm_provider}_base_url", "")
            new_base_url = st.text_input(f"{llm_provider} Base URL", value=base_url, key="cfg_llm_url")
            
            model_name = raw_config.get("app", {}).get(f"{llm_provider}_model_name", "")
            new_model_name = st.text_input(f"{llm_provider} Model Name", value=model_name, key="cfg_llm_model")
    
    with col_sys2:
        with st.container(border=True):
            st.write("**Whisper Settings**")
            whisper_config = raw_config.get("whisper", {})
            
            model_sizes = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
            current_size = whisper_config.get("model_size", "large-v3")
            size_idx = model_sizes.index(current_size) if current_size in model_sizes else 5
            whisper_model = st.selectbox("Model Size", model_sizes, index=size_idx, key="cfg_whisper_model")
            
            devices = ["CPU", "cuda"]
            current_device = whisper_config.get("device", "CPU")
            device_idx = devices.index(current_device) if current_device in devices else 0
            whisper_device = st.selectbox("Device", devices, index=device_idx, key="cfg_whisper_device")
            
            compute_types = ["int8", "float16", "int8_float16"]
            current_compute = whisper_config.get("compute_type", "int8")
            compute_idx = compute_types.index(current_compute) if current_compute in compute_types else 0
            whisper_compute = st.selectbox("Compute Type", compute_types, index=compute_idx, key="cfg_whisper_compute")
        
        with st.container(border=True):
            st.write("**Storage**")
            material_dir = raw_config.get("app", {}).get("material_directory", "")
            new_material_dir = st.text_input("Material Directory", value=material_dir, 
                                             help="Leave empty for default (./storage/cache_videos)",
                                             key="cfg_material_dir")
            
        with st.container(border=True):
            st.write("**UI & App Settings**")
            hide_config_setting = st.checkbox("Hide Basic Settings on Main Page", 
                                              value=raw_config.get("app", {}).get("hide_config", False), 
                                              key="cfg_hide_config")
    
    # Redis settings
    with st.expander("🔴 Redis Configuration", expanded=False):
        app_config = raw_config.get("app", {})
        redis_enabled = st.checkbox("Enable Redis", value=app_config.get("enable_redis", False), key="cfg_redis_enable")
        
        if redis_enabled:
            rcol1, rcol2, rcol3 = st.columns(3)
            with rcol1:
                redis_host = st.text_input("Redis Host", value=app_config.get("redis_host", "localhost"), key="cfg_redis_host")
            with rcol2:
                redis_port = st.number_input("Redis Port", value=app_config.get("redis_port", 6379), key="cfg_redis_port")
            with rcol3:
                redis_db = st.number_input("Redis DB", value=app_config.get("redis_db", 0), key="cfg_redis_db")
            
            redis_password = st.text_input("Redis Password", value=app_config.get("redis_password", ""), 
                                           type="password", key="cfg_redis_pass")

# ============================================================
# SAVE BUTTON
# ============================================================
st.divider()

save_col1, save_col2, save_col3 = st.columns([2, 1, 1])

with save_col1:
    if st.button("💾 Save All Settings", type="primary", use_container_width=True):
        try:
            # Build updated config
            cfg = load_raw_config()
            
            # Video defaults
            cfg.setdefault("app", {})
            cfg["app"]["video_source"] = video_source
            cfg["app"]["max_concurrent_tasks"] = max_tasks
            cfg["app"]["subtitle_provider"] = subtitle_provider
            cfg["app"]["llm_provider"] = llm_provider
            cfg["app"]["hide_config"] = hide_config_setting
            
            # LLM settings
            if new_api_key:
                cfg["app"][f"{llm_provider}_api_key"] = new_api_key
            if new_base_url:
                cfg["app"][f"{llm_provider}_base_url"] = new_base_url
            if new_model_name:
                cfg["app"][f"{llm_provider}_model_name"] = new_model_name
            
            if new_material_dir:
                cfg["app"]["material_directory"] = new_material_dir
            
            # Redis
            cfg["app"]["enable_redis"] = redis_enabled if 'redis_enabled' in dir() else False
            
            # UI settings
            cfg.setdefault("ui", {})
            cfg["ui"]["font_name"] = selected_font if isinstance(selected_font, str) else current_font
            cfg["ui"]["font_size"] = font_size
            cfg["ui"]["text_fore_color"] = text_color
            cfg["ui"]["voice_name"] = voice_name
            
            # Whisper settings
            cfg.setdefault("whisper", {})
            cfg["whisper"]["model_size"] = whisper_model
            cfg["whisper"]["device"] = whisper_device
            cfg["whisper"]["compute_type"] = whisper_compute
            
            if save_raw_config(cfg):
                st.toast("Settings saved successfully!", icon="💾")
                st.success("✅ Configuration saved to `config.toml`")
        except Exception as e:
            st.error(f"Error saving settings: {str(e)}")

with save_col2:
    if st.button("🔄 Reload", use_container_width=True):
        st.rerun()

with save_col3:
    if st.button("📋 View Raw Config", use_container_width=True):
        st.session_state["show_raw"] = not st.session_state.get("show_raw", False)

if st.session_state.get("show_raw", False):
    with st.expander("📋 Raw config.toml", expanded=True):
        try:
            with open(config_path, "r") as f:
                st.code(f.read(), language="toml")
        except Exception:
            st.error("Could not read config.toml")
