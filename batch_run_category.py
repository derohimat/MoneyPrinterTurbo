import sys
import os
import re
import uuid
import sys
import argparse
from loguru import logger

# Add root dir
root_dir = os.path.dirname(os.path.realpath(__file__))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from app.services import task as tm
from app.config import config
from app.utils import safety_filters

# VOICES
VOICE_NAME = "en-US-ChristopherNeural"

def run_batch(json_file):
    # Enable debug logging
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    
    # Read topics from file
    import json
    try:
        with open(json_file, 'r') as f:
            topics = json.load(f)
    except FileNotFoundError:
        logger.error(f"File not found: {json_file}")
        return

    logger.info(f"Loaded {len(topics)} topics from {json_file}")

    for i, topic in enumerate(topics):
        logger.info(f"Processing topic {i+1}/{len(topics)}: {topic}")
        
        task_id = str(uuid.uuid4())

        # Clean subject for AI generation
        # Input format: Category_01_Title_With_Underscores
        # Output format: Category: Title With Underscores
        
        clean_subject = topic
        category = "General" # Default category
        
        # Match pattern: Category_Number_Title
        match = re.match(r'^([^_]+)_\d+_(.+)$', topic)
        if match:
            category, title_part = match.groups()
            # Replace remaining underscores in the title part with spaces
            title_clean = title_part.replace('_', ' ')
            clean_subject = f"{category} - {title_clean}"
        else:
            # Fallback: just replace underscores
            # Try to guess category if possible, or just use first word
            parts = topic.split('_')
            if len(parts) > 1:
                category = parts[0]
            
            clean_subject = topic.replace('_', ' ')
            title_clean = clean_subject # For search term extraction fallback
            
        logger.info(f"  > Subject for AI: {clean_subject}")
        
        # Extract search terms from title
        # For "IslamicPlaces_01_Kabah_Mekkah_...", extract "Kabah Mekkah"
        search_terms = []
        if "IslamicPlaces" in category:
            # Take the first 2-3 words of the clean title as the main search term
            # Example: "Kabah Mekkah Sejarah..." -> "Kabah Mekkah"
            words = title_clean.split()
            if len(words) >= 2:
                main_term = f"{words[0]} {words[1]}"
                search_terms.append(main_term)
                search_terms.append(f"{main_term} cinematic")
                search_terms.append(f"{main_term} drone")
            else:
                search_terms.append(title_clean)
            
            # Add general terms
            search_terms.append("Islamic Architecture")
            search_terms.append("Historical Place")
            
            logger.info(f"  > Forced Search Terms: {search_terms}")
            
            logger.info(f"  > Forced Search Terms: {search_terms}")
            
        # Define negative terms using centralized safety logic
        negative_terms = safety_filters.get_negative_terms(clean_subject, category_hint=category)
        logger.info(f"  > Negative Terms (from safety_filters): {negative_terms}")

        # Check if output file already exists to skip re-generation
        safe_name = re.sub(r'[\\/*?:"<>|]', "", topic)
        
        # Create category-specific directory
        # e.g. batch_outputs/IslamicPlaces/
        batch_dir = os.path.join(root_dir, "batch_outputs", category)
        os.makedirs(batch_dir, exist_ok=True)
        
        final_output_path = os.path.join(batch_dir, f"{safe_name}.mp4")
        
        if os.path.exists(final_output_path):
            logger.warning(f"Skipping {topic} (File already exists: {final_output_path})")
            continue

        # Configure Video Params
        params = VideoParams(
            video_subject=clean_subject,
            video_script="",  # Let AI generate script
            video_terms=search_terms if search_terms else None, # Pass explicit terms if available
            video_negative_terms=negative_terms if negative_terms else None, # Pass negative terms
            video_aspect=VideoAspect.portrait.value, # 9:16
            voice_name=VOICE_NAME,
            video_source="pexels",
            video_concat_mode=VideoConcatMode.random,
            subtitle_enabled=True,
            font_size=60,
            stroke_width=1.5
        )

        max_retries = 3
        retry_delays = [10, 30, 60]  # seconds between retries
        
        for attempt in range(1, max_retries + 1):
            try:
                task_id = str(uuid.uuid4())  # Fresh task_id per attempt
                # Start generation
                logger.info(f"  > Attempt {attempt}/{max_retries}")
                result = tm.start(task_id, params)
                
                # If successful, rename output file
                if result and "videos" in result:
                    output_file = result["videos"][0]
                    if os.path.exists(output_file):
                        os.rename(output_file, final_output_path)
                        logger.success(f"Video saved to: {final_output_path}")
                    break  # Success, exit retry loop
                else:
                    logger.error(f"Failed to generate video for: {topic} (attempt {attempt})")
                    if attempt < max_retries:
                        import time
                        delay = retry_delays[attempt - 1]
                        logger.warning(f"Retrying in {delay}s...")
                        time.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Error processing {topic} (attempt {attempt}): {str(e)}")
                if attempt < max_retries:
                    import time
                    delay = retry_delays[attempt - 1]
                    logger.warning(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed for: {topic}")
                continue

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Batch create videos from a JSON file.')
    parser.add_argument('json_file', help='Path to the JSON file containing topics')
    args = parser.parse_args()
    
    run_batch(args.json_file)
