"""Step 4: Push approved corrections to Strapi. Run ONLY after client approval."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from integrations.strapi import update_bottle, get_headers, STRAPI_BASE_URL
from utils.jitter import random_delay

INPUT_PATH = Path(__file__).parent / "data" / "corrections.json"


def fetch_document_id(bottle_id: int) -> str | None:
    """Fetch documentId from Strapi for a given numeric ID."""
    url = (
        f"{STRAPI_BASE_URL}/skus"
        f"?filters[id][$eq]={bottle_id}"
        f"&pagination[limit]=1"
        f"&fields[0]=id"
    )
    try:
        resp = requests.get(url, headers=get_headers())
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0].get("documentId") if data else None
    except Exception as e:
        print(f"  [Strapi] Error fetching documentId for {bottle_id}: {e}")
        return None


def apply_corrections(dry_run: bool = False) -> None:
    """Apply all corrections to Strapi."""

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    corrections = data.get("corrections", [])
    if not corrections:
        print("[Apply] No corrections to apply.")
        return

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[Apply] {mode} — {len(corrections)} bottles to update")

    success = 0
    failed = 0

    for i, c in enumerate(corrections, 1):
        b_id = c["id"]
        b_name = c["name"]
        improved = c.get("improved", {})

        if not improved or not improved.get("en"):
            print(f"[{i}/{len(corrections)}] {b_name} — no improved description, skipping")
            failed += 1
            continue

        # Get documentId (prefer stored, fallback to API)
        doc_id = c.get("documentId") or fetch_document_id(b_id)
        if not doc_id:
            print(f"[{i}/{len(corrections)}] {b_name} — FAILED: no documentId")
            failed += 1
            continue

        payload = {"description": improved}

        if dry_run:
            en_preview = improved.get("en", "")[:80]
            print(f"[{i}/{len(corrections)}] {b_name} — would update: \"{en_preview}...\"")
        else:
            try:
                update_bottle(doc_id, payload)
                print(f"[{i}/{len(corrections)}] {b_name} — updated successfully")
                success += 1
            except Exception as e:
                print(f"[{i}/{len(corrections)}] {b_name} — FAILED: {e}")
                failed += 1

        if i < len(corrections) and not dry_run:
            random_delay(0.5, 1.5)

    print(f"\n[Apply] {mode} complete: {success} success, {failed} failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply corrected descriptions to Strapi")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    apply_corrections(dry_run=args.dry_run)
