import os
import random
from app.utils import utils

def get_sfx_dir():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    sfx_dir = os.path.join(root, "resource", "sfx")
    if not os.path.exists(sfx_dir):
        os.makedirs(sfx_dir, exist_ok=True)
    return sfx_dir

def get_random_transition_sfx():
    sfx_dir = get_sfx_dir()
    # Assume any mp3/wav in sfx root or 'transition' subfolder is a transition element
    # For simplicity, look in root first
    files = [f for f in os.listdir(sfx_dir) if f.endswith(".mp3") or f.endswith(".wav")]
    if not files:
        return None
    return os.path.join(sfx_dir, random.choice(files))
