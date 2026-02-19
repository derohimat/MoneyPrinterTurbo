import numpy as np
import re

def predict_retention_curve(script_text, estimated_duration=60):
    """
    Generate per-second engagement prediction.
    Returns: list of float (0.0-1.0) representing score per second.
    
    Simplified logic since we might not have exact subtitle timestamps yet during pre-generation scoring.
    We assume uniform speaking rate for the prediction if subtitles aren't provided.
    """
    if not script_text:
        return [0.5] * estimated_duration

    # Split into rough sentences to approximate timing
    sentences = re.split(r'[.!?]+', script_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return [0.5] * estimated_duration

    # Estimate time per sentence (approx 150 words per minute = 2.5 words per second)
    words_per_sec = 2.5
    
    curve = []
    
    base_score = 0.5
    
    for sent in sentences:
        words = sent.split()
        n_words = len(words)
        duration = max(1, int(n_words / words_per_sec))
        
        # Scoring logic
        score = base_score
        
        # 1. Question boost
        if "?" in sent:
            score += 0.2
            
        # 2. Exclamation boost
        if "!" in sent:
            score += 0.1
            
        # 3. Short sentence boost
        if n_words < 8:
            score += 0.15
        
        # 4. Long sentence penalty
        if n_words > 15:
            score -= (n_words - 15) * 0.05
            
        # 5. Pattern interrupt (numbers)
        if any(char.isdigit() for char in sent):
            score += 0.1
            
        # 6. Negative word penalty (boring words)
        if any(w in sent.lower() for w in ["basically", "sort of", "maybe", "usually"]):
            score -= 0.1

        # Clamp score
        score = max(0.1, min(1.0, score))
        
        # Append to curve for the duration of this sentence
        curve.extend([score] * duration)

    # Adjust total duration to match estimated_duration if needed
    current_len = len(curve)
    if current_len < estimated_duration:
        curve.extend([curve[-1]] * (estimated_duration - current_len))
    elif current_len > estimated_duration:
        curve = curve[:estimated_duration]
        
    # Apply decay (viewers drop off naturally)
    # Linear decay: start 1.0 -> end 0.8 modifier
    decay = np.linspace(1.0, 0.8, len(curve))
    curve = [s * d for s, d in zip(curve, decay)]
    
    return curve

def get_retention_heatmap_data(script_text, duration=60):
    """
    Returns data formatted for a Streamlit chart.
    """
    curve = predict_retention_curve(script_text, duration)
    return {
        "seconds": list(range(len(curve))),
        "engagement": curve
    }
