import hashlib
import json
import logging
import re
import time
import requests
from typing import List

import g4f
from loguru import logger
from openai import AzureOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from app.config import config
from app.utils import llm_cache

_max_retries = 5


def _generate_response(prompt: str) -> str:
    try:
        content = ""
        llm_provider = config.app.get("llm_provider", "openai")
        logger.info(f"llm provider: {llm_provider}")
        if llm_provider == "g4f":
            model_name = config.app.get("g4f_model_name", "")
            if not model_name:
                model_name = "gpt-3.5-turbo-16k-0613"
            content = g4f.ChatCompletion.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
            )
        else:
            api_version = ""  # for azure
            if llm_provider == "moonshot":
                api_key = config.app.get("moonshot_api_key")
                model_name = config.app.get("moonshot_model_name")
                base_url = "https://api.moonshot.cn/v1"
            elif llm_provider == "ollama":
                # api_key = config.app.get("openai_api_key")
                api_key = "ollama"  # any string works but you are required to have one
                model_name = config.app.get("ollama_model_name")
                base_url = config.app.get("ollama_base_url", "")
                if not base_url:
                    base_url = "http://localhost:11434/v1"
            elif llm_provider == "openai":
                api_key = config.app.get("openai_api_key")
                model_name = config.app.get("openai_model_name")
                base_url = config.app.get("openai_base_url", "")
                if not base_url:
                    base_url = "https://api.openai.com/v1"
            elif llm_provider == "oneapi":
                api_key = config.app.get("oneapi_api_key")
                model_name = config.app.get("oneapi_model_name")
                base_url = config.app.get("oneapi_base_url", "")
            elif llm_provider == "azure":
                api_key = config.app.get("azure_api_key")
                model_name = config.app.get("azure_model_name")
                base_url = config.app.get("azure_base_url", "")
                api_version = config.app.get("azure_api_version", "2024-02-15-preview")
            elif llm_provider == "gemini":
                api_key = config.app.get("gemini_api_key")
                model_name = config.app.get("gemini_model_name")
                base_url = config.app.get("gemini_base_url", "")
            elif llm_provider == "qwen":
                api_key = config.app.get("qwen_api_key")
                model_name = config.app.get("qwen_model_name")
                base_url = "***"
            elif llm_provider == "cloudflare":
                api_key = config.app.get("cloudflare_api_key")
                model_name = config.app.get("cloudflare_model_name")
                account_id = config.app.get("cloudflare_account_id")
                base_url = "***"
            elif llm_provider == "deepseek":
                api_key = config.app.get("deepseek_api_key")
                model_name = config.app.get("deepseek_model_name")
                base_url = config.app.get("deepseek_base_url")
                if not base_url:
                    base_url = "https://api.deepseek.com"
            elif llm_provider == "sumopod":
                api_key = config.app.get("sumopod_api_key")
                model_name = config.app.get("sumopod_model_name")
                base_url = config.app.get("sumopod_base_url", "")
                if not base_url:
                    base_url = "https://ai.sumopod.com/v1"
            elif llm_provider == "modelscope":
                api_key = config.app.get("modelscope_api_key")
                model_name = config.app.get("modelscope_model_name")
                base_url = config.app.get("modelscope_base_url")
                if not base_url:
                    base_url = "https://api-inference.modelscope.cn/v1/"
            elif llm_provider == "ernie":
                api_key = config.app.get("ernie_api_key")
                secret_key = config.app.get("ernie_secret_key")
                base_url = config.app.get("ernie_base_url")
                model_name = "***"
                if not secret_key:
                    raise ValueError(
                        f"{llm_provider}: secret_key is not set, please set it in the config.toml file."
                    )
            elif llm_provider == "pollinations":
                try:
                    base_url = config.app.get("pollinations_base_url", "")
                    if not base_url:
                        base_url = "https://text.pollinations.ai/openai"
                    model_name = config.app.get("pollinations_model_name", "openai-fast")
                   
                    # Prepare the payload
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "seed": 101  # Optional but helps with reproducibility
                    }
                    
                    # Optional parameters if configured
                    if config.app.get("pollinations_private"):
                        payload["private"] = True
                    if config.app.get("pollinations_referrer"):
                        payload["referrer"] = config.app.get("pollinations_referrer")
                    
                    headers = {
                        "Content-Type": "application/json"
                    }
                    
                    # Make the API request
                    response = requests.post(base_url, headers=headers, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    
                    if result and "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return content.replace("\n", "")
                    else:
                        raise Exception(f"[{llm_provider}] returned an invalid response format")
                        
                except requests.exceptions.RequestException as e:
                    raise Exception(f"[{llm_provider}] request failed: {str(e)}")
                except Exception as e:
                    raise Exception(f"[{llm_provider}] error: {str(e)}")

            if llm_provider not in ["pollinations", "ollama"]:  # Skip validation for providers that don't require API key
                if not api_key:
                    raise ValueError(
                        f"{llm_provider}: api_key is not set, please set it in the config.toml file."
                    )
                if not model_name:
                    raise ValueError(
                        f"{llm_provider}: model_name is not set, please set it in the config.toml file."
                    )
                if not base_url and llm_provider not in ["gemini"]:
                    raise ValueError(
                        f"{llm_provider}: base_url is not set, please set it in the config.toml file."
                    )

            if llm_provider == "qwen":
                import dashscope
                from dashscope.api_entities.dashscope_response import GenerationResponse

                dashscope.api_key = api_key
                response = dashscope.Generation.call(
                    model=model_name, messages=[{"role": "user", "content": prompt}]
                )
                if response:
                    if isinstance(response, GenerationResponse):
                        status_code = response.status_code
                        if status_code != 200:
                            raise Exception(
                                f'[{llm_provider}] returned an error response: "{response}"'
                            )

                        content = response["output"]["text"]
                        return content.replace("\n", "")
                    else:
                        raise Exception(
                            f'[{llm_provider}] returned an invalid response: "{response}"'
                        )
                else:
                    raise Exception(f"[{llm_provider}] returned an empty response")

            if llm_provider == "gemini":
                import google.generativeai as genai

                if not base_url:
                    genai.configure(api_key=api_key, transport="rest")
                else:
                    genai.configure(api_key=api_key, transport="rest", client_options={'api_endpoint': base_url})

                generation_config = {
                    "temperature": 0.5,
                    "top_p": 1,
                    "top_k": 1,
                    "max_output_tokens": 2048,
                }

                safety_settings = [
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "BLOCK_ONLY_HIGH",
                    },
                    {
                        "category": "HARM_CATEGORY_HATE_SPEECH",
                        "threshold": "BLOCK_ONLY_HIGH",
                    },
                    {
                        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        "threshold": "BLOCK_ONLY_HIGH",
                    },
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "BLOCK_ONLY_HIGH",
                    },
                ]

                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                )

                try:
                    response = model.generate_content(prompt)
                    candidates = response.candidates
                    generated_text = candidates[0].content.parts[0].text
                except (AttributeError, IndexError) as e:
                    print("Gemini Error:", e)

                return generated_text

            if llm_provider == "cloudflare":
                response = requests.post(
                    f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a friendly assistant",
                            },
                            {"role": "user", "content": prompt},
                        ]
                    },
                )
                result = response.json()
                logger.info(result)
                return result["result"]["response"]

            if llm_provider == "ernie":
                response = requests.post(
                    "https://aip.baidubce.com/oauth/2.0/token", 
                    params={
                        "grant_type": "client_credentials",
                        "client_id": api_key,
                        "client_secret": secret_key,
                    }
                )
                access_token = response.json().get("access_token")
                url = f"{base_url}?access_token={access_token}"

                payload = json.dumps(
                    {
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.5,
                        "top_p": 0.8,
                        "penalty_score": 1,
                        "disable_search": False,
                        "enable_citation": False,
                        "response_format": "text",
                    }
                )
                headers = {"Content-Type": "application/json"}

                response = requests.request(
                    "POST", url, headers=headers, data=payload
                ).json()
                return response.get("result")

            if llm_provider == "azure":
                client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=base_url,
                )

            if llm_provider == "modelscope":
                content = ''
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                )
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    extra_body={"enable_thinking": False},
                    stream=True
                )
                if response:
                    for chunk in response:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            content += delta.content
                    
                    if not content.strip():
                        raise ValueError("Empty content in stream response")
                    
                    return content.replace("\n", "")
                else:
                    raise Exception(f"[{llm_provider}] returned an empty response")

            else:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=60.0,
                )

            response = client.chat.completions.create(
                model=model_name, messages=[{"role": "user", "content": prompt}]
            )
            if response:
                if isinstance(response, ChatCompletion):
                    content = response.choices[0].message.content
                else:
                    raise Exception(
                        f'[{llm_provider}] returned an invalid response: "{response}", please check your network '
                        f"connection and try again."
                    )
            else:
                raise Exception(
                    f"[{llm_provider}] returned an empty response, please check your network connection and try again."
                )

        return content.replace("\n", "")
    except Exception as e:
        return f"Error: {str(e)}"


