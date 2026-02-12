"""
YouTube Auto-Upload — Upload generated videos to YouTube with metadata.

Prerequisites:
1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable the YouTube Data API v3
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download the client_secret.json and place it in the project root
5. Install: pip install google-auth google-auth-oauthlib google-api-python-client

First run will open a browser for OAuth authorization.
Subsequent runs use the saved token (youtube_token.json).
"""

import json
import os
import time
from loguru import logger

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False
    logger.warning("YouTube API libraries not installed. Run: pip install google-auth google-auth-oauthlib google-api-python-client")


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "youtube_token.json"

# YouTube category IDs
CATEGORY_MAP = {
    "IslamicPlaces": "19",    # Travel & Events
    "Stoik": "27",            # Education
    "Psikologi": "27",        # Education
    "Misteri": "24",          # Entertainment
    "Fakta": "27",            # Education
    "Kesehatan": "26",        # Howto & Style
    "Horor": "24",            # Entertainment
    "Keuangan": "27",         # Education
    "General": "22",          # People & Blogs
}


def get_authenticated_service(client_secret_path: str = "", token_path: str = ""):
    """
    Authenticate with YouTube API using OAuth 2.0.
    Returns an authenticated YouTube service object.
    """
    if not YOUTUBE_API_AVAILABLE:
        logger.error("YouTube API libraries not installed")
        return None
    
    if not client_secret_path:
        client_secret_path = CLIENT_SECRET_FILE
    if not token_path:
        token_path = TOKEN_FILE
    
    creds = None
    
    # Load existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # Refresh or get new token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                logger.error(f"Client secret file not found: {client_secret_path}")
                logger.info("Download it from Google Cloud Console > APIs & Services > Credentials")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save token for future use
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info(f"Token saved to: {token_path}")
    
    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str = "",
    description: str = "",
    tags: list = None,
    category: str = "General",
    privacy: str = "private",
    metadata_json_path: str = "",
) -> dict:
    """
    Upload a video to YouTube.
    
    Args:
        video_path: Path to the video file
        title: Video title (max 100 chars)
        description: Video description
        tags: List of tags
        category: Category name (mapped to YouTube category ID)
        privacy: "private", "unlisted", or "public"
        metadata_json_path: Path to metadata.json (overrides title/desc/tags)
    
    Returns:
        dict with upload result info
    """
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return {"status": "error", "message": "File not found"}
    
    # Load metadata from JSON if available
    if metadata_json_path and os.path.exists(metadata_json_path):
        try:
            with open(metadata_json_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            title = title or metadata.get("title", "")
            description = description or metadata.get("description", "")
            tags = tags or metadata.get("tags", [])
            logger.info(f"Loaded metadata from: {metadata_json_path}")
        except Exception as e:
            logger.warning(f"Failed to load metadata: {str(e)}")
    
    # Defaults
    if not title:
        title = os.path.splitext(os.path.basename(video_path))[0][:100]
    if not description:
        description = title
    if not tags:
        tags = []
    
    # Get YouTube service
    youtube = get_authenticated_service()
    if not youtube:
        return {"status": "error", "message": "Authentication failed"}
    
    # Get YouTube category ID
    category_id = CATEGORY_MAP.get(category, "22")
    
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    
    logger.info(f"Uploading to YouTube: {title}")
    logger.info(f"  Privacy: {privacy}")
    logger.info(f"  Category: {category} (ID: {category_id})")
    
    try:
        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"  Upload progress: {int(status.progress() * 100)}%")
        
        video_id = response.get("id", "")
        video_url = f"https://youtube.com/watch?v={video_id}" if video_id else ""
        
        logger.success(f"Upload complete! Video ID: {video_id}")
        logger.success(f"URL: {video_url}")
        
        return {
            "status": "success",
            "video_id": video_id,
            "url": video_url,
            "title": title,
        }
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return {"status": "error", "message": str(e)}


def batch_upload(
    video_dir: str,
    category: str = "General",
    privacy: str = "private",
    delay_seconds: int = 60,
):
    """
    Upload all videos in a directory to YouTube.
    
    Args:
        video_dir: Directory containing .mp4 files
        category: Category for all videos
        privacy: Privacy status for all videos
        delay_seconds: Delay between uploads (to avoid rate limits)
    """
    if not os.path.isdir(video_dir):
        logger.error(f"Directory not found: {video_dir}")
        return
    
    import glob
    video_files = sorted(glob.glob(os.path.join(video_dir, "*.mp4")))
    
    if not video_files:
        logger.warning(f"No .mp4 files found in: {video_dir}")
        return
    
    logger.info(f"Found {len(video_files)} videos to upload from: {video_dir}")
    
    results = []
    for i, video_file in enumerate(video_files, 1):
        logger.info(f"\n--- Uploading {i}/{len(video_files)} ---")
        
        # Check for metadata.json alongside the video
        base_name = os.path.splitext(video_file)[0]
        metadata_path = os.path.join(os.path.dirname(video_file), "metadata.json")
        
        result = upload_video(
            video_path=video_file,
            category=category,
            privacy=privacy,
            metadata_json_path=metadata_path,
        )
        results.append(result)
        
        # Delay between uploads
        if i < len(video_files):
            logger.info(f"Waiting {delay_seconds}s before next upload...")
            time.sleep(delay_seconds)
    
    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] != "success")
    logger.info(f"\n=== Upload Summary ===")
    logger.info(f"  ✅ Success: {success}")
    logger.info(f"  ❌ Failed: {failed}")
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Upload videos to YouTube.')
    parser.add_argument('path', help='Video file or directory to upload')
    parser.add_argument('--category', default="General", help='Category name')
    parser.add_argument('--privacy', default="private", choices=["private", "unlisted", "public"],
                        help='Privacy status')
    parser.add_argument('--delay', type=int, default=60, help='Delay between uploads (seconds)')
    args = parser.parse_args()
    
    if os.path.isdir(args.path):
        batch_upload(args.path, category=args.category, privacy=args.privacy, delay_seconds=args.delay)
    else:
        upload_video(args.path, category=args.category, privacy=args.privacy)
