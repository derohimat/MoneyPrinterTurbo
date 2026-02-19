
import re
import os
from loguru import logger
from moviepy import VideoFileClip
from app.utils import utils

# Keywords that might indicate an engaging moment
EMOTIONAL_KEYWORDS = [
    "incredible", "amazing", "shocking", "unbelievable", "crazy",
    "insane", "hacked", "secret", "exposed", "truth", "finally", 
    "omg", "wow", "boom", "mind-blowing",
    # Indonesian
    "luar biasa", "gila", "dahsyat", "menakjubkan", "rahasia",
    "terungkap", "akhirnya", "waduh", "mantap"
]

def score_segment(text: str) -> int:
    """
    Score a text segment for potential virality.
    """
    score = 0
    text_lower = text.lower()
    
    # Question marks (Hooks/Engagement)
    score += text.count("?") * 2
    
    # Exclamations
    score += text.count("!") * 2
    
    # Emotional keywords
    for keyword in EMOTIONAL_KEYWORDS:
        if keyword in text_lower:
            score += 3
            
    # Numbers (often stats or facts)
    # Simple regex for numbers > 100 or specific patterns?
    # Actually any number might be interesting.
    if re.search(r'\d+', text):
        score += 1
        
    return score

def extract_highlights(video_path: str, subtitle_path: str, output_dir: str, max_clips: int = 3, clip_duration: float = 20.0):
    """
    Extract highlight clips from video based on subtitle analysis.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    try:
        from app.services import subtitle
        if not os.path.exists(subtitle_path):
            logger.warning(f"subtitle file not found: {subtitle_path}, skipping highlights")
            return []
            
        subs = subtitle.file_to_subtitles(subtitle_path)
        if not subs:
            return []
            
        # 1. Score segments
        # We need to look at windows of text, not just single lines.
        # A highlight is 20s. We should slide a window?
        # Or score each subtitle line, then find dense areas.
        
        # Let's verify timeline.
        # Map time to score.
        timeline_scores = []
        
        for sub in subs:
            # sub: (index, time_str, text)
            start_str = sub[1].split(" --> ")[0]
            start_time = utils.srt_time_to_seconds(start_str)
            text = sub[2]
            score = score_segment(text)
            if score > 0:
                timeline_scores.append({"time": start_time, "score": score, "text": text})
                
        logger.info(f"found {len(timeline_scores)} scored segments: {timeline_scores}")
                
        if not timeline_scores:
            logger.info("no highlight moments found based on keywords")
            return []
            
        # 2. Find peaks
        # We want non-overlapping windows of `clip_duration`.
        # Simple algorithm: Sort by score. Pick highest. Mark window as used. Repeat.
        
        timeline_scores.sort(key=lambda x: x["score"], reverse=True)
        
        selected_clips = []
        full_duration = 0
        try:
             clip_for_dur = VideoFileClip(video_path)
             full_duration = clip_for_dur.duration
             clip_for_dur.close()
        except:
             full_duration = 300 # Fallback 5 mins if read fails (unlikely if path valid)

        used_ranges = []
        
        for item in timeline_scores:
            if len(selected_clips) >= max_clips:
                break
                
            center_time = item["time"]
            # Center the clip around the moment
            half_dur = clip_duration / 2
            start = max(0, center_time - half_dur)
            end = min(full_duration, start + clip_duration)
            
            # Re-adjust start if end was clamped
            if end == full_duration:
                start = max(0, end - clip_duration)
                
            # Check overlap
            is_overlapping = False
            for r in used_ranges:
                # Check intersection
                if max(start, r[0]) < min(end, r[1]): # Overlap condition
                    is_overlapping = True
                    break
            
            if not is_overlapping:
                selected_clips.append((start, end, item["score"]))
                used_ranges.append((start, end))

        logger.info(f"selected {len(selected_clips)} clips: {selected_clips}")
                
        # 3. Extract Clips
        saved_paths = []
        # Re-open clip to avoid long open handle
        with VideoFileClip(video_path) as clip:
            for i, (start, end, score) in enumerate(selected_clips):
                out_name = f"highlight_{i+1}_score{score}.mp4"
                out_path = os.path.join(output_dir, out_name)
                
                subclip = clip.subclipped(start, end)
                subclip.write_videofile(out_path, codec="libx264", audio_codec="aac", logger=None)
                saved_paths.append(out_path)
                logger.info(f"exported highlight {i+1}: {out_path} (score: {score})")
                
        return saved_paths

    except Exception as e:
        logger.error(f"failed to extract highlights: {e}")
        return []
