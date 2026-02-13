import argparse
import os
import subprocess
import sys
from loguru import logger

# Configuration
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# Python environments
VENV_PYTHON = os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe")
VENV_UPLOAD_PYTHON = os.path.join(ROOT_DIR, "venv-upload", "Scripts", "python.exe")

def run_command(cmd, env=None):
    try:
        subprocess.run(cmd, check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e}")
        return False

def upload_tiktok(video, desc, login_mode=False):
    """Run TikTok uploader via main venv (Python 3.10)"""
    script = os.path.join(ROOT_DIR, "app/utils/tiktok_upload.py")
    
    if not os.path.exists(VENV_PYTHON):
        logger.error(f"Main venv not found at {VENV_PYTHON}. Please install dependencies first.")
        return False
        
    cmd = [VENV_PYTHON, script]
    if video:
        cmd.append(video)
        
    if desc:
        cmd.extend(["--desc", desc])
    if login_mode:
        cmd.append("--login")
        
    logger.info(f"Launching TikTok uploader: {' '.join(cmd)}")
    return run_command(cmd)

def upload_instagram(video, user, password, caption):
    """Run Instagram uploader via isolated venv-upload (Python 3.10 + instagrapi)"""
    script = os.path.join(ROOT_DIR, "app/utils/instagram_upload.py")
    
    if not os.path.exists(VENV_UPLOAD_PYTHON):
        logger.error(f"Upload venv not found at {VENV_UPLOAD_PYTHON}. Preparing environment...")
        # Fallback logic? Or strict error?
        return False
        
    cmd = [VENV_UPLOAD_PYTHON, script, "--video", video, "--user", user, "--passw", password]
    if caption:
        cmd.extend(["--caption", caption])
        
    logger.info(f"Launching Instagram uploader: {' '.join(cmd)}")
    # Pass environment variables/clean env if needed
    return run_command(cmd)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Platform Video Uploader")
    subparsers = parser.add_subparsers(dest="platform", help="Platform to upload to")
    
    # TikTok
    tiktok_parser = subparsers.add_parser("tiktok", help="Upload to TikTok")
    tiktok_parser.add_argument("video", nargs="?", help="Video file path (Optional if --login)")
    tiktok_parser.add_argument("--desc", default="", help="Video description")
    tiktok_parser.add_argument("--login", action="store_true", help="Login mode only")

    # Instagram
    insta_parser = subparsers.add_parser("instagram", help="Upload to Instagram Reels")
    insta_parser.add_argument("video", help="Video file path")
    insta_parser.add_argument("--user", required=True, help="Instagram Username")
    insta_parser.add_argument("--passw", required=True, help="Instagram Password")
    insta_parser.add_argument("--caption", default="", help="Caption")

    args = parser.parse_args()
    
    if args.platform == "tiktok":
        if args.login:
            upload_tiktok(None, args.desc, login_mode=True)
        else:
            if not args.video:
                logger.error("Video file is required for upload mode!")
                sys.exit(1)
            upload_tiktok(args.video, args.desc)
            
    elif args.platform == "instagram":
        upload_instagram(args.video, args.user, args.passw, args.caption)
    else:
        parser.print_help()
