"""
Multi-Language Video Clone — Generate the same video in multiple languages.
Reuses cached video clips, only regenerates voice + subtitles per language.
"""

import os
import re
import sys
import uuid
import time as time_module

from loguru import logger

from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from app.services import task as tm
from app.config import config

# Language presets: {code: (voice_name, language_label)}
LANGUAGE_PRESETS = {
    "en": ("en-US-ChristopherNeural", "English"),
    "id": ("id-ID-ArdiNeural", "Indonesian"),
    "ar": ("ar-SA-HamedNeural", "Arabic"),
    "es": ("es-ES-AlvaroNeural", "Spanish"),
    "fr": ("fr-FR-HenriNeural", "French"),
    "de": ("de-DE-ConradNeural", "German"),
    "pt": ("pt-BR-AntonioNeural", "Portuguese"),
    "hi": ("hi-IN-MadhurNeural", "Hindi"),
    "ja": ("ja-JP-KeitaNeural", "Japanese"),
    "ko": ("ko-KR-InJoonNeural", "Korean"),
    "zh": ("zh-CN-YunxiNeural", "Chinese"),
    "tr": ("tr-TR-AhmetNeural", "Turkish"),
    "ru": ("ru-RU-DmitryNeural", "Russian"),
    "ms": ("ms-MY-OsmanNeural", "Malay"),
}

root_dir = os.path.dirname(os.path.abspath(__file__))


def clone_video_multi_language(
    video_subject: str,
    languages: list = None,
    output_base_dir: str = "",
    category: str = "General",
):
    """
    Generate the same video content in multiple languages.
    
    Args:
        video_subject: The topic of the video
        languages: List of language codes (e.g. ["en", "id", "ar"])
        output_base_dir: Base directory for outputs
        category: Category name for folder organization
    """
    if not languages:
        languages = ["en", "id", "ar"]
    
    if not output_base_dir:
        output_base_dir = os.path.join(root_dir, "batch_outputs", "multilang")
    
    logger.info(f"Multi-language clone for: {video_subject}")
    logger.info(f"Languages: {[LANGUAGE_PRESETS.get(l, (l,l))[1] for l in languages]}")
    
    results = {}
    
    for lang_code in languages:
        if lang_code not in LANGUAGE_PRESETS:
            logger.warning(f"Unknown language code: {lang_code}, skipping")
            continue
        
        voice_name, lang_label = LANGUAGE_PRESETS[lang_code]
        
        # Create language-specific output directory
        lang_dir = os.path.join(output_base_dir, category, lang_code)
        os.makedirs(lang_dir, exist_ok=True)
        
        safe_name = re.sub(r'[\\/*?:"<>|]', "", video_subject)[:80]
        final_path = os.path.join(lang_dir, f"{safe_name}.mp4")
        
        if os.path.exists(final_path):
            logger.info(f"[{lang_label}] Already exists, skipping: {final_path}")
            results[lang_code] = {"status": "skipped", "path": final_path}
            continue
        
        logger.info(f"[{lang_label}] Generating with voice: {voice_name}")
        
        task_id = str(uuid.uuid4())
        params = VideoParams(
            video_subject=video_subject,
            video_script="",
            video_aspect=VideoAspect.portrait.value,
            voice_name=voice_name,
            video_language=lang_code,
            video_source="pexels",
            video_concat_mode=VideoConcatMode.random,
            subtitle_enabled=True,
            font_size=60,
            stroke_width=1.5,
        )
        
        try:
            result = tm.start(task_id, params)
            if result and "videos" in result:
                output_file = result["videos"][0]
                if os.path.exists(output_file):
                    os.rename(output_file, final_path)
                    logger.success(f"[{lang_label}] Video saved: {final_path}")
                    results[lang_code] = {"status": "success", "path": final_path}
                else:
                    results[lang_code] = {"status": "failed", "path": ""}
            else:
                logger.error(f"[{lang_label}] Failed to generate video")
                results[lang_code] = {"status": "failed", "path": ""}
        except Exception as e:
            logger.error(f"[{lang_label}] Error: {str(e)}")
            results[lang_code] = {"status": "error", "path": ""}
    
    # Print summary
    logger.info("\n=== Multi-Language Clone Summary ===")
    for lang_code, info in results.items():
        lang_label = LANGUAGE_PRESETS.get(lang_code, (lang_code, lang_code))[1]
        status = info["status"]
        icon = "✅" if status == "success" else "⏭️" if status == "skipped" else "❌"
        logger.info(f"  {icon} {lang_label}: {status}")
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Generate a video in multiple languages.')
    parser.add_argument('subject', help='Video subject/topic')
    parser.add_argument('--languages', nargs='+', default=["en", "id", "ar"],
                        help='Language codes (e.g. en id ar es)')
    parser.add_argument('--category', default="General", help='Category name')
    args = parser.parse_args()
    
    clone_video_multi_language(
        video_subject=args.subject,
        languages=args.languages,
        category=args.category,
    )
