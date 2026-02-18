"""
T0-5: Platform-specific safe zone definitions.
Prevents subtitles and overlays from being hidden by platform UI elements
(profile icons, like buttons, comment bars, etc.)
"""


# Safe zone margins as percentage of video dimensions
# Each platform has areas at top/bottom/left/right where UI overlays exist
PLATFORM_SAFE_ZONES = {
    "youtube_shorts": {
        "top": 0.10,     # YouTube Shorts title bar
        "bottom": 0.18,  # Like/Comment/Share buttons + description
        "left": 0.05,
        "right": 0.12,   # Right-side action buttons
    },
    "tiktok": {
        "top": 0.08,     # TikTok status bar
        "bottom": 0.20,  # Description + music ticker
        "left": 0.05,
        "right": 0.15,   # Heart/Comment/Share/Bookmark buttons
    },
    "instagram_reels": {
        "top": 0.10,     # Instagram header
        "bottom": 0.20,  # Caption + action buttons
        "left": 0.05,
        "right": 0.12,   # Action buttons
    },
    "default": {
        "top": 0.08,
        "bottom": 0.15,
        "left": 0.05,
        "right": 0.10,
    },
}


def get_safe_zone(platform: str = "default"):
    """Get safe zone margins for a platform.
    
    Returns dict with 'top', 'bottom', 'left', 'right' as pixel fractions (0-1).
    """
    return PLATFORM_SAFE_ZONES.get(platform, PLATFORM_SAFE_ZONES["default"])


def get_safe_subtitle_y(video_height: int, subtitle_height: int, 
                        position: str = "bottom", platform: str = "default"):
    """Calculate safe Y position for subtitle placement.
    
    Args:
        video_height: Height of the video in pixels
        subtitle_height: Height of the subtitle clip in pixels
        position: "bottom", "top", or "center"
        platform: Target platform name
        
    Returns:
        Y coordinate (int) for subtitle placement
    """
    safe = get_safe_zone(platform)
    
    if position == "bottom":
        # Place above the bottom safe zone
        safe_bottom_px = int(video_height * safe["bottom"])
        y = video_height - safe_bottom_px - subtitle_height
        return max(0, y)
    elif position == "top":
        # Place below the top safe zone
        safe_top_px = int(video_height * safe["top"])
        return safe_top_px
    else:  # center
        return (video_height - subtitle_height) // 2


def get_safe_area(video_width: int, video_height: int, platform: str = "default"):
    """Get the safe area rectangle for content placement.
    
    Returns: (x, y, width, height) tuple of the safe content area in pixels.
    """
    safe = get_safe_zone(platform)
    x = int(video_width * safe["left"])
    y = int(video_height * safe["top"])
    w = int(video_width * (1 - safe["left"] - safe["right"]))
    h = int(video_height * (1 - safe["top"] - safe["bottom"]))
    return (x, y, w, h)
