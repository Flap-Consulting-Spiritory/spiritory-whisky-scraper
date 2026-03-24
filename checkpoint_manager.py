import json
import os
from datetime import datetime

STATE_FILE = "scraper_state.json"

def load_checkpoint() -> int | None:
    """Loads the last processed bottle ID from the state file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get("last_processed_id")
        except json.JSONDecodeError:
            print("[Checkpoint Manager] Failed to decode existing state file. starting from scratch.")
    return None

def save_checkpoint(bottle_id: int):
    """Saves the last processed bottle ID to the state file."""
    data = {
        "last_processed_id": bottle_id,
        "last_run_timestamp": datetime.now().isoformat()
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)