def generate_viral_topic(category: str = "") -> str:
    """Generate a viral video topic using the LLM."""
    prompt = f"""
# Role: Viral Content Strategist

## Goal:
Generate ONE single specific, viral-worthy short video topic.

## Constraints:
1. Return ONLY the topic text. No quotes, no explanations, no "Here is a topic:".
2. The topic must be catchy, intriguing, and suitable for a short video (Shorts/Reels/TikTok).
3. If a category is provided, the topic must belong to that category.
4. If no category is provided, choose a random popular niche (Mystery, Facts, History, Science, Psychology, Finance, etc.).
5. The topic should be in English.
6. Make it sound like a hook or a title.

## Input:
Category: {category if category else "Random Mixed"}

## Example Outputs:
- The Dark Secret Behind the Mona Lisa's Smile
- Why You Should Never Sleep with Your Phone
- The Man Who Survived Two Nuclear Bombs
- 3 Money Hacks Banks Don't Want You to Know
""".strip()

    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                # Clean up response
                topic = response.strip().strip('"').strip("'")
                # Remove prefixes like "Topic: " or "1. "
                topic = re.sub(r"^(Topic:|Here is a topic:|1\.|-)\s*", "", topic, flags=re.IGNORECASE)
                return topic
        except Exception as e:
            logger.error(f"failed to generate viral topic: {e}")
        
        if i < _max_retries:
            time.sleep(1)
            
    return "The Mystery of Why This Topic Failed to Load"


