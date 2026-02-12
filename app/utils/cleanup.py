"""
Temp File Cleanup — Auto-delete temporary task files to free up disk space.
"""
import os
import shutil
import time
from loguru import logger
from app.utils import utils

def cleanup_task(task_id: str):
    """
    Delete the specific task directory and all its contents.
    Call this after successful video generation and upload.
    """
    task_dir = utils.task_dir(task_id)
    if os.path.exists(task_dir):
        try:
            shutil.rmtree(task_dir)
            logger.info(f"Cleaned up temp files for task: {task_id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup task directory {task_dir}: {str(e)}")

def cleanup_cache(max_age_hours: int = 48):
    """
    Delete cached videos older than max_age_hours.
    """
    cache_dir = os.path.join(utils.root_dir(), "storage", "cache_videos")
    if not os.path.exists(cache_dir):
        return

    now = time.time()
    deleted_count = 0
    
    for filename in os.listdir(cache_dir):
        filepath = os.path.join(cache_dir, filename)
        if os.path.isfile(filepath):
            file_age_hours = (now - os.path.getmtime(filepath)) / 3600
            if file_age_hours > max_age_hours:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete old cache file {filename}: {str(e)}")
    
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old cache videos (> {max_age_hours}h)")
