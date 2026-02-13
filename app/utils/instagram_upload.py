from instagrapi import Client
from loguru import logger
import os
import argparse

# Config
SESSION_FILE = "instagram_session.json"

def login(username, password):
    """
    Login to Instagram and save session.
    """
    cl = Client()
    
    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(username, password)
            logger.info("Session loaded successfully")
        except Exception as e:
            logger.warning(f"Session load failed, re-logging in: {e}")
            cl.login(username, password)
    else:
        cl.login(username, password)
    
    cl.dump_settings(SESSION_FILE)
    logger.success(f"Login successful! Session saved to {SESSION_FILE}")
    return cl

def upload_reel(username, password, video_path, caption):
    """
    Upload a video as Reel.
    """
    cl = login(username, password)
    
    logger.info(f"Uploading Reel: {video_path}")
    try:
        media = cl.clip_upload(
            path=video_path,
            caption=caption
        )
        logger.success(f"Uploaded Reel! PK: {media.pk}")
        return True
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True, help="Instagram Username")
    parser.add_argument("--passw", required=True, help="Instagram Password")
    parser.add_argument("--video", required=True, help="Video path")
    parser.add_argument("--caption", default="", help="Caption")
    
    args = parser.parse_args()
    
    upload_reel(args.user, args.passw, args.video, args.caption)