def generate_script(
    video_subject: str, language: str = "", paragraph_number: int = 1
) -> str:
    # T0-6: Enhanced prompt for high-retention short video scripts
    prompt = f"""
# Role: Viral Short Video Script Generator

## Goals:
Generate an engaging, high-retention script for a short video (30-90 seconds) on the given subject.

## Script Structure:
1. HOOK (first sentence): Start with a bold claim, surprising fact, or provocative question. This must grab attention in under 2 seconds.
2. SETUP (next 2-3 sentences): Build context quickly with short, punchy sentences.
3. ESCALATION (body): Present the main content with increasing intensity. Use rhetorical questions and micro-cliffhangers between paragraphs.
4. PAYOFF (ending): Deliver a satisfying conclusion or surprising twist. End with a thought-provoking statement.

## Pacing Rules:
1. Keep sentences SHORT — maximum 12 words per sentence. 
2. Include at least ONE rhetorical question per paragraph.
3. Use micro-cliffhangers: "But here's what most people don't know..." / "And that's when things got interesting..."
4. Vary sentence length: alternate between very short (3-5 words) and medium (8-12 words) for rhythm.
5. Use power words: "secret", "shocking", "incredible", "unbelievable", "impossible" where natural.

## Constrains:
1. Return the script as a string with the specified number of paragraphs.
2. Do NOT reference this prompt in your response.
3. Get straight to the point — no "welcome to this video" or similar introductions.
4. No markdown formatting, no titles, no headers.
5. Only return raw script content.
6. Do NOT include "voiceover", "narrator" or similar indicators.
7. Never mention the prompt, script structure, or paragraph count.
8. Respond in the same language as the video subject.
9. Use a conversational, energetic tone — as if talking to a friend.
10. IMPORTANT: All content must be safe and appropriate for ALL audiences. No violence, horror, sexual content, drugs, alcohol, profanity, gambling, weapons, or disturbing themes.

# Input:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".strip()
    if language:
        prompt += f"\n- language: {language}"

    final_script = ""
    logger.info(f"subject: {video_subject}")

    # [I2] Check cache first
    cached = llm_cache.get("script", subject=video_subject, language=language, paragraphs=paragraph_number)
    if cached:
        logger.success(f"[LLM Cache] Returning cached script for '{video_subject}'")
        return cached


    def format_response(response):
        # Clean the script
        # Remove asterisks, hashes
        response = response.replace("*", "")
        response = response.replace("#", "")

        # Remove markdown syntax
        response = re.sub(r"\[.*\]", "", response)
        response = re.sub(r"\(.*\)", "", response)

        # Split the script into paragraphs
        paragraphs = response.split("\n\n")

        # Select the specified number of paragraphs
        # selected_paragraphs = paragraphs[:paragraph_number]

        # Join the selected paragraphs into a single string
        return "\n\n".join(paragraphs)

    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                final_script = format_response(response)
            else:
                logging.error("gpt returned an empty response")

            # g4f may return an error message
            if final_script and "当日额度已消耗完" in final_script:
                raise ValueError(final_script)

            if final_script:
                break
        except Exception as e:
            logger.error(f"failed to generate script: {e}")

        if i < _max_retries:
            logger.warning(f"failed to generate video script, trying again... {i + 1}")
            time.sleep(2 * (i + 1))  # exponential backoff
    if "Error: " in final_script:
        logger.error(f"failed to generate video script: {final_script}")
        return None
    else:
        logger.success(f"completed: \n{final_script}")
        # [I2] Store in cache
        llm_cache.set("script", final_script, subject=video_subject, language=language, paragraphs=paragraph_number)
    return final_script.strip()


def generate_terms(video_subject: str, video_script: str, amount: int = 5, use_faceless: bool = False) -> List[str]:
    faceless_instruction = ""
    if use_faceless:
        faceless_instruction = """
