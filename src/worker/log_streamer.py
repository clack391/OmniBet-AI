import sys
import json
import redis
from datetime import datetime, timezone
from contextlib import contextmanager


@contextmanager
def stream_logs_to_redis(job_id: str):
    """Context manager that redirects sys.stdout during execution.

    Every print() call inside the Celery task (including all pipeline.py
    agent output) is:
      1. Still written to the console (worker logs).
      2. Published to Redis pub/sub channel  job:{job_id}:logs
         as a JSON message  {"type": "log", "message": "...", "ts": "..."}

    No changes to pipeline.py are required.
    """
    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        # Redis unavailable — run without streaming, don't crash the task
        yield
        return

    channel = f"job:{job_id}:logs"
    original_stdout = sys.stdout

    class RedisLogStream:
        def write(self, text):
            original_stdout.write(text)
            if text.strip():
                try:
                    r.publish(channel, json.dumps({
                        "type": "log",
                        "message": text.strip(),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }))
                except Exception:
                    pass  # Never let Redis errors crash the prediction task

        def flush(self):
            original_stdout.flush()

        # Make it look like a real file object so libraries don't complain
        def fileno(self):
            return original_stdout.fileno()

        def isatty(self):
            return False

    sys.stdout = RedisLogStream()
    try:
        yield
    finally:
        sys.stdout = original_stdout
        # Notify the WebSocket that this job's log stream is finished
        try:
            r.publish(channel, json.dumps({
                "type": "done",
                "job_id": job_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            pass
