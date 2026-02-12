"""
Auto Thumbnail Generator - Extracts a frame from the video and overlays title text.
Generates a 1280x720 JPEG thumbnail ready for YouTube upload.
"""

import os
from loguru import logger
from moviepy import VideoFileClip
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils


def generate_thumbnail(
    video_path: str,
    title: str,
    output_path: str = "",
    timestamp_pct: float = 0.3,
    width: int = 1280,
    height: int = 720,
) -> str:
    """
    Generate a thumbnail from a video with title text overlay.
    
    Args:
        video_path: Path to the source video
        title: Title text to overlay
        output_path: Where to save the thumbnail. Auto-generated if empty.
        timestamp_pct: Where in the video to grab the frame (0.0-1.0)
        width: Thumbnail width
        height: Thumbnail height
    
    Returns:
        Path to the generated thumbnail
    """
    if not output_path:
        base = os.path.splitext(video_path)[0]
        output_path = f"{base}_thumb.jpg"

    try:
        # Extract frame from video
        clip = VideoFileClip(video_path)
        timestamp = clip.duration * timestamp_pct
        frame = clip.get_frame(timestamp)
        clip.close()

        # Convert to PIL Image and resize
        img = Image.fromarray(frame)
        img = img.resize((width, height), Image.LANCZOS)

        # Add dark gradient overlay at bottom for text readability
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        for y in range(height // 2, height):
            alpha = int(200 * ((y - height // 2) / (height // 2)))
            draw_overlay.rectangle([(0, y), (width, y + 1)], fill=(0, 0, 0, alpha))
        
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)

        # Add title text
        draw = ImageDraw.Draw(img)
        
        # Try to use a good font
        font = _get_best_font(size=48)
        font_small = _get_best_font(size=28)

        # Wrap title text
        wrapped_title = _wrap_text(draw, title, font, max_width=width - 80)
        
        # Calculate text position (bottom area)
        text_bbox = draw.multiline_textbbox((0, 0), wrapped_title, font=font)
        text_height = text_bbox[3] - text_bbox[1]
        text_y = height - text_height - 60

        # Draw text shadow
        draw.multiline_text(
            (42, text_y + 2), wrapped_title, font=font, fill=(0, 0, 0, 200), align="left"
        )
        # Draw text
        draw.multiline_text(
            (40, text_y), wrapped_title, font=font, fill=(255, 255, 255, 255), align="left"
        )

        # Convert back to RGB for JPEG
        img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=90)
        
        logger.success(f"Thumbnail generated: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to generate thumbnail: {str(e)}")
        return ""


def _get_best_font(size: int = 48):
    """Try to load a nice font, fall back to default."""
    font_candidates = [
        os.path.join(utils.font_dir(), "MicrosoftYaHeiBold.ttc"),
        os.path.join(utils.font_dir(), "STHeitiMedium.ttc"),
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]
    
    for font_path in font_candidates:
        try:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    
    return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_width: int) -> str:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    # Limit to 3 lines max
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:len(lines[-1])-3] + "..."
    
    return "\n".join(lines)
