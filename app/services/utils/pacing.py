import random
from enum import Enum

class PacingMode(Enum):
    FAST = "fast"
    SLOW = "slow"
    DYNAMIC = "dynamic"
    DEFAULT = "default"

def get_clip_duration(mode: str = "default") -> float:
    """
    Get a duration for the next clip based on the pacing mode.
    
    Args:
        mode: The pacing mode (fast, slow, dynamic, default)
        
    Returns:
        float: Duration in seconds
    """
    if mode == PacingMode.FAST.value:
        return random.uniform(1.5, 3.0)
    elif mode == PacingMode.SLOW.value:
        return random.uniform(3.0, 5.0)
    elif mode == PacingMode.DYNAMIC.value:
        # 70% chance of fast cut, 30% chance of slow cut
        if random.random() < 0.7:
             return random.uniform(1.5, 2.5)
        else:
             return random.uniform(3.0, 4.5)
    else: # Default
        return random.uniform(2.0, 4.0)

def get_pacing_mode(video_subject: str = "") -> str:
    """Determine pacing mode based on subject (heuristic) or default."""
    # Could range based on keywords, but rigorous analysis is TIER 6.
    return PacingMode.DYNAMIC.value # Default to dynamic for better engagement
