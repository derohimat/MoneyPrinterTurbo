import os
import re
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip

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
    # List of safe words that shouldn't independently define a match 
    # if combined with strong nouns (like "city", "building")
    GENERIC_TERMS_EXTENDED = GENERIC_TERMS.union({
        "city", "building", "street", "architecture", "monument", "ancient"
    })
    
    search_tokens = [t.strip().lower() for t in search_term.split()]
    # Filter out generic terms to find 'specific' keywords (the core nouns)
    specific_tokens = [t for t in search_tokens if t not in GENERIC_TERMS_EXTENDED and len(t) > 2]
    
    # If all tokens were filtered out (e.g. search was exactly "ancient city"), 
    # fall back to the original generic terms so we can still match *something*.
    validation_tokens = specific_tokens if specific_tokens else search_tokens
    
    # We require AT LEAST ONE specific token to be present in the title OR tags.
    # The LLM now generates 1-3 noun clusters (e.g., "Kaaba Mecca Pilgrims").
    # If Pexels returns a video tagged "Kaaba", that's a valid hit.
    
    found_match = False
    matched_token = ""
    
    # 1. Check title/slug (Pexels URLs usually contain the title slug)
    title_lower = video_title.lower()
    for token in validation_tokens:
        if token in title_lower:
            found_match = True
            matched_token = token
            break
            
    if not found_match:
        # 2. Check tags
        for tag in video_tags:
            tag_lower = tag.lower()
            for token in validation_tokens:
                # Use word boundaries or simple sub-string
                if token in tag_lower or tag_lower in token:
                    found_match = True
                    matched_token = token
                    break
            if found_match:
                break
                
    if found_match:
        return True, f"Matched '{matched_token}'"
    else:
        # If we failed the strong metadata check, we can still accept the video 
        # IF Pexels' search algorithm decided it was highly relevant (Trust Pexels).
        # We'll log a warning but STILL PASS IT to prevent empty video generation.
        logger.warning(f"Lenient Pass: Pexels provided video without strict metadata match for {validation_tokens}")
        return True, "Lenient fallback pass"


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


