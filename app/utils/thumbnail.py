
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
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(img)
                # Load font
                try:
                    font_size = int(img.height * 0.08) # 8% of height for bold title
                    # Try to use STHeitiMedium or fallback
                    from app.utils.utils import font_dir
                    import os
                    font_path = os.path.join(font_dir(), "STHeitiMedium.ttc")
                    if not os.path.exists(font_path):
                        font_path = "arial.ttf"
                    font = ImageFont.truetype(font_path, font_size)
                except Exception as e:
                    logger.warning(f"Failed to load custom font for thumbnail: {e}")
                    font = ImageFont.load_default()
                    
                # Calculate text dimensions (Handle multiline if text is long)
                # Wrap text if it exceeds 90% of image width
                max_width = img.width * 0.9
                words = text_overlay.split()
                lines = []
                current_line = []
                
                for word in words:
                    current_line.append(word)
                    # Check width
                    test_line = " ".join(current_line)
                    # PIL 10+ uses textbbox or textlength
                    try:
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        w = bbox[2] - bbox[0]
                    except AttributeError:
                        w, _ = draw.textsize(test_line, font=font)
                        
                    if w > max_width:
                        # Exceeded, pop the last word and finalize the line
                        if len(current_line) > 1:
                            current_line.pop()
                            lines.append(" ".join(current_line))
                            current_line = [word]
                        else:
                            # Single word is too long, just add it anyway
                            lines.append(word)
                            current_line = []
                if current_line:
                    lines.append(" ".join(current_line))
                    
                # Draw multiline text centered horizontally, placed at the top (15% from top)
                # Typical TikTok/Shorts cover style: Bold White text, Heavy Black Stroke/Shadow
                try:
                    line_height = bbox[3] - bbox[1] if 'bbox' in locals() else draw.textsize("A", font=font)[1]
                except:
                    line_height = font_size
                    
                y = img.height * 0.15 # Top 15%
                
                for line in lines:
                    try:
                        bbox = draw.textbbox((0, 0), line, font=font)
                        w = bbox[2] - bbox[0]
                    except AttributeError:
                        w, _ = draw.textsize(line, font=font)
                        
                    x = (img.width - w) / 2
                    
                    # Heavy Stroke/Shadow effect (Draw text multiple times slightly offset)
                    shadow_color = "black"
                    text_color = "yellow" if "hook" in line.lower() or len(lines) == 1 else "white"
                    stroke_width = max(3, int(font_size * 0.05))
                    
                    # Draw thick stroke
                    for offset_x in range(-stroke_width, stroke_width + 1):
                        for offset_y in range(-stroke_width, stroke_width + 1):
                            if offset_x == 0 and offset_y == 0: continue
                            draw.text((x + offset_x, y + offset_y), line, font=font, fill=shadow_color)
                            
                    # Draw drop shadow (offset bottom right)
                    draw.text((x + stroke_width * 2, y + stroke_width * 2), line, font=font, fill=shadow_color)
                    
                    # Draw main text
                    draw.text((x, y), line, font=font, fill=text_color)
                    
                    y += line_height * 1.2 # Move down for next line

            filename = f"thumbnail_{i+1}_{style_name}.jpg"
            path = os.path.join(output_dir, filename)
            img.save(path, quality=90)
            saved_paths.append(path)
            logger.info(f"generated thumbnail: {path}")
            
        return saved_paths
        
    except Exception as e:
        logger.error(f"failed to generate thumbnails: {e}")
        return []


def generate_thumbnail(video_path: str, title: str, output_path: str):
    import shutil
    res = generate_thumbnails(video_path, os.path.dirname(output_path), 1, title)
    if res:
        shutil.copy(res[0], output_path)
        return output_path
    return None
