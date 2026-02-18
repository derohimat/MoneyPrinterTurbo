from moviepy import Clip, vfx, CompositeVideoClip
import numpy as np
from PIL import Image, ImageFilter
import random


# FadeIn
def fadein_transition(clip: Clip, t: float = 0.5) -> Clip:
    return clip.with_effects([vfx.FadeIn(t)])


# FadeOut
def fadeout_transition(clip: Clip, t: float = 0.5) -> Clip:
    return clip.with_effects([vfx.FadeOut(t)])


# SlideIn
def slidein_transition(clip: Clip, t: float = 0.5, side: str = "left") -> Clip:
    return clip.with_effects([vfx.SlideIn(t, side)])


# SlideOut
def slideout_transition(clip: Clip, t: float = 0.5, side: str = "left") -> Clip:
    return clip.with_effects([vfx.SlideOut(t, side)])


# T1-1: Ken Burns Effect
def ken_burns_effect(clip: Clip, zoom_factor: float = 1.15, pan_direction: str = "random") -> Clip:
    """
    Apply Ken Burns effect (slow zoom and pan) to a clip.
    """
    w, h = clip.size
    duration = clip.duration
    
    if pan_direction == "random":
        pan_direction = random.choice(["center", "left", "right", "top", "bottom"])

    def make_frame(get_frame, t):
        frame = get_frame(t)
        img = Image.fromarray(frame)
        
        # Calculate zoom progress (1.0 to zoom_factor)
        progress = t / duration
        current_zoom = 1.0 + (zoom_factor - 1.0) * progress
        
        new_w = int(w / current_zoom)
        new_h = int(h / current_zoom)
        
        # Calculate crop position based on direction
        if pan_direction == "center":
            x = (w - new_w) // 2
            y = (h - new_h) // 2
        elif pan_direction == "left":
            x = int((w - new_w) * progress)
            y = (h - new_h) // 2
        elif pan_direction == "right":
            x = int((w - new_w) * (1 - progress))
            y = (h - new_h) // 2
        elif pan_direction == "top":
            x = (w - new_w) // 2
            y = int((h - new_h) * progress)
        elif pan_direction == "bottom":
            x = (w - new_w) // 2
            y = int((h - new_h) * (1 - progress))
        else:
            x, y = (w - new_w) // 2, (h - new_h) // 2

        # Crop and resize back to original size
        cropped = img.crop((x, y, x + new_w, y + new_h))
        resized = cropped.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(resized)

    return clip.transform(make_frame)


# T1-4: New Transitions
def whip_pan_transition(clip: Clip, t: float = 0.3, direction: str = "left") -> Clip:
    """Fast sliding transition with motion blur simulation"""
    return clip.with_effects([vfx.SlideIn(t, direction)]) # Placeholder for now, simplistic


def zoom_transition(clip: Clip, t: float = 0.4, mode: str = "in") -> Clip:
    """Zoom transition (in or out)"""
    # Simple implementation using existing effects or transform
    if mode == "in":
        return clip.with_effects([vfx.FadeIn(t)]) # Placeholder
    else:
        return clip.with_effects([vfx.FadeOut(t)]) # Placeholder
