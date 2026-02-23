import time
import threading
from functools import wraps

# Global state to track the last external API call time ACROSS ALL functions
_last_called = 0.0
_global_lock = threading.Lock()

def rate_limit(calls_per_minute=10):
    """
    Globally spaces out function executions so we don't exceed the API ratelimit.
    10 calls per minute = 60.0 / 10 = 6.0 seconds per call.
    """
    min_interval = 60.0 / calls_per_minute

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global _last_called
            
            with _global_lock:
                elapsed = time.time() - _last_called
                if elapsed < min_interval:
                    # Sleep the exact remaining time needed to hit 6.0s
                    sleep_time = min_interval - elapsed
                    print(f"⏳ Rate Limiter Active: Pausing {sleep_time:.2f}s before calling {func.__name__}...")
                    time.sleep(sleep_time)
                
                try:
                    return func(*args, **kwargs)
                finally:
                    # Update global timer AFTER the function triggers
                    _last_called = time.time()
        return wrapper
    return decorator