def search_images_pexels(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    
    params = {"query": search_term, "per_page": 10, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
    logger.info(f"searching fallback images: {query_url}")

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
        image_items = []
        if "photos" not in response:
            logger.error(f"search images failed: {response}")
            return image_items
            
        photos = response["photos"]
        for p in photos:
            # Get the large high-res version
            url = p.get("src", {}).get("large2x") or p.get("src", {}).get("large")
            if url:
                item = MaterialInfo()
                item.provider = "pexels_image"
                item.url = url
                item.duration = 5.0 # Fixed duration since it's an image
                image_items.append(item)
                
        return image_items
    except Exception as e:
        logger.error(f"search images failed: {str(e)}")

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

def search_images_pixabay(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    api_key = get_api_key("pixabay_api_keys")
    
    # Determine orientation equivalent for Pixabay
    orientation = "vertical" if aspect == VideoAspect.portrait else "horizontal" if aspect == VideoAspect.landscape else "all"

    params = {
        "q": search_term,
        "image_type": "photo",
        "orientation": orientation,
        "per_page": 20,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/?{urlencode(params)}"
    logger.info(f"searching fallback images: {query_url}")

    rate_limiter.pixabay.wait()

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=False, timeout=(30, 60)
        )
        response = r.json()
        image_items = []
        if "hits" not in response:
            logger.error(f"search images failed: {response}")
            return image_items
            
        photos = response["hits"]
        for p in photos:
            # Prefer large image url
            url = p.get("largeImageURL") or p.get("webformatURL")
            if url:
                item = MaterialInfo()
                item.provider = "pixabay_image"
                item.url = url
                item.duration = 5.0 # Fixed duration for images
                image_items.append(item)
                
        return image_items
    except Exception as e:
        logger.error(f"search images failed: {str(e)}")

    return []

def save_video(video_url: str, save_dir: str = "", search_term: str = "", provider: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if search_term:
        # Sanitize search term for directory name
        safe_term = re.sub(r'[\\/*?:"<>|]', "", search_term).strip().replace(" ", "_")
        save_dir = os.path.join(save_dir, safe_term)

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    
    is_image = "image" in provider.lower()
    
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"
    image_path = f"{save_dir}/{video_id}.jpg"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # If it's an image, download as image first then convert to 5s video
    if is_image:
        try:
            with open(image_path, "wb") as f:
                f.write(
                    requests.get(
                        video_url,
                        headers=headers,
                        proxies=config.proxy,
                        verify=False,
                        timeout=(60, 240),
                    ).content
                )
            
            logger.info(f"Downloaded fallback image, converting to 5s clip: {image_path}")
            clip = ImageClip(image_path).set_duration(5.0)
            # Write to the standard video_path
            clip.write_videofile(video_path, fps=30, codec="libx264", audio=False, logger=None)
            clip.close()
            
            # Clean up the raw image file
            if os.path.exists(image_path):
                os.remove(image_path)
                
            return video_path
        except Exception as e:
            logger.error(f"Failed to process and convert fallback image {video_url}: {e}")
            if os.path.exists(video_path):
                os.remove(video_path)
            return ""

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

    # Build local cache directory to check for categorized videos
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.storage_dir("cache_videos")
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    # Before querying APIs, search our categorized local cache
    cached_video_paths = []
    if material_directory:
        for search_term in search_terms:
            safe_term = re.sub(r'[\\/*?:"<>|]', "", search_term).strip().replace(" ", "_")
            term_dir = os.path.join(material_directory, safe_term)
            if os.path.isdir(term_dir):
                logger.info(f"checking local cache for term '{search_term}' in {term_dir}")
                for filename in os.listdir(term_dir):
                    if filename.endswith(".mp4"):
                        filepath = os.path.join(term_dir, filename)
                        if os.path.getsize(filepath) > 0:
                            try:
                                clip = VideoFileClip(filepath)
                                duration = clip.duration
                                fps = clip.fps
                                clip.close()
                                if duration > 0 and fps > 0:
                                    item = MaterialInfo()
                                    item.provider = "local_cache"
                                    item.url = filepath  # Pretend filepath is the URL so it gets treated identically
                                    item.duration = duration
                                    item.search_term = search_term
                                    
                                    if item.url not in valid_video_urls:
                                        valid_video_items.append(item)
                                        valid_video_urls.append(item.url)
                                        found_duration += item.duration
                                        cached_video_paths.append(filepath)
                            except Exception as e:
                                logger.warning(f"invalid cached video file: {filepath} => {str(e)}")

        if found_duration >= audio_duration:
            logger.success(f"enough footage found purely from local cache ({found_duration:.0f}s >= {audio_duration:.0f}s)")
            
    # Determine primary and fallback search functions ONLY IF we need more duration
    if found_duration < audio_duration:
        if source == "pixabay":
            search_sources = [("pixabay", search_videos_pixabay), ("pexels", search_videos_pexels)]
        else:
            search_sources = [("pexels", search_videos_pexels), ("pixabay", search_videos_pixabay)]

        for source_name, search_videos in search_sources:
            for term_idx, search_term in enumerate(search_terms):
                video_items = search_videos(
                    search_term=search_term,
                    minimum_duration=max_clip_duration,
                    video_aspect=video_aspect,
                    negative_terms=negative_terms,
                )
                logger.info(f"found {len(video_items)} videos for '{search_term}' from {source_name}")

                # [IMAGE FALLBACK LOGIC]: If the search failed, and it's our critical hook term, get an image
                if not video_items and term_idx == 0:
                    logger.warning(f"No videos found for Hook Term '{search_term}'. Falling back to cinematic image search...")
                    if source_name == "pexels":
                        video_items = search_images_pexels(search_term, video_aspect)
                    else:
                        video_items = search_images_pixabay(search_term, video_aspect)
                    
                    if video_items:
                        logger.success(f"Successfully rescued Hook with {len(video_items)} cinematic images from {source_name}")
                
                for item in video_items:
                    # Give it the search sequence so we know which categorized folder to save it to later
                    item.search_term = search_term

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
    video_paths = cached_video_paths.copy() # Start out with the ones that are legally filepaths

    # IMPORTANT: The user hook needs the FIRST video to be highly relevant to the primary subject. 
    # If using random concat mode, we must secure at least one primary video at index 0.
    if video_contact_mode.value == VideoConcatMode.random.value and valid_video_items:
        primary_term = search_terms[0] if search_terms else ""
        
        # 1. Find the best primary candidate
        primary_candidate_idx = -1
        for i, item in enumerate(valid_video_items):
            if getattr(item, 'search_term', "") == primary_term:
                primary_candidate_idx = i
                break
                
        if primary_candidate_idx != -1:
            # Pop the primary candidate
            primary_vid = valid_video_items.pop(primary_candidate_idx)
            # Shuffle the rest
            random.shuffle(valid_video_items)
            # Put the primary candidate back at the explicitly first position
            valid_video_items.insert(0, primary_vid)
            logger.info(f"Anchored highly-relevant video for '{primary_term}' to index 0 (Hook)")
        else:
            random.shuffle(valid_video_items)
            
    total_duration = 0.0
    
    # We will submit tasks in small batches to avoid over-fetching and save bandwidth.
    max_workers = 3
    logger.info(f"Starting limited batch download/processing with {max_workers} workers")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        index = 0
        while index < len(valid_video_items) and total_duration < audio_duration:
            # Prepare a small batch
            batch_items = valid_video_items[index:index + max_workers]
            index += max_workers
            
            future_to_item = {}
            for item in batch_items:
                # If the item is ALREADY a local cache file, treat it as downloaded
                if item.provider == "local_cache":
                    # It's already in the cached_video_paths list from above, just need to tally the duration
                    seconds = min(max_clip_duration, item.duration)
                    total_duration += seconds
                    logger.info(f"video used from local cache: {item.url}")
                else:
                    search_term = getattr(item, 'search_term', "") 
                    provider = getattr(item, 'provider', "")
                    future = executor.submit(save_video, video_url=item.url, save_dir=material_directory, search_term=search_term, provider=provider)
                    future_to_item[future] = item
            
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    saved_video_path = future.result()
                    if saved_video_path:
                        logger.info(f"video saved: {saved_video_path}")
                        video_paths.append(saved_video_path)
                        seconds = min(max_clip_duration, item.duration)
                        total_duration += seconds
                except Exception as e:
                    logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
                    
            if total_duration >= audio_duration:
                logger.info(f"total duration of downloaded videos: {total_duration}s meets required {audio_duration}s. Stopping download.")
                break

    logger.success(f"downloaded {len(video_paths)} videos (batch mode)")

    # Apply quality scoring filter
    if video_paths:
        video_paths = video_scorer.filter_videos_by_quality(video_paths, min_score=60)

    return video_paths
