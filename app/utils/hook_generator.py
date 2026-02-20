"""
Hook Generator — Creates attention-grabbing text overlays for the first 3 seconds of videos.
Proven to significantly increase YouTube Shorts retention rate.
"""

import random
from loguru import logger


# Hook templates by category
HOOK_TEMPLATES = {
    "IslamicPlaces": [
        "This sacred place will leave you speechless...",
        "Have you ever seen anything this beautiful?",
        "Most people don't know this exists...",
        "The story behind this place is incredible...",
        "You won't believe what's inside...",
        "This is one of Islam's most sacred sites...",
    ],
    "Stoik": [
        "This ancient wisdom changed everything...",
        "Marcus Aurelius said something powerful...",
        "Stop scrolling. This will change your mindset.",
        "The Stoics knew something we forgot...",
        "This one principle can transform your life...",
        "Ancient wisdom for modern problems...",
    ],
    "Psikologi": [
        "Your brain is lying to you. Here's how...",
        "Psychology says this about you...",
        "Most people get this completely wrong...",
        "This will change how you see yourself...",
        "The truth about human behavior...",
        "Science just proved something shocking...",
    ],
    "Misteri": [
        "This mystery has never been solved...",
        "What they found will shock you...",
        "Nobody can explain what happened here...",
        "This remains unexplained to this day...",
        "The truth is stranger than fiction...",
        "Scientists are baffled by this discovery...",
    ],
    "Fakta": [
        "I bet you didn't know this...",
        "This fact will blow your mind...",
        "99% of people don't know this...",
        "Wait until you hear this...",
        "Here's something they never taught you...",
        "This changes everything you thought you knew...",
    ],
    "Kesehatan": [
        "Stop doing this to your body...",
        "Doctors don't want you to know this...",
        "This one habit can change your health...",
        "Your body is trying to tell you something...",
        "The truth about what you're eating...",
        "This simple trick boosts your health...",
    ],
    "Horor": [
        "What happened next will terrify you...",
        "This is the scariest thing you'll see today...",
        "Don't watch this alone at night...",
        "This true story gave me chills...",
        "Something is very wrong here...",
        "They should never have gone there...",
    ],
    "Keuangan": [
        "Rich people do this differently...",
        "Stop wasting money on this...",
        "This one mistake is keeping you poor...",
        "The secret to building wealth...",
        "I wish I knew this 10 years ago...",
        "Your money habits are holding you back...",
    ],
}

# Generic hooks for uncategorized content
GENERIC_HOOKS = [
    "Wait for it...",
    "You need to see this...",
    "This will change your perspective...",
    "Most people don't know about this...",
    "Here's something incredible...",
    "Pay attention to this...",
    "You won't believe what happens next...",
    "This is absolutely mind-blowing...",
]

# CTA templates for end screens
CTA_TEMPLATES = [
    "Follow for more! 🔔",
    "Like & Subscribe! ❤️",
    "Share this with someone! 📤",
    "Follow for daily content! ✨",
    "Want more? Hit Follow! 🚀",
    "Don't miss the next one! 🔔",
]


def get_hook_text(category: str = "General", subject: str = "", auto_optimize: bool = True) -> str:
    """
    Get a compelling hook text for the video intro.
    
    Args:
        category: Video category
        subject: Video subject (for context)
        auto_optimize: If True, prefer high-performing hooks from analytics DB.
    
    Returns:
        Hook text string
    """
    # T6-6: Auto-feedback loop
    if auto_optimize:
        try:
            from app.utils import analytics_db
            top_hooks = analytics_db.get_hooks_by_category(category, limit=3, min_samples=3)
            # Filter hooks with retention > 0.5 (50%)
            proven_hooks = [h for h in top_hooks if h.get("avg_retention", 0) > 0.5]
            
            if proven_hooks:
                # 70% chance to pick a proven hook, 30% chance to explore new ones (Epsilon-Greedy like)
                if random.random() < 0.7:
                    selected = random.choice(proven_hooks)["hook_template"]
                    logger.info(f"Auto-Feedback: Selected proven hook for '{category}': {selected}")
                    return selected
        except Exception as e:
            logger.warning(f"Auto-Feedback failed: {e}")

    templates = HOOK_TEMPLATES.get(category, GENERIC_HOOKS)
    hook = random.choice(templates)
    logger.info(f"Hook selected for '{category}': {hook}")
    return hook


def get_cta_text() -> str:
    """Get a call-to-action text for the video outro."""
    return random.choice(CTA_TEMPLATES)
