"""
Video Quality Scoring — Heuristic-based scoring to filter irrelevant or low-quality video clips.

Since we don't have vision AI available locally, this uses metadata-based heuristics
to score each downloaded video clip for relevance and quality.
"""

import os
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip


def score_video(
    video_path: str,
    search_term: str = "",
    minimum_duration: float = 3.0,
    minimum_resolution: int = 720,
    minimum_fps: int = 24,
) -> dict:
    """
    Score a video clip based on quality heuristics.
    
    Returns:
        dict with 'score' (0-100), 'passed' (bool), and 'details' (dict)
    """
    score = 0
    details = {}
    
    try:
        if not os.path.exists(video_path):
            return {"score": 0, "passed": False, "details": {"error": "File not found"}}
        
        file_size = os.path.getsize(video_path)
        
        # File size check (very small files are likely corrupt)
        if file_size < 50_000:  # < 50KB
            return {"score": 0, "passed": False, "details": {"error": "File too small (likely corrupt)"}}
        
        details["file_size_mb"] = round(file_size / (1024 * 1024), 2)
        
        clip = VideoFileClip(video_path)
        
        # Duration scoring (0-25 points)
        duration = clip.duration
        details["duration"] = round(duration, 1)
        if duration >= minimum_duration:
            duration_score = min(25, int(duration * 5))
            score += duration_score
            details["duration_score"] = duration_score
        else:
            details["duration_score"] = 0
        
        # Resolution scoring (0-25 points)
        width = clip.w
        height = clip.h
        details["resolution"] = f"{width}x{height}"
        min_dim = min(width, height)
        if min_dim >= 1080:
            score += 25
            details["resolution_score"] = 25
        elif min_dim >= 720:
            score += 20
            details["resolution_score"] = 20
        elif min_dim >= 480:
            score += 10
            details["resolution_score"] = 10
        else:
            details["resolution_score"] = 0
        
        # FPS scoring (0-15 points)
        fps = clip.fps
        details["fps"] = round(fps, 1)
        if fps >= 30:
            score += 15
            details["fps_score"] = 15
        elif fps >= 24:
            score += 10
            details["fps_score"] = 10
        else:
            details["fps_score"] = 5
        
        # Aspect ratio bonus (0-10 points)
        # Portrait videos (9:16) get bonus for YouTube Shorts
        aspect_ratio = width / height if height > 0 else 1
        if 0.5 <= aspect_ratio <= 0.65:  # Portrait (9:16)
            score += 10
            details["aspect_bonus"] = 10
        elif 1.7 <= aspect_ratio <= 1.8:  # Landscape (16:9)
            score += 8
            details["aspect_bonus"] = 8
        elif 0.95 <= aspect_ratio <= 1.05:  # Square (1:1)
            score += 5
            details["aspect_bonus"] = 5
        else:
            details["aspect_bonus"] = 0
        
        # File size quality indicator (0-15 points)
        # Higher bitrate = better quality (for same resolution)
        bitrate = (file_size * 8) / duration if duration > 0 else 0  # bits per second
        details["bitrate_kbps"] = round(bitrate / 1000, 0)
        if bitrate > 5_000_000:  # > 5 Mbps
            score += 15
            details["bitrate_score"] = 15
        elif bitrate > 2_000_000:  # > 2 Mbps
            score += 10
            details["bitrate_score"] = 10
        elif bitrate > 1_000_000:  # > 1 Mbps
            score += 5
            details["bitrate_score"] = 5
        else:
            details["bitrate_score"] = 0
        
        # Stability bonus (0-10 points) — file opens and reads cleanly
        score += 10
        details["stability_score"] = 10

        # [I3] Tag match score (0-30 points)
        # Give a massive bonus to videos where the exact search term keywords appear in the path/name.
        # This ensures a highly relevant 720p video easily beats a generic irrelevant 1080p video.
        if search_term:
            tokens = [t.strip().lower() for t in search_term.split() if len(t) > 2]
            path_lower = video_path.lower()
            matched = sum(1 for t in tokens if t in path_lower)
            # +10 points per matched keyword, up to 30 points
            tag_score = min(30, matched * 10)
            score += tag_score
            details["tag_match_score"] = tag_score
        else:
            details["tag_match_score"] = 0

        clip.close()
        
        passed = score >= 40  # Minimum threshold
        details["total_score"] = score
        
        return {"score": score, "passed": passed, "details": details}
        
    except Exception as e:
        logger.warning(f"Video scoring failed for {video_path}: {str(e)}")
        return {"score": 0, "passed": False, "details": {"error": str(e)}}


def filter_videos_by_quality(
    video_paths: list,
    min_score: int = 60,
    search_term: str = "",
) -> list:
    """
    Filter a list of video paths, keeping only those that pass quality scoring.
    
    Args:
        video_paths: List of video file paths
        min_score: Minimum score to keep (0-100)
        search_term: Used to compute tag match bonus score
    
    Returns:
        Filtered list of video paths sorted by score (best first)
    """
    scored_videos = []
    
    for path in video_paths:
        result = score_video(path, search_term=search_term)
        if result["passed"] and result["score"] >= min_score:
            scored_videos.append((path, result["score"]))
            logger.debug(f"Video PASSED ({result['score']}/100): {os.path.basename(path)}")
        else:
            logger.debug(f"Video REJECTED ({result['score']}/100): {os.path.basename(path)} — {result['details']}")
    
    # Sort by score descending (best first)
    scored_videos.sort(key=lambda x: x[1], reverse=True)
    
    filtered = [path for path, _ in scored_videos]
    logger.info(f"Video quality filter: {len(filtered)}/{len(video_paths)} passed (min_score={min_score})")
    
    return filtered
