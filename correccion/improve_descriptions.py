"""Step 2: Fetch bottle metadata from Strapi, enhance descriptions via Venice AI.

With --batch-size N>1, N bottles share one Venice call, amortizing the
few-shot examples block (~1,300 tokens) across the batch.
"""

import argparse
import json
import logging
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import openai
import requests

# Add parent dir to path so we can import project modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.jitter import random_delay
from utils.metadata import extract_metadata as _extract_metadata_shared
from integrations.strapi import get_headers, STRAPI_BASE_URL
from correccion.prompt_templates import build_improvement_prompt
from correccion.batch_runner import setup_run_logger, process_batch

INPUT_PATH = Path(__file__).parent / "data" / "bottles_to_correct.json"
OUTPUT_PATH = Path(__file__).parent / "data" / "corrections.json"


def fetch_bottle_by_id(bottle_id: int) -> dict | None:
    """Fetch a single bottle from Strapi by numeric ID."""
    url = (
        f"{STRAPI_BASE_URL}/skus"
        f"?filters[id][$eq]={bottle_id}"
        f"&pagination[limit]=1"
    )
    try:
        resp = requests.get(url, headers=get_headers())
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0] if data else None
    except Exception as e:
        print(f"  [Strapi] Error fetching bottle {bottle_id}: {e}")
        return None


def extract_metadata(bottle: dict) -> dict:
    """Extract relevant metadata fields from a Strapi bottle record.
    Delegates to `utils.metadata.extract_metadata` so live + correction runs
    share one source of truth."""
    return _extract_metadata_shared(bottle)


def get_current_description_en(bottle: dict) -> str:
    """Extract the current English description from a Strapi bottle."""
    desc = bottle.get("description")
    if isinstance(desc, dict):
        return desc.get("en", "") or ""
    if isinstance(desc, str):
        return desc
    return ""


def call_venice_ai(prompt: str) -> dict:
    """Call Venice AI and return parsed 5-language description dict."""
    client = openai.OpenAI(
        api_key=os.environ.get("VENICE_ADMIN_KEY", ""),
        base_url="https://api.venice.ai/api/v1",
    )

    response = client.chat.completions.create(
        model="gemini-3-flash-preview",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    parsed = json.loads(raw)
    return {
        "de": parsed.get("de", ""),
        "en": parsed.get("en", ""),
        "es": parsed.get("es", ""),
        "fr": parsed.get("fr", ""),
        "it": parsed.get("it", ""),
    }


def load_existing_corrections() -> dict:
    """Load existing corrections file for resume support."""
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"total": 0, "processed": 0, "corrections": [], "failed": []}