7. **FACELESS MODE ACTIVE**: 
   - STRICTLY AVOID terms that imply a person's face (e.g., "portrait", "face", "looking at camera", "talking head").
   - Focus on: "hands doing x", "back view of person", "over the shoulder shot", "close up of objects", "scenery", "environment".
   - If the subject requires a person, use "silhouette", "shadow", "body part only".
"""

    prompt = f"""
# Role: Video Search Terms Generator

## Goals:
Generate {amount} highly specific search terms for stock videos, based on the video subject and script.

## Constraints:
1. The search terms must be returned as a JSON-array of strings.
2. **CRITICAL**: Each search term MUST include the main subject "{video_subject}" or a direct synonym.
3. **VISUAL FOCUS**: Generate terms that represent **tangible objects** or **visual scenes**.
   - BAD: "{video_subject} culture", "{video_subject} happiness", "{video_subject} background", "{video_subject} nature"
   - GOOD: "{video_subject} lantern", "{video_subject} eating dates", "{video_subject} praying hands", "{video_subject} mosque architecture"
4. Avoid generic words like "video", "footage", "4k", "hd", "scene".
5. Reply with English search terms only.
6. All search terms must be safe and appropriate for children.
{faceless_instruction}

## Output Example:
["{video_subject} celebration dinner", "{video_subject} traditional clothes", "{video_subject} praying", "{video_subject} family gathering"]

## Context:
### Video Subject
{video_subject}


### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
""".strip()

    logger.info(f"subject: {video_subject}")

    # [I2] Check cache first
    _script_hash = hashlib.md5(video_script.encode()).hexdigest()[:8] if video_script else "none"
    cached = llm_cache.get("terms", subject=video_subject, script_hash=_script_hash, faceless=use_faceless)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass  # fall through to LLM call

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if "Error: " in response:
                logger.error(f"failed to generate video terms: {response}")
                return None
            search_terms = json.loads(response)
            if not isinstance(search_terms, list) or not all(
                isinstance(term, str) for term in search_terms
            ):
                logger.error("response is not a list of strings.")
                continue

        except Exception as e:
            logger.warning(f"failed to generate video terms: {str(e)}")
            if response:
                match = re.search(r"\[.*]", response)
                if match:
                    try:
                        search_terms = json.loads(match.group())
                    except Exception as e:
                        logger.warning(f"failed to generate video terms: {str(e)}")
                        pass

        if search_terms and len(search_terms) > 0:
            break
        if i < _max_retries:
            logger.warning(f"failed to generate video terms, trying again... {i + 1}")
            time.sleep(2 * (i + 1))  # exponential backoff

    logger.success(f"completed: \n{search_terms}")
    # [I2] Store in cache
    if search_terms:
        _script_hash = hashlib.md5(video_script.encode()).hexdigest()[:8] if video_script else "none"
        llm_cache.set("terms", json.dumps(search_terms), subject=video_subject, script_hash=_script_hash, faceless=use_faceless)
    return search_terms


def generate_scene_terms(video_subject: str, video_script: str, use_faceless: bool = False) -> list[dict]:
    """
    [C3] Scene-Aware Video Matching: generate one search term per script sentence.
    Returns a list of dicts: [{"sentence": "...", "term": "..."}, ...]
    Falls back to regular generate_terms if LLM fails.
    """
    faceless_note = ""
    if use_faceless:
        faceless_note = "\n- AVOID terms with faces, portraits, or people looking at camera."

    prompt = f"""
