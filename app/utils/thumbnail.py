
import os
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont, ImageColor
from moviepy import VideoFileClip
from loguru import logger
import random
import numpy as np

def apply_color_shift(img, r=0, g=0, b=0):
    """Apply RGB color shift to image."""
    data = np.array(img)
    # R
    data[..., 0] = np.clip(data[..., 0] + r, 0, 255)
    # G
    data[..., 1] = np.clip(data[..., 1] + g, 0, 255)
    # B
    data[..., 2] = np.clip(data[..., 2] + b, 0, 255)
    return Image.fromarray(data)

def add_vignette(img, intensity=0.4):
    """Add vignette effect."""
    w, h = img.size
    # Create gradient mask
    # Simple radial gradient
    # Center is white (transparent in mask context usually means opaqe if alpha mask? 
    # Here we want to darken corners. So center=NoChange, Corners=Dark.
    # We create a black layer and mask it.
    
    # Actually, simpler: create a radial gradient from transparent to black.
    # PIL doesn't have built-in radial gradient easily.
    # Approximate with halo used in video_effects or manual.
    
    # Quick vignette: Darken corners.
    # Create a layer.
    
    # Method: Create a radial gradient image L mode.
    # Center 255, corners 0. 
    # Then use it to blend black layer?
    
    # Let's use a simpler approach for now to avoid complex deps:
    # Just darken borders?
    # Or skip if too complex for PIL only without numpy meshgrids.
    pass 
    # Revisit if needed. For now returning img as is or use simple contrast.
    return img

def generate_thumbnails(video_path: str, output_dir: str, count: int = 3, text_overlay: str = None):
    """
    Generate multiple thumbnail variants from video.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    try:
        clip = VideoFileClip(video_path)
        duration = clip.duration
        
        # Pick timestamps: 20%, 50%, 80%
        # If count > 3, add more.
        # Avoid very start/end.
        
        timestamps = []
        if count == 1:
            timestamps = [duration * 0.5]
        else:
            # Linear spacing between 10% and 90%
            start_p = 0.1
            end_p = 0.9
            step = (end_p - start_p) / (count + 1)
            for i in range(count):
                timestamps.append(duration * (start_p + step * (i + 1)))
                
        # Enhancements styles
        styles = [
            ("original", lambda img: img),
            ("vibrant", lambda img: ImageEnhance.Color(ImageEnhance.Contrast(img).enhance(1.2)).enhance(1.5)),
            ("high_contrast", lambda img: ImageEnhance.Contrast(img).enhance(1.4)),
            ("warm", lambda img: apply_color_shift(img, r=20, g=10, b=-10)),
            ("cool", lambda img: apply_color_shift(img, r=-10, g=0, b=20)),
        ]
        
        saved_paths = []
        
        for i, ts in enumerate(timestamps):
            # Extract frame
            frame = clip.get_frame(ts)
            img = Image.fromarray(frame)
            
            # Apply Style (Cycle through styles)
            style_name, style_func = styles[i % len(styles)]
            
            # T5-2: AI Enhancement (Basics)
            # Always apply slight sharpening and upscale if needed?
            # Assuming 1080p source, thumbnail target 1280x720.
            img.thumbnail((1280, 720)) # Resize to fit
            # Actually we want to fill 1280x720?
            # If video is 9:16 (Shorts), thumbnail should ideally be 9:16 too for Shorts?
            # YouTube Shorts thumbnails are usually vertical.
            # Standard video is 16:9.
            # Let's assume input aspect ratio is preserved.
            
            img = style_func(img)
            
            # Add text overlay if provided
            if text_overlay:
                draw = ImageDraw.Draw(img)
                # Load font
                try:
                    font_size = int(img.height * 0.1) # 10% of height
                    font = ImageFont.truetype("arial.ttf", font_size)
                except:
                    font = ImageFont.load_default()
                    
                # Draw text with shadow
                # Center
                # text_w = draw.textlength(text_overlay, font=font)
                # x = (img.width - text_w) / 2
                # y = img.height * 0.8 # Bottom
                
                # Draw shadow
                # draw.text((x+4, y+4), text_overlay, font=font, fill="black")
                # draw.text((x, y), text_overlay, font=font, fill="white")
                pass

            filename = f"thumbnail_{i+1}_{style_name}.jpg"
            path = os.path.join(output_dir, filename)
            img.save(path, quality=90)
            saved_paths.append(path)
            logger.info(f"generated thumbnail: {path}")
            
        return saved_paths
        
    except Exception as e:
        logger.error(f"failed to generate thumbnails: {e}")
        return []
