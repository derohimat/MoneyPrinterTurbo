import json
import os
from loguru import logger
from app.services import llm


def generate_youtube_metadata(video_subject: str, video_script: str, output_dir: str) -> dict:
    """
    Generate YouTube-optimized metadata (title, description, tags, hashtags) using LLM.
    Saves result as a .txt file alongside the video.
    """
    prompt = f"""You are a YouTube SEO expert. Generate optimized metadata for a YouTube Shorts video.

Video Topic: {video_subject}

Video Script:
{video_script[:500]}

Generate the following in JSON format:
{{
    "title": "An engaging YouTube title (max 100 chars, include keywords)",
    "description": "A compelling description (150-300 words, include keywords, call to action, and 5 relevant hashtags at the end)",
    "tags": ["tag1", "tag2", "tag3", "...up to 15 relevant tags"],
    "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"]
}}

Rules:
- Title must be catchy and click-worthy but NOT clickbait
- Description should summarize the video, include a call to action (like, subscribe)
- Tags should be relevant search terms people would use to find this video
- All content must be in English
- Keep it family-friendly / kids-safe
- Return ONLY the JSON, no other text
"""

    try:
        response = llm.generate_script(
            video_subject=prompt,
            language="en",
            paragraph_number=1,
        )
        
        if not response:
            logger.error("LLM returned empty response for metadata generation")
            return {}

        # Try to parse JSON from response
        # Strip markdown code blocks if present
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        metadata = json.loads(cleaned)
        
        # Save metadata file
        metadata_path = os.path.join(output_dir, "metadata.txt")
        with open(metadata_path, "w", encoding="utf-8") as f:
            f.write(f"TITLE:\n{metadata.get('title', '')}\n\n")
            f.write(f"DESCRIPTION:\n{metadata.get('description', '')}\n\n")
            f.write(f"TAGS:\n{', '.join(metadata.get('tags', []))}\n\n")
            f.write(f"HASHTAGS:\n{' '.join(metadata.get('hashtags', []))}\n")

        # Also save raw JSON
        json_path = os.path.join(output_dir, "metadata.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.success(f"YouTube metadata saved to: {metadata_path}")
        return metadata

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse metadata JSON: {str(e)}")
        # Save raw response as fallback
        fallback_path = os.path.join(output_dir, "metadata_raw.txt")
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(response)
        return {}
    except Exception as e:
        logger.error(f"Failed to generate YouTube metadata: {str(e)}")
        return {}
