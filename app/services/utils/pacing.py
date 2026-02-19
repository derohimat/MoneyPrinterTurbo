import random
from enum import Enum

class PacingMode(Enum):
    FAST = "fast"
    SLOW = "slow"
    DYNAMIC = "dynamic"
    DEFAULT = "default"

def get_clip_duration(mode: str = "default", current_time: float = 0, total_duration: float = 60) -> float:
    """
    Get a duration for the next clip based on pacing mode and position in timeline.
    
    Args:
        mode: The pacing mode (fast, slow, dynamic, default)
        current_time: Current timestamp in the video timeline (for dynamic pacing)
        total_duration: Total expected duration of the video (for dynamic pacing)
        
    Returns:
        float: Duration in seconds
    """
    min_dur = 2.0
    max_dur = 4.0

    if mode == PacingMode.FAST.value:
        min_dur, max_dur = 1.5, 3.0
    elif mode == PacingMode.SLOW.value:
        min_dur, max_dur = 3.0, 5.0
    elif mode == PacingMode.DYNAMIC.value:
        # Pacing Curve: Fast Start -> Slower Middle -> Fast End
        if total_duration > 0:
            progress = current_time / total_duration
        else:
            progress = 0
            
        # First 20% and Last 20%: Fast
        if progress < 0.20 or progress > 0.80:
             min_dur, max_dur = 1.0, 2.5
        else:
             # Middle: Mixed/Slower
             min_dur, max_dur = 2.5, 5.0
    else: # Default
        min_dur, max_dur = 2.0, 4.0
        
    return random.uniform(min_dur, max_dur)

def get_pacing_mode(video_subject: str = "") -> str:
    """Determine pacing mode based on subject (heuristic) or default."""
    # Could range based on keywords, but rigorous analysis is TIER 6.
    return PacingMode.DYNAMIC.value # Default to dynamic for better engagement
