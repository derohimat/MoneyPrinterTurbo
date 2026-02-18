
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils
from app.utils import utils
from app.utils import video_scorer
from app.utils import rate_limiter

requested_count = 0


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global requested_count
    requested_count += 1
    return api_keys[requested_count % len(api_keys)]



GENERIC_TERMS = {
    "background", "view", "scene", "video", "clip", "stock", "footage", 
    "hd", "4k", "sky", "blue", "white", "black", "green", "red",
    "nature", "landscape", "people", "happy", "person", "man", "woman",
    "girl", "boy", "day", "night", "light", "dark", "slow", "motion"
}

def validate_video_metadata(video_tags: List[str], video_title: str, search_term: str) -> Tuple[bool, str]:
    """
    Validates if the video metadata matches the search term strictly.
    Returns (is_valid, reason)
    """
    search_tokens = [t.strip().lower() for t in search_term.split()]
    # Filter out generic terms to find 'specific' keywords
    specific_tokens = [t for t in search_tokens if t not in GENERIC_TERMS and len(t) > 2]
    
    # If all tokens are generic (e.g., "Blue Sky"), fall back to using all tokens
    validation_tokens = specific_tokens if specific_tokens else search_tokens
    
    # Combine tags and title for checking
    # Note: validation_tokens are AND or OR?
    # If search is "Ramadan Mosque", we probably want "Ramadan" OR "Mosque" as a hit, 
    # but preferably "Ramadan".
    # Since we filtered generics, "Ramadan Nature" -> "Ramadan".
    # We require AT LEAST ONE specific token to be present.
    
    found_match = False
    matched_token = ""
    
    # Check title/slug
    title_lower = video_title.lower()
    for token in validation_tokens:
        if token in title_lower:
            found_match = True
            matched_token = token
            break
            
    if not found_match:
        # Check tags (exact or partial match?)
        # Tags in Pexels are usually single words or phrases.
        for tag in video_tags:
            tag_lower = tag.lower()
            for token in validation_tokens:
                if token in tag_lower:
                    found_match = True
                    matched_token = token
                    break
            if found_match:
                break
                
    if found_match:
        return True, f"Matched '{matched_token}'"
    else:
        return False, f"Missing specific keywords: {validation_tokens}"


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    negative_terms: List[str] = None,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    rate_limiter.pexels.wait()

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=False,
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            # check for negative terms
            if negative_terms:
                should_skip = False
                # Pexels video object has 'url' which often contains the title/slug
                # e.g. https://www.pexels.com/video/a-person-praying-12345/
                video_url_slug = v.get("url", "").lower()
                # Check tags if available (Pexels API response usually contains tags in 'tags' list or just keywords in url)
                # Pexels 'tags' field is list of strings
                video_tags = [t.lower() for t in v.get("tags", [])]
                
                for term in negative_terms:
                    term = term.lower()
                    if term in video_url_slug:
                        should_skip = True
                        break
                    for tag in video_tags:
                        if term in tag:
                            should_skip = True
                            break
                    if should_skip:
                        break
                
                if should_skip:
                    logger.warning(f"Skipping video due to negative term: {v.get('url')}")
                    continue

                # STRICT METADATA VALIDATION
                # Extract subject/keywords
                video_url_slug = v.get("url", "").lower()
                video_tags = [t.lower() for t in v.get("tags", [])]
                
                is_valid, reason = validate_video_metadata(video_tags, video_url_slug, search_term)
                if not is_valid:
                    logger.warning(f"Skipping video due to metadata mismatch: {v.get('url')} | Reason: {reason}")
                    continue

            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    negative_terms: List[str] = None,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    rate_limiter.pixabay.wait()

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=False, timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            # check for negative terms
            if negative_terms:
                should_skip = False
                # Pixabay 'tags' is a comma-separated string
                video_tags = v.get("tags", "").lower()
                video_page_url = v.get("pageURL", "").lower()

                for term in negative_terms:
                    term = term.lower()
                    if term in video_tags or term in video_page_url:
                        should_skip = True
                        break
                
                if should_skip:
                    logger.warning(f"Skipping video due to negative term: {v.get('pageURL')}")
                    continue

                # STRICT METADATA VALIDATION
                video_title = v.get("pageURL", "").lower()
                video_tags = [t.strip().lower() for t in v.get("tags", "").split(",")]
                
                is_valid, reason = validate_video_metadata(video_tags, video_title, search_term)
                if not is_valid:
                    logger.warning(f"Skipping video due to metadata mismatch: {v.get('pageURL')} | Reason: {reason}")
                    continue

            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=False,
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            clip.close()
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    negative_terms: List[str] = None,
) -> List[str]:
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0

    # Determine primary and fallback search functions
    if source == "pixabay":
        search_sources = [("pixabay", search_videos_pixabay), ("pexels", search_videos_pexels)]
    else:
        search_sources = [("pexels", search_videos_pexels), ("pixabay", search_videos_pixabay)]

    for source_name, search_videos in search_sources:
        for search_term in search_terms:
            video_items = search_videos(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
                negative_terms=negative_terms,
            )
            logger.info(f"found {len(video_items)} videos for '{search_term}' from {source_name}")

            for item in video_items:
                if item.url not in valid_video_urls:
                    valid_video_items.append(item)
                    valid_video_urls.append(item.url)
                    found_duration += item.duration

        # Check if we have enough footage from primary source
        if found_duration >= audio_duration:
            logger.info(f"sufficient footage found from {source_name} ({found_duration:.0f}s >= {audio_duration:.0f}s), skipping fallback")
            break
        else:
            logger.warning(f"insufficient footage from {source_name} ({found_duration:.0f}s < {audio_duration:.0f}s), trying next source...")

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    
    # Parallel download using ThreadPoolExecutor
    max_workers = 5  # Download up to 5 videos simultaneously
    logger.info(f"Starting parallel download with {max_workers} workers for {len(valid_video_items)} candidate videos")
    
    # Submit all download tasks
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Map future -> item for tracking
        future_to_item = {}
        for item in valid_video_items:
            future = executor.submit(save_video, video_url=item.url, save_dir=material_directory)
            future_to_item[future] = item
        
        # Process completed downloads as they finish
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                saved_video_path = future.result()
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    seconds = min(max_clip_duration, item.duration)
                    total_duration += seconds
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, enough material collected"
                        )
                        # Cancel remaining futures
                        for f in future_to_item:
                            f.cancel()
                        break
            except Exception as e:
                logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")

    logger.success(f"downloaded {len(video_paths)} videos (parallel mode)")

    # Apply quality scoring filter
    if video_paths:
        video_paths = video_scorer.filter_videos_by_quality(video_paths, min_score=40)

    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
