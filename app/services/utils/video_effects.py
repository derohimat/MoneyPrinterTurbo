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


# T4-3: Visual Effects Library

def screen_shake(clip: Clip, intensity: int = 10) -> Clip:
    """Random per-frame pixel offset."""
    def make_frame(get_frame, t):
        frame = get_frame(t)
        # Random dx, dy
        dx, dy = np.random.randint(-intensity, intensity, 2)
        # Using roll for wrap-around shift (fastest)
        # Axis 0 = rows (y), Axis 1 = columns (x)
        frame_rolled = np.roll(frame, dx, axis=1)
        frame_rolled = np.roll(frame_rolled, dy, axis=0)
        return frame_rolled
        
    return clip.transform(make_frame)

def flash_effect(clip: Clip, duration: float = 0.2, color: str = "white") -> Clip:
    """Flash screen with color for duration at start."""
    w, h = clip.size
    from PIL import ImageColor
    if isinstance(color, str):
        c = ImageColor.getrgb(color)
    else:
        c = color
        
    flash = ColorClip(size=(w, h), color=c).with_duration(duration)
    # Fade out flash
    flash = flash.with_effects([vfx.FadeOut(duration)])
    
    # Ideally composite over clip starting at 0
    # But if clip is long, flash only at start.
    return CompositeVideoClip([clip, flash.with_start(0)])

def chromatic_aberration(clip: Clip, offset: int = 5) -> Clip:
    """Shift Red and Blue channels in opposite directions."""
    def make_frame(get_frame, t):
        frame = get_frame(t).copy()
        # R channel shift
        frame[:, :, 0] = np.roll(frame[:, :, 0], offset, axis=1)
        # B channel shift
        frame[:, :, 2] = np.roll(frame[:, :, 2], -offset, axis=1)
        return frame
    return clip.transform(make_frame)

def glitch_effect(clip: Clip) -> Clip:
    """RGB split + random slicing."""
    def make_frame(get_frame, t):
        frame = get_frame(t).copy()
        # Occasional heavy glitch
        if np.random.random() > 0.3:
            offset = np.random.randint(5, 20)
            frame[:, :, 0] = np.roll(frame[:, :, 0], offset, axis=1)
            frame[:, :, 2] = np.roll(frame[:, :, 2], -offset, axis=1)
            # Slice
            y = np.random.randint(0, frame.shape[0] - 20)
            h_slice = np.random.randint(5, 50)
            shift = np.random.randint(-50, 50)
            if y+h_slice < frame.shape[0]:
                 # Shift slice horizontally
                 frame[y:y+h_slice, :, :] = np.roll(frame[y:y+h_slice, :, :], shift, axis=1)
        return frame
    return clip.transform(make_frame)

def zoom_burst(clip: Clip, duration: float = 0.3, zoom_to: float = 1.3) -> Clip:
    """Quick zoom in and out (pulse)."""
    w, h = clip.size
    orig_dur = clip.duration
    
    def make_frame(get_frame, t):
        frame = get_frame(t)
        img = Image.fromarray(frame)
        
        # Triangle wave for zoom: 0 -> max -> 0
        cycle_t = t % duration
        progress = cycle_t / duration
        
        if progress < 0.5:
            # 0 -> 1: Zoom in
            z = 1.0 + (zoom_to - 1.0) * (progress * 2)
        else:
            # 1 -> 0: Zoom out
            z = zoom_to - (zoom_to - 1.0) * ((progress - 0.5) * 2)
            
        new_w = int(w / z)
        new_h = int(h / z)
        
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        
        cropped = img.crop((x, y, x + new_w, y + new_h))
        resized = cropped.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(resized)

    return clip.transform(make_frame)
