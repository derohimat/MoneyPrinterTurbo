import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Global negative terms (Safe for work/Kids friendly)
GLOBAL_NEGATIVE_TERMS = [
    "nude", "sex", "porn", "bikini", "underwear", "lingerie", "naked", 
    "violence", "blood", "gore", "kill", "murder", "death", "dead", 
    "drug", "cocaine", "heroine", "weed", "smoking", "cigarette", "alcohol", "liquor", "beer", "wine", "drunk",
    "horror", "scary", "ghost", "zombie", "monster", "witch", "demon", "devil", "satan", "hell" # Default exclude horror unless specified
]

# Category specific negative terms
CATEGORY_NEGATIVE_TERMS: Dict[str, List[str]] = {
    "IslamicPlaces": [
        "church", "cross", "nun", "priest", "jesus", "christ", "buddha", "monk", "hindu", "christmas", 
        "temple", "statue", "idol", "pig", "pork", "dog", "bar", "club", "party", "dance", "music", "woman", "girl"
    ],
    "Stoik": [
        "party", "club", "dancing", "laughing", "comedy", "funny", "silly", "crazy", "angry", "fighting", "crying",
        "luxury", "rich", "gold", "money", "expensive", "car", "mansion"
    ],
    "Psikologi": [
        "hospital", "surgery", "blood", "doctor", "nurse", "mad", "crazy", "insane", "asylum", "horror", "scary"
    ],
    "Misteri": [
        "funny", "comedy", "happy", "bright", "sunny", "cartoon", "animation", "cute", "silly", "laughing"
    ],
    "Fakta": [
        "fiction", "movie", "film", "actor", "actress", "fake", "cartoon", "animation", "drawing", "sketch"
    ],
    "Kesehatan": [
        "junk food", "burger", "pizza", "soda", "candy", "sugar", "cake", "hospital", "surgery", "blood", "needle", "injection"
    ],
    "Horor": [
        "funny", "comedy", "happy", "bright", "sunny", "cute", "silly", "laughing", "cartoon", "animation", "baby", "child"
    ],
    "Keuangan": [
        "poverty", "homeless", "beggar", "trash", "dirty", "gambling", "casino", "slot machine", "betting"
    ]
}

def get_negative_terms(subject: str, category_hint: str = None) -> List[str]:
    """
    Determine negative terms based on subject and optional category hint.
    """
    negative_terms = list(GLOBAL_NEGATIVE_TERMS)
    
    # Try to detect category from subject if not provided
    detected_category = category_hint
    if not detected_category:
        subject_lower = subject.lower()
        if "islam" in subject_lower or "muslim" in subject_lower:
             detected_category = "IslamicPlaces"
        elif "stoic" in subject_lower:
             detected_category = "Stoik"
        elif "psychology" in subject_lower:
             detected_category = "Psikologi"
        elif "mystery" in subject_lower:
             detected_category = "Misteri"
        elif "fact" in subject_lower:
             detected_category = "Fakta"
        elif "health" in subject_lower:
             detected_category = "Kesehatan"
        elif "horror" in subject_lower or "ghost" in subject_lower:
             detected_category = "Horor"
        elif "finance" in subject_lower or "money" in subject_lower:
             detected_category = "Keuangan"

    # If Horror category, remove horror-related bans from global list
    if detected_category and ("Horor" in detected_category or "Misteri" in detected_category):
         for term in ["horror", "scary", "ghost", "zombie", "monster", "witch", "demon", "devil", "satan", "hell", "death", "dead", "kill", "murder", "blood", "gore"]:
            if term in negative_terms:
                negative_terms.remove(term)

    # Add category specific terms
    if detected_category and detected_category in CATEGORY_NEGATIVE_TERMS:
        negative_terms.extend(CATEGORY_NEGATIVE_TERMS[detected_category])
    
    return negative_terms
