
import re
from loguru import logger

# Default scoring weights
DEFAULT_WEIGHTS = {
    "base_score": 50,
    "avg_sentence_length_penalty": 2,  # penalty per word above threshold (15)
    "question_bonus": 10,             # bonus per question per 100 words
    "exclamation_bonus": 5,           # bonus per exclamation per 100 words
    "emotional_word_bonus": 5,        # bonus per emotional word per 100 words
    "hook_strength_bonus": 20,        # bonus if first sentence is short & catchy
    "cliffhanger_bonus": 8,           # bonus per cliffhanger phrase per 100 words
    "max_score": 100,
    "min_score": 0
}

# Keywords for analysis (English + Indonesian)
EMOTIONAL_WORDS = {
    "amazing", "incredible", "shocking", "unbelievable", "secret", "exposed", "mystery",
    "scary", "terrifying", "hilarious", "insane", "crazy", "best", "worst", "never",
    "fail", "win", "legendary", "myth", "truth",
    "luar biasa", "rahasia", "mengejutkan", "gila", "terbaik", "terburuk", "aneh",
    "misteri", "mengungkap", "dasyat", "keren", "parah", "wajib", "penting"
}

CLIFFHANGER_PHRASES = [
    "but wait", "however", "here is the thing", "the truth is", "what happened next",
    "you won't believe", "suddenly", "turns out", "in the end",
    "tapi tunggu", "namun", "ternyata", "yang gila adalah", "sebenarnya",
    "apa yang terjadi", "kamu tidak akan percaya", "tiba-tiba", "akhirnya"
]

def score_script(script_text: str, weights: dict = None) -> dict:
    """
    Analyze script and return a score (0-100) with breakdown.
    
    Args:
        script_text: The full text of the video script.
        weights: Optional dictionary to override default scoring weights.
        
    Returns:
        dict: {
            "score": int,
            "breakdown": dict,
            "feedback": list
        }
    """
    if not script_text:
        return {"score": 0, "breakdown": {}, "feedback": ["No script provided."]}

    w = weights or DEFAULT_WEIGHTS
    
    # Preprocessing
    # Remove extra whitespace
    clean_text = re.sub(r'\s+', ' ', script_text).strip()
    
    # Split into sentences (naive split by punctuation)
    sentences = re.split(r'[.!?]+', clean_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # Split into words
    words = re.findall(r'\w+', clean_text.lower())
    word_count = len(words)
    sentence_count = len(sentences)
    
    if word_count == 0 or sentence_count == 0:
         return {"score": 0, "breakdown": {}, "feedback": ["Script is empty."]}

    score = w["base_score"]
    breakdown = {"base": w["base_score"]}
    feedback = []

    # 1. Average Sentence Length
    avg_len = word_count / sentence_count
    # Threshold: 15 words. Ideally scripts are punchy.
    threshold = 15
    if avg_len > threshold:
        penalty = (avg_len - threshold) * w["avg_sentence_length_penalty"]
        score -= penalty
        breakdown["sentence_length_penalty"] = -round(penalty, 1)
        feedback.append(f"Sentences are too long (avg {avg_len:.1f} words). Aim for < {threshold}.")
    else:
        breakdown["sentence_length_penalty"] = 0

    # 2. Question Density
    question_count = script_text.count("?")
    q_density = (question_count / word_count) * 100
    q_bonus = q_density * w["question_bonus"]
    # Cap bonus
    q_bonus = min(q_bonus, 20) 
    score += q_bonus
    breakdown["question_bonus"] = round(q_bonus, 1)
    if question_count == 0:
        feedback.append("Consider adding questions to engage the audience.")

    # 3. Exclamation/Excitement Density
    excl_count = script_text.count("!")
    e_density = (excl_count / word_count) * 100
    e_bonus = e_density * w["exclamation_bonus"]
    e_bonus = min(e_bonus, 15)
    score += e_bonus
    breakdown["excitement_bonus"] = round(e_bonus, 1)

    # 4. Emotional Word Density
    emo_count = sum(1 for word in words if word in EMOTIONAL_WORDS)
    emo_density = (emo_count / word_count) * 100
    emo_bonus = emo_density * w["emotional_word_bonus"]
    emo_bonus = min(emo_bonus, 20)
    score += emo_bonus
    breakdown["emotional_word_bonus"] = round(emo_bonus, 1)
    if emo_count < 3:
        feedback.append("Script lacks emotional trigger words (e.g., amazing, secret, crazy).")

    # 5. Cliffhanger/Transition Phrases
    cw_count = 0
    lower_script = clean_text.lower()
    for phrase in CLIFFHANGER_PHRASES:
        cw_count += lower_script.count(phrase)
    
    cw_density = (cw_count / word_count) * 100
    cw_bonus = cw_density * w["cliffhanger_bonus"]
    cw_bonus = min(cw_bonus, 15)
    score += cw_bonus
    breakdown["cliffhanger_bonus"] = round(cw_bonus, 1)

    # 6. Hook Strength (First Sentence)
    if sentences:
        first_sent = sentences[0]
        first_words = len(first_sent.split())
        # Hook criteria: Short (<12 words) OR contains Question/Exclamation OR Emotional word
        is_short = first_words < 12
        has_punct = "?" in first_sent or "!" in first_sent
        has_emo = any(word in first_sent.lower() for word in EMOTIONAL_WORDS)
        
        hook_bonus = 0
        if is_short: hook_bonus += 5
        if has_punct: hook_bonus += 5
        if has_emo: hook_bonus += 10
        
        # Max hook bonus is implicit 20 defined in logic, but let's stick to valid check
        if hook_bonus > 0:
            score += hook_bonus
            breakdown["hook_bonus"] = hook_bonus
        else: 
            feedback.append("First sentence (Hook) is weak. Make it short, punchy, or emotional.")

    # Final Clamping
    final_score = max(w["min_score"], min(w["max_score"], round(score)))
    
    return {
        "score": final_score,
        "breakdown": breakdown,
        "feedback": feedback,
        "metrics": {
            "word_count": word_count,
            "sentence_count": sentence_count,
            "avg_len": round(avg_len, 1),
            "emotional_words": emo_count,
            "questions": question_count
        }
    }