def save_corrections(data: dict) -> None:
    """Save corrections to JSON file."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def process_one_bottle(entry: dict, output: dict, logger: logging.Logger) -> bool:
    """Single-bottle path: Strapi fetch -> Venice call -> append. Used by
    --batch-size 1 runs and as fallback when a batched call fails."""
    b_id = entry["id"]
    b_name = entry["name"]

    bottle_data = fetch_bottle_by_id(b_id)
    if not bottle_data:
        logger.warning(f"[FAIL id={b_id} name=\"{b_name}\"] reason=strapi_fetch")
        # De-duplicate: drop any prior failed record for this id before re-appending
        output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
        output["failed"].append({"id": b_id, "name": b_name, "error": "strapi_fetch"})
        save_corrections(output)
        return False

    metadata = extract_metadata(bottle_data)
    current_en = get_current_description_en(bottle_data)
    if not current_en:
        logger.warning(f"[FAIL id={b_id} name=\"{b_name}\"] reason=no_description")
        output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
        output["failed"].append({"id": b_id, "name": b_name, "error": "no_description"})
        save_corrections(output)
        return False

    prompt = build_improvement_prompt(b_name, current_en, metadata)
    try:
        improved = call_venice_ai(prompt)
    except Exception as e:
        logger.warning(f"[FAIL id={b_id} name=\"{b_name}\"] reason={e}")
        output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
        output["failed"].append({"id": b_id, "name": b_name, "error": str(e)})
        save_corrections(output)
        return False

    wc_orig = len(current_en.split())
    wc_impr = len(improved.get("en", "").split())
    logger.info(f"[OK id={b_id} name=\"{b_name}\"] {wc_orig} words -> {wc_impr} words")

    # On retry-after-prior-failure, drop the stale failed entry
    output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
    output["corrections"].append({
        "id": b_id,
        "name": b_name,
        "documentId": bottle_data.get("documentId", ""),
        "original_en": current_en,
        "improved": improved,
        "metadata": metadata,
    })
    output["processed"] = len(output["corrections"])
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    save_corrections(output)
    return True


def _categorize_error(err: str) -> str:
    e = (err or "").lower()
    if "402" in e:
        return "402_no_credits"
    if "429" in e:
        return "429_rate_limit"
    if "json" in e or "missing" in e or "incomplete" in e:
        return "json_parse"
    if "strapi" in e:
        return "strapi_fetch"
    if "no_description" in e:
        return "no_description"
    return "other"


def run_improvement(limit: int = 0, batch_size: int = 5) -> None:
    """Main improvement loop. limit=0 = all pending. batch_size=1 = original
    single-bottle path. batch_size>1 = batched calls with per-bottle fallback."""
    logger, log_path = setup_run_logger()

    with open(INPUT_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    all_bottles = candidates["bottles"]
    total_candidates = candidates.get("total", len(all_bottles))

    existing = load_existing_corrections()
    done_ids = {c["id"] for c in existing["corrections"]}

    # Build pending list: bottles not yet successful (failed entries are retried)
    pending = [b for b in all_bottles if b["id"] not in done_ids]
    if limit and limit > 0:
        pending = pending[:limit]

    output = existing
    output["total"] = total_candidates

    expected_calls = math.ceil(len(pending) / batch_size) if batch_size > 1 else len(pending)
    logger.info("=" * 70)
    logger.info(
        f"[run start] candidates={total_candidates} already_done={len(done_ids)} "
        f"pending={len(pending)} batch_size={batch_size} limit={limit or 'all'}"
    )
    logger.info(f"[run start] expected venice calls: ~{expected_calls}")
    logger.info(f"[run start] log file: {log_path}")
    logger.info("=" * 70)

    success_total = 0
    fail_total_run = 0

    try:
        if batch_size <= 1:
            for i, entry in enumerate(pending, 1):
                logger.info(f"[{i}/{len(pending)}] id={entry['id']} name=\"{entry['name']}\"")
                ok = process_one_bottle(entry, output, logger)
                if ok:
                    success_total += 1
                else:
                    fail_total_run += 1
                if i < len(pending):
                    random_delay(1.0, 3.0)
        else:
            chunks = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
            for k, chunk in enumerate(chunks, 1):
                label = f"[batch {k}/{len(chunks)}]"
                logger.info(
                    f"{label} starting ({len(chunk)} bottles, "
                    f"total_done={output['processed']}, total_failed={len(output['failed'])})"
                )
                s, f_ = process_batch(
                    entries=chunk,
                    output=output,
                    logger=logger,
                    fetch_bottle_by_id=fetch_bottle_by_id,
                    extract_metadata=extract_metadata,
                    get_current_description_en=get_current_description_en,
                    save_corrections=save_corrections,
                    process_one_bottle=process_one_bottle,
                    batch_label=label,
                )
                success_total += s
                fail_total_run += f_
                if k < len(chunks):
                    random_delay(1.5, 3.5)

    except KeyboardInterrupt:
        logger.warning("[INTERRUPTED] Ctrl+C received — state already persisted to corrections.json")

    # Final summary
    err_breakdown = Counter(_categorize_error(f.get("error", "")) for f in output["failed"])
    logger.info("=" * 70)
    logger.info(
        f"[run done] processed={output['processed']} "
        f"total_failed_in_state={len(output['failed'])} "
        f"this_run_success={success_total} this_run_failed={fail_total_run}"
    )
    logger.info(f"[run done] error breakdown: {dict(err_breakdown)}")
    logger.info(f"[run done] state file: {OUTPUT_PATH}")
    logger.info(f"[run done] log file:   {log_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Improve scraper-generated descriptions")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Number of pending bottles to process (0 = all)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=5,
        help="Bottles per Venice AI call. 1 = original single-bottle path.",
    )
    args = parser.parse_args()
    run_improvement(limit=args.limit, batch_size=args.batch_size)
