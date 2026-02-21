import time
import threading
from functools import wraps

# Global state to track the last call time 
_last_called = 0.0
_lock = threading.Lock()

def rate_limit(calls_per_minute=10):
    min_interval = 60.0 / calls_per_minute

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global _last_called
            
            with _lock:
                elapsed = time.time() - _last_called
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                
                try:
                    return func(*args, **kwargs)
                finally:
                    _last_called = time.time()
        return wrapper
    return decorator
