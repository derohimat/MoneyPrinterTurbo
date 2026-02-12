"""
API Rate Limiter — Prevents hitting API limits for Pexels/Pixabay.
"""
import time
from loguru import logger

class RateLimiter:
    def __init__(self, calls_per_minute=30):
        self.delay = 60.0 / calls_per_minute
        self.last_call = 0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.delay:
            wait_time = self.delay - elapsed
            logger.debug(f"Rate limiter: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        self.last_call = time.time()

# Global limiters
# Pexels: 200 requests/hour recommended limit for free tier
# Pixabay: 5000 requests/hour
pexels = RateLimiter(calls_per_minute=30)   # 1 request every 2 seconds
pixabay = RateLimiter(calls_per_minute=60)  # 1 request every 1 second
