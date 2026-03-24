import random
import time

def random_delay(min_sec: float = 2.5, max_sec: float = 6.5) -> None:
    """Pause execution for a random amount of time to emulate human interaction."""
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"    [Jitter] Sleeping for {sleep_time:.2f}s...")
    time.sleep(sleep_time)
