
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageSequenceClip
from app.utils import utils
from loguru import logger

def extract_numbers_from_script(script: str, subtitles: list) -> list:
    """
    Find numbers >= 100 in script and map them to timestamps using subtitle data.
    subtitles: list of (index, time_str, text) from file_to_subtitles
    Returns: [{"value": 1000, "start": 1.5, "end": 2.5}, ...]
    """
    numbers = []
    # Regex for numbers, including comma/dot separators
    # Also optionally followed by multiplier words
    # Limitation: This regex is simple. Better use specific text-to-num library or just digits.
    # Focusing on digits for now: "10,000", "1.5 million" -> difficult.
    # Pattern: \b\d[\d,.]*\b
    
    # We iterate subtitles to find numbers in them
    # This is safer than aligning script to subtitles manually
    
    pattern = r'\b(\d{2,}(?:[.,]\d+)?)\b' # Matches 10, 100, 1,000. Ignore single digits.
    
    for item in subtitles:
        # item: (index, "00:00:01,000 --> ...", "text")
        time_str = item[1]
        text = item[2]
        
        start_str, end_str = time_str.split(" --> ")
        start = utils.srt_time_to_seconds(start_str)
        end = utils.srt_time_to_seconds(end_str)
        
        matches = re.finditer(pattern, text)
        for match in matches:
            num_str = match.group(1)
            # Clean num_str (remove commas)
            clean_str = num_str.replace(",", "").replace(".", "")
            try:
                # If dot was decimal, this might be wrong.
                # Heuristic: if '.' in text, treat as decimal?
                # "1.5" -> 15? No.
                # For simplistic approach, only integers >= 100.
                if "." in num_str and "," not in num_str:
                     val = float(num_str)
                else:
                     val = int(clean_str)
                     
                if val >= 100:
                    numbers.append({
                        "value": val,
                        "start": start,
                        "end": end,
                        "text": num_str # Keep original formatting or reformat?
                    })
            except ValueError:
                continue
                
    return numbers

def create_counter_clip(target_number: int, duration: float = 1.5, size: tuple = (600, 200), font_path: str = None, color: str = "yellow") -> ImageSequenceClip:
    """
    Generate a counting-up animation clip.
    """
    fps = 30
    frames = []
    
    try:
        font = ImageFont.truetype(font_path, 100) if font_path else ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    from PIL import ImageColor
    if isinstance(color, str):
        try:
            fill_color = ImageColor.getrgb(color) 
        except:
            fill_color = (255, 255, 0) # Fallback Yellow
    else:
        fill_color = color
        
    for i in range(int(duration * fps)):
        progress = i / (duration * fps)
        # Ease out cubic
        eased = 1 - (1 - progress) ** 3
        current = int(target_number * eased)
        
        target_int = int(target_number)
        # If target was float?
        
        txt = f"{current:,}"
        
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw text centered
        # bbox = draw.textbbox((0,0), txt, font=font)
        # w = bbox[2] - bbox[0]
        # h = bbox[3] - bbox[1]
        # pos = ((size[0] - w) // 2, (size[1] - h) // 2)
        
        # Stroke
        stroke_width = 4
        stroke_fill = (0, 0, 0)
        
        draw.text((size[0]//2, size[1]//2), txt, font=font, anchor="mm", fill=fill_color, stroke_width=stroke_width, stroke_fill=stroke_fill)
        
        frames.append(np.array(img))
        
    return ImageSequenceClip(frames, fps=fps)
