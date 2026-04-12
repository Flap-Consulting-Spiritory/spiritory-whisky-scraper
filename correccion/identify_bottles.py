"""Step 1: Parse scraper CSV log and identify bottles with scraper-generated descriptions."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

SKIP_VALUES = {"[already had data]", "[no wb data]", "[ban]", "[error]", ""}

CSV_PATH = Path(__file__).parent.parent / "logs" / "scraper.csv"
OUTPUT_PATH = Path(__file__).parent / "data" / "bottles_to_correct.json"


def identify_bottles() -> dict:
    """Parse CSV and return deduplicated list of bottles with generated descriptions."""
    seen: dict[str, dict] = {}  # id -> latest row

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            desc = row.get("description", "").strip()
            if desc in SKIP_VALUES:
                continue

            bottle_id = row["id"].strip()
            timestamp = row.get("timestamp", "")

            # Keep latest entry per bottle ID
            if bottle_id in seen:
                if timestamp > seen[bottle_id]["timestamp"]:
                    seen[bottle_id] = row
            else:
                seen[bottle_id] = row

    bottles = [
        {
            "id": int(row["id"]),
            "wbId": row.get("wbId", ""),
            "name": row.get("name", ""),
        }
        for row in seen.values()
    ]

    # Sort by ID for consistent ordering
    bottles.sort(key=lambda b: b["id"])

    result = {
        "total": len(bottles),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bottles": bottles,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[Identify] Found {len(bottles)} bottles with scraper-generated descriptions")
    print(f"[Identify] Output: {OUTPUT_PATH}")
    return result


if __name__ == "__main__":
    identify_bottles()
