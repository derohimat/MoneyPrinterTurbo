from moviepy import Clip, vfx, CompositeVideoClip, ColorClip, ImageClip
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
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

# T2-5: Pop-in animation
def pop_in_effect(clip: Clip, duration: float = 0.5) -> Clip:
    """
    Animated scale from 0 to 1 over duration with overshoot (pop effect).
    """
    def scale(t):
        if t < duration:
            progress = t / duration
            # Pop effect: Overshoot to 1.2 then settle to 1.0
            if progress < 0.7:
                 s = (progress / 0.7) * 1.2
                 return max(0.1, s) # Avoid 0 size crash
            else:
                 return 1.2 - ((progress - 0.7) / 0.3) * 0.2
        return 1.0
    
    # Apply resize animation
    return clip.resized(scale)

# T2-2: Subtitle background box
def create_rounded_box_clip(size, color, opacity=0.8, radius=15, duration=None):
    """
    Create a rounded rectangle ColorClip.
    """
    w, h = size
    # Increase resolution for anti-aliasing
    scale = 2
    w_up, h_up = int(w * scale), int(h * scale)
    radius_up = int(radius * scale)
    
    # Create mask image (white rounded rect on black bg)
    img = Image.new('L', (w_up, h_up), 0)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w_up, h_up), radius=radius_up, fill=255)
    
    # Resize back
    mask_img = img.resize((int(w), int(h)), Image.Resampling.LANCZOS)
    mask_arr = np.array(mask_img) / 255.0
    
    from PIL import ImageColor
    if isinstance(color, str):
        color = ImageColor.getrgb(color)
        
    # Create ColorClip
    bg_clip = ColorClip(size=(int(w), int(h)), color=color).with_opacity(opacity)
    if duration:
        bg_clip = bg_clip.with_duration(duration)
    
    # Set mask
    mask_clip = ImageClip(mask_arr, is_mask=True)
    if duration:
        mask_clip = mask_clip.with_duration(duration)

    return bg_clip.with_mask(mask_clip)