# Role: Scene-Aware Video Director

## Task
You are given a video script. For EACH sentence, generate ONE highly specific stock video search term
that visually represents what is being narrated at that moment.

## Rules
1. Return ONLY a JSON array of objects with "sentence" and "term" keys.
2. Each "term" must be 2-5 words, suitable for stock video search (Pexels/Pixabay).
3. Terms must be in English.
4. Match the visual mood and content of each sentence.
5. Avoid generic terms like "video", "footage", "clip".{faceless_note}

## Script
{video_script}

## Output Format (JSON only, no markdown):
[
  {{"sentence": "First sentence of script.", "term": "specific visual search term"}},
  {{"sentence": "Second sentence.", "term": "another specific term"}}
]
""".strip()

    logger.info(f"[C3] Generating scene-aware terms for {len(video_script.split('.'))} sentences...")

    # Check cache
    _hash = hashlib.md5(video_script.encode()).hexdigest()[:8]
    cached = llm_cache.get("scene_terms", subject=video_subject, script_hash=_hash, faceless=use_faceless)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    scene_terms = []
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if not response:
                continue
            # Extract JSON array
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if isinstance(parsed, list) and all("term" in item for item in parsed):
                    scene_terms = parsed
                    break
        except Exception as e:
            logger.warning(f"[C3] Scene terms attempt {i+1} failed: {e}")
            time.sleep(2 * (i + 1))

    if scene_terms:
        llm_cache.set("scene_terms", json.dumps(scene_terms), subject=video_subject, script_hash=_hash, faceless=use_faceless)
        logger.success(f"[C3] Generated {len(scene_terms)} scene-aware terms")
    else:
        logger.warning("[C3] Scene terms generation failed, falling back to regular terms")

    return scene_terms


if __name__ == "__main__":
    video_subject = "生命的意义是什么"
    script = generate_script(
        video_subject=video_subject, language="zh-CN", paragraph_number=1
    )
    print("######################")
    print(script)
    search_terms = generate_terms(
        video_subject=video_subject, video_script=script, amount=5
    )
    print("######################")
    print(search_terms)
    
def generate_veo_prompts(video_subject: str, video_script: str) -> dict:
    """
    Generate Veo prompts (positive and negative) based on the video subject and script.
    """
    prompt = f"""
# Role: Video Director & Cinematographer

# Task
Generate a highly detailed, cinematic prompt for a video generation AI (like Google Veo) and a negative prompt to avoid unwanted elements.
The video will be used as the **initial hook** (first 5-8 seconds) of a video about: "{video_subject}".

# Video Script Context:
{video_script[:500]}...

# Instructions
1. **Positive Prompt**: Describe the visual scene in detail.
   - Style: **Photorealistic, Cinematic, 4k, High Detail**.
   - Lighting: Cinematic lighting, golden hour, or dramatic lighting.
   - Camera: Drone shot, close up, or tracking shot.
   - Content: Make it catchy and relevant to the hook. Focus on the main subject.
2. **Negative Prompt**: STRICTLY avoid these elements:
   - text, watermark, logo, copyright, blurry, distorted, bad anatomy, deformed, cartoon, illustration, painting, low quality, pixelated.

# Output Format
Return ONLY a JSON object:
{{
  "prompt": "your detailed positive prompt here",
  "negative_prompt": "your negative prompt here"
}}
"""
    response = _generate_response(prompt)
    try:
        # Extract JSON from potential markdown code blocks
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            json_str = match.group()
            return json.loads(json_str)
        else:
            return json.loads(response)
    except Exception as e:
        logger.error(f"Failed to parse Veo prompts from LLM response: {e}. Response: {response}")
        # Fallback
        return {
            "prompt": f"Cinematic shot of {video_subject}, 8k resolution, highly detailed, professional lighting.",
            "negative_prompt": "text, watermark, blurry, distorted, cartoon, low quality"
        }
