from tiktok_uploader.upload import upload_video
from tiktok_uploader.auth import save_cookies
from loguru import logger
import os

COOKIES_FILE = "tiktok_cookies.txt"

def login():
    """
    Opens browser for manual login and saves cookies.
    """
    logger.info("Opening browser for TikTok login...")
    try:
        save_cookies(COOKIES_FILE)
        logger.success(f"Cookies saved to {COOKIES_FILE}")
        return True
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return False

def upload(video_path: str, description: str = "", cookies_path: str = None):
    """
    Upload video to TikTok.
    """
    if not cookies_path:
        cookies_path = COOKIES_FILE
        
    if not os.path.exists(cookies_path):
        logger.error(f"Cookies file not found: {cookies_path}. Please login first.")
        return False

    logger.info(f"Uploading to TikTok: {video_path}")
    try:
        # returns list of failed uploads? or boolean?
        # Based on docs: returns failed_videos (list)
        failed = upload_video(
            filenames=[video_path],
            description=description,
            cookies=cookies_path,
            headless=True 
        )
        
        if not failed:
            logger.success("Upload successful!")
            return True
        else:
            logger.error(f"Upload failed for: {failed}")
            return False
            
    except Exception as e:
        logger.error(f"TikTok upload error: {e}")
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?", help="Video file path")
    parser.add_argument("--desc", default="", help="Description")
    parser.add_argument("--login", action="store_true", help="Login mode")
    args = parser.parse_args()
    
    if args.login:
        login()
    elif args.video:
        upload(args.video, args.desc)
    else:
        logger.error("Video file required if not logging in")
