
import threading
import time
import schedule
from loguru import logger
from app.utils import db

# Delayed imports to avoid circular dependency if uploads use db
# from app.utils import youtube_upload, tiktok_upload, instagram_upload

# Scheduler thread
_scheduler_thread = None
_stop_event = threading.Event()

def publish_due_tasks():
    """Check db for due tasks and publish them."""
    tasks = db.get_due_publish_tasks()
    if not tasks:
        return
        
    logger.info(f"scheduler found {len(tasks)} due tasks")
    
    for task in tasks:
        task_id = task["id"]
        platform = task["platform"]
        video_path = task["video_path"]
        
        logger.info(f"processing publish task {task_id} for {platform}")
        db.update_publish_status(task_id, "processing")
        
        try:
            # metadata
            meta = {}
            if task["metadata_json"]:
                import json
                try:
                    meta = json.loads(task["metadata_json"])
                except:
                    pass
            
            title = meta.get("title", "Video")
            desc = meta.get("description", "")
            tags = meta.get("tags", [])
            
            from app.utils import youtube_upload, tiktok_upload, instagram_upload 
            
            result = False
            error = None
            
            if platform == "youtube":
                # Assuming youtube_upload has a generic upload function
                # We need to verify youtube_upload.py signature.
                # For now using a placeholder call based on typical usage
                try:
                    # check if upload_video exists
                    if hasattr(youtube_upload, "upload_video"):
                        youtube_upload.upload_video(video_path, title, desc, tags)
                        result = True
                    else:
                        error = "YouTube uploader not implemented"
                except Exception as e:
                    error = str(e)
                    
            elif platform == "tiktok":
                try:
                    if hasattr(tiktok_upload, "upload_video"):
                        tiktok_upload.upload_video(video_path, title, desc, tags)
                        result = True
                    else:
                        error = "TikTok uploader not implemented"
                except Exception as e:
                    error = str(e)
                    
            elif platform == "instagram":
                try:
                     if hasattr(instagram_upload, "upload_video"):
                        instagram_upload.upload_video(video_path, title, desc, tags)
                        result = True
                     else:
                        error = "Instagram uploader not implemented"
                except Exception as e:
                    error = str(e)
            else:
                error = f"Unknown platform {platform}"
                
            if result:
                db.update_publish_status(task_id, "published")
                logger.info(f"successfully published task {task_id}")
            else:
                db.update_publish_status(task_id, "failed", error_message=error)
                logger.error(f"failed to publish task {task_id}: {error}")
                
        except Exception as e:
            logger.error(f"crash processing task {task_id}: {e}")
            db.update_publish_status(task_id, "failed", error_message=str(e))

def run_scheduler():
    """Main scheduler loop."""
    logger.info("scheduler started")
    
    # Check every minute
    schedule.every(1).minutes.do(publish_due_tasks)
    
    # Also run once immediately on startup?
    # publish_due_tasks() 
    
    while not _stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
        
    logger.info("scheduler stopped")

def start():
    """Start the scheduler in a background thread."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
        
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    _scheduler_thread.start()

def stop():
    """Stop the scheduler."""
    _stop_event.set()
    if _scheduler_thread:
        _scheduler_thread.join()
