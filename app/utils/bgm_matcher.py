"""
Smart BGM Matching - Maps categories to specific background music files.

Since the available BGM files are generic (output000.mp3 - output029.mp3),
we assign specific ranges to each category to ensure consistency.
Each category gets a pool of ~3-4 songs to rotate through.

If you add custom BGM files, create subfolders in resource/songs/:
  resource/songs/islamic/
  resource/songs/horror/
  resource/songs/calm/
  etc.
"""

import glob
import os
import random
from loguru import logger
from app.utils import utils


# Map categories to specific BGM file indices for consistent theming
# These are manually curated assignments based on the available tracks
CATEGORY_BGM_MAP = {
    # Calm / Spiritual tracks for Islamic content
    "IslamicPlaces": ["output000.mp3", "output005.mp3", "output010.mp3", "output014.mp3"],

    # Philosophical / Ambient for Stoicism
    "Stoik": ["output001.mp3", "output006.mp3", "output011.mp3", "output017.mp3"],

    # Thoughtful / Introspective for Psychology
    "Psikologi": ["output002.mp3", "output007.mp3", "output012.mp3", "output018.mp3"],

    # Suspenseful / Dark for Mystery
    "Misteri": ["output003.mp3", "output008.mp3", "output013.mp3", "output019.mp3"],

    # Suspenseful / Eerie for Horror
    "Horor": ["output003.mp3", "output008.mp3", "output023.mp3", "output027.mp3"],

    # Upbeat / Informational for Facts
    "Fakta": ["output004.mp3", "output009.mp3", "output015.mp3", "output020.mp3"],

    # Fresh / Natural for Health
    "Kesehatan": ["output005.mp3", "output010.mp3", "output016.mp3", "output021.mp3"],

    # Corporate / Professional for Finance
    "Keuangan": ["output001.mp3", "output011.mp3", "output022.mp3", "output024.mp3"],
}


def get_bgm_for_category(category: str, bgm_type: str = "random", bgm_file: str = "") -> str:
    """
    Get a BGM file matched to the video category.
    
    Args:
        category: Video category (e.g. "IslamicPlaces", "Horor")
        bgm_type: "random" for random selection, "" for no BGM
        bgm_file: Explicit BGM file path (overrides category matching)
    
    Returns:
        Path to the BGM file, or empty string if no BGM
    """
    if not bgm_type:
        return ""

    # If explicit file provided, use it
    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    song_dir = utils.song_dir()

    # Check for category-specific subfolder first
    category_dir = os.path.join(song_dir, category.lower())
    if os.path.isdir(category_dir):
        files = glob.glob(os.path.join(category_dir, "*.mp3"))
        if files:
            selected = random.choice(files)
            logger.info(f"BGM matched from category folder '{category}': {os.path.basename(selected)}")
            return selected

    # Use category mapping
    if category in CATEGORY_BGM_MAP:
        mapped_files = CATEGORY_BGM_MAP[category]
        # Filter to only files that actually exist
        existing = [os.path.join(song_dir, f) for f in mapped_files if os.path.exists(os.path.join(song_dir, f))]
        if existing:
            selected = random.choice(existing)
            logger.info(f"BGM matched for category '{category}': {os.path.basename(selected)}")
            return selected
    
    # Fallback: random from all available
    files = glob.glob(os.path.join(song_dir, "*.mp3"))
    if files:
        selected = random.choice(files)
        logger.info(f"BGM fallback (random): {os.path.basename(selected)}")
        return selected

    return ""
