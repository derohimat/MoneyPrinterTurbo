
import os
from moviepy import VideoFileClip
from loguru import logger

PLATFORM_LIMITS = {
    "youtube_shorts":  {"max_duration": 60,  "aspect": "9:16", "suffix": "_shorts"},
    "tiktok":          {"max_duration": 180, "aspect": "9:16", "suffix": "_tiktok"},
    "instagram_reels": {"max_duration": 90,  "aspect": "9:16", "suffix": "_reels"},
}

def export_for_platforms(video_path: str, output_dir: str, platforms: list = None):
    """
    Export trimmed variants for each platform.
    """
    if not platforms:
        platforms = ["youtube_shorts"] # Default
        
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    results = {}
    
    try:
        # Load main video
        # Note: We should use context manager or rigorous close() to avoid file locks
        
        # Optimization: If all requested platforms are > video duration, we can just copy?
        # But we might need to enforce aspect ratio check or something.
        # For now, let's assume input is already the correct aspect ratio (9:16) as per T0-5/T1-3
        # If input is 16:9, and we want 9:16, we need to crop.
        # But `params.video_aspect` controls the generation.
        # If user generated 16:9 and asks for shorts, we might have a problem.
        # Spec says: "auto-export trimmed variants". Implies mainly duration trim.
        # Re-formatting aspect ratio is complex (AI crop).
        # We will assume user generated 9:16 content if they want Shorts/Reels/TikTok.
        # Or we just trim duration and ignore aspect ratio if it doesn't match?
        # Spec AC-1 says "9:16".
        
        with VideoFileClip(video_path) as clip:
            duration = clip.duration
            
            for platform in platforms:
                spec = PLATFORM_LIMITS.get(platform)
                if not spec:
                    logger.warning(f"unknown platform: {platform}")
                    continue
                
                # Check Duration
                max_dur = spec["max_duration"]
                
                target_filename = os.path.basename(video_path).rsplit(".", 1)[0] + spec["suffix"] + ".mp4"
                out_path = os.path.join(output_dir, target_filename)
                
                if duration <= max_dur:
                    # Just copy or write?
                    # Write to ensure encoding settings if needed?
                    # Clip.write_videofile might re-encode.
                    # Copy is faster if codec is compatible.
                    # But verifying specific codec/bitrate might be needed.
                    # Let's write_videofile for consistency and "trimmed" logic even if full length
                    # (Clip.subclipped(0, duration) is same)
                    
                    # Actually, if duration is short enough, we just use full video.
                    logger.info(f"exporting for {platform} (full duration: {duration:.2f}s) -> {out_path}")
                    clip.write_videofile(out_path, codec="libx264", audio_codec="aac", logger=None)
                else:
                    # Trim
                    # Spec AC-5: "Trim from start (keep beginning, cut end) to preserve hook"
                    # Ideally we might want to speed up or pick best part, but "cut end" is simplest/safest for hook.
                    logger.info(f"exporting for {platform} (trimmed to {max_dur}s) -> {out_path}")
                    trimmed = clip.subclipped(0, max_dur)
                    trimmed.write_videofile(out_path, codec="libx264", audio_codec="aac", logger=None)
                    
                results[platform] = out_path

    except Exception as e:
        logger.error(f"failed to export for platforms: {e}")
        
    return results
