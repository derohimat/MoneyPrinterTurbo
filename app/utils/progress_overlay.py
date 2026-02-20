
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import VideoClip

def detect_list_content(script: str):
    """
    Detect if script is list-style. Returns list of segment boundaries.
    Detects: "1.", "2.", "first", "second", "number N", ordinals.
    Returns: [{"index": 1, "total": 10}, ...]
    Note: Exact timing of list items from script text ALONE is hard without alignment.
    For this implementation, we will assume EQUAL spacing if timestamps are not provided,
    OR we can try to use subtitle timings if we had them aligned to script items.
    
    SIMPLIFICATION for TIER 4:
    If we have subtitles (which we do in generate_video), we can scan subtitles for "1.", "2.", "Step 1" etc.
    So this function should probably take subtitles as input?
    Or we just return the COUNT of items and their LABELS, and `create_progress_bar_clip` 
    needs to know WHEN they happen.
    
    If we only have script:
    We can't know when "Item 2" starts.
    
    Let's change logic: `create_progress_bar_clip` will receive `subtitles` and parse them to find list markers.
    """
    pass # Replaced by logic in parses

def parse_list_from_subtitles(subtitles):
    """
    subtitles: list of (index, time_str, text)
    Returns: [{"index": 1, "total": 3, "start": 0.0, "end": 5.0, "label": "1"}, ...]
    """
    import re
    from app.utils import utils
    
    list_items = []
    # Patterns: "1.", "Step 1", "First", "(1)"
    # Simplest: "^\d+\." or "Step \d+"
    pattern = r'(?:^|\s)(\d+)\.|^Step\s+(\d+)'
    
    # We need to find Total.
    # Scan all subs first.
    param_matches = []
    for sub in subtitles:
        text = sub[2].strip()
        match = re.search(pattern, text)
        if match:
             val = match.group(1) or match.group(2)
             if val.isdigit():
                 start = utils.srt_time_to_seconds(sub[1].split(" --> ")[0])
                 param_matches.append({"val": int(val), "start": start})
    
    if not param_matches:
        return []
        
    # Filter for sequential? 1, 2, 3...
    # Or just take them.
    # If we have 1, 2, 3. The total is 3.
    # Segment 1: start of 1 -> start of 2.
    # Segment 2: start of 2 -> start of 3.
    # Segment 3: start of 3 -> end of video.
    
    # Sort by value
    param_matches.sort(key=lambda x: x["val"])
    
    # Check if sequential (1,2,3... with optional gaps but monotonic)
    # If we have 1, 2, 5. It's weird.
    # If we have 1, 1, 2. (Repeating 1).
    
    # Dedup by value
    unique = {}
    for p in param_matches:
        if p["val"] not in unique:
            unique[p["val"]] = p["start"]
            
    sorted_vals = sorted(unique.keys())
    # Should start with 1?
    if not sorted_vals or sorted_vals[0] != 1:
        return []
        
    # Should be mostly consecutive?
    # If 1, 2, 4. We assume 3 was missed?
    # Let's just Map them.
    
    total = sorted_vals[-1]
    segments = []
    
    for i, val in enumerate(sorted_vals):
        start = unique[val]
        if i < len(sorted_vals) - 1:
            end = unique[sorted_vals[i+1]]
        else:
            end = None # Will be set to video end
            
        segments.append({
            "index": val,
            "total": total,
            "start": start,
            "end": end
        })
        
    return segments

def create_progress_bar_clip(video_size, subtitles, video_duration, bar_height=10, 
                              fill_color="yellow", show_counter=True):
    """
    Create overlay clip.
    subtitles: Srt parsed list.
    """
    w, h = video_size
    segments = parse_list_from_subtitles(subtitles)
    
    if not segments:
        return None
        
    # Fix last segment end
    segments[-1]["end"] = video_duration
    
    # Validate segments cover duration somewhat
    # If segment 1 starts at 10s. 0-10s is Segment 0?
    if segments[0]["start"] > 1.0:
        # Implicit segment 0 (Intro)
        segments.insert(0, {
            "index": 0,
            "total": segments[0]["total"],
            "start": 0.0,
            "end": segments[0]["start"]
        })
        
    # Convert color
    from PIL import ImageColor
    if isinstance(fill_color, str):
        try:
            fill_rgb = ImageColor.getrgb(fill_color)
        except:
             fill_rgb = (255, 215, 0)
    else:
        fill_rgb = fill_color
        
    def make_frame(t):
        # Find current segment
        # Check explicit ranges
        cur = None
        for s in segments:
            if s["start"] <= t:
                if s["end"] is None or t < s["end"]:
                    cur = s
                    break
        
        if not cur:
            cur = segments[-1] # Fallback
            
        # Global Progress within video? Or stepped?
        # Spec says: "Bar fills smoothly from segment to segment."
        # Meaning: continuous fill over the whole video?
        # Or: Segment 1 fills 1/N to 2/N?
        # "showing current position (e.g., '3/10')"
        # Usually listicle progress bars fill up as we go.
        # So progress = t / video_duration?
        # OR progress = (index - 1) + (local_progress) / total?
        
        # Let's do Global Linear Progress if unsure, overlayed with Steps?
        # "Current position (3/10)" implies discrete steps.
        # "Smooth fill animation".
        # Let's do: Fill = t / duration.
        # Text = "Step X/Y".
        
        total = cur["total"]
        if total == 0: total = 1
        
        # Draw
        img = Image.new("RGBA", (w, bar_height + 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Positioning: Top of Safe Zone. 
        # Safe zone top is usually ~100px down.
        # Let's put it at y=100.
        bar_y = 10
        
        # Background bar
        bg_color = (255, 255, 255, 80)
        draw.rectangle([(20, bar_y), (w-20, bar_y+bar_height)], fill=bg_color, outline=None)
        
        # Fill bar (Global progress)
        global_progress = t / video_duration
        fill_w = int((w-40) * global_progress)
        draw.rectangle([(20, bar_y), (20+fill_w, bar_y+bar_height)], fill=fill_rgb)
        
        # Counter text
        if show_counter and cur["index"] > 0:
            txt = f"{cur['index']}/{cur['total']}"
            try:
                # Use default font
                font = ImageFont.load_default()
                # draw.text((w/2, 0), txt, font=font, fill="white", anchor="mt")
                # anchor mt not supported in old PIL?
                w_text = draw.textlength(txt, font=font)
                draw.text(((w-w_text)/2, 0), txt, font=font, fill="white")
            except:
                pass
                
        return np.array(img)

    return VideoClip(make_frame, duration=video_duration)
