"""Batch helpers for improve_descriptions.py.

Holds the batched Venice AI client, the per-batch processing loop with
single-bottle fallback, and a structured run logger that writes to
correccion/logs/improve_YYYYMMDD_HHMMSS.log.

Kept in a separate module so improve_descriptions.py stays under the
300-line global limit.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import openai

from utils.jitter import random_delay
from correccion.prompt_templates import build_batch_improvement_prompt

VENICE_BASE_URL = "https://api.venice.ai/api/v1"
VENICE_MODEL = "gemini-3-flash-preview"

LOGS_DIR = Path(__file__).parent / "logs"


def setup_run_logger() -> tuple[logging.Logger, Path]:
    """Create a per-run text logger writing to correccion/logs/improve_*.log.

    Also mirrors records to stdout via a StreamHandler so progress is
    visible when the script runs in the foreground.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"improve_{stamp}.log"

    logger = logging.getLogger(f"correccion.improve.{stamp}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Avoid duplicate handlers if called twice in the same process
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger, log_path


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def call_venice_ai_batch(prompt: str, expected_ids: list[int]) -> list[dict]:
    """Call Venice AI with a multi-bottle prompt and parse the results array.

    Returns a list of dicts shaped {"id": int, "improved": {de,en,es,fr,it}}
    in the same order as expected_ids.

    Raises ValueError if the response is missing any expected id (caller
    catches this to fall back to per-bottle calls).
    """
    client = openai.OpenAI(
        api_key=os.environ.get("VENICE_ADMIN_KEY", ""),
        base_url=VENICE_BASE_URL,
    )

    response = client.chat.completions.create(
        model=VENICE_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    parsed = json.loads(raw)

    results = parsed.get("results")
    if not isinstance(results, list):
        raise ValueError("batch response missing 'results' array")

    by_id: dict[int, dict] = {}
    for entry in results:
        try:
            rid = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        improved = entry.get("improved") or {}
        by_id[rid] = {
            "de": improved.get("de", ""),
            "en": improved.get("en", ""),
            "es": improved.get("es", ""),
            "fr": improved.get("fr", ""),
            "it": improved.get("it", ""),
        }

    missing = [i for i in expected_ids if i not in by_id]
    if missing:
        raise ValueError(f"batch incomplete: missing ids {missing}")

    # Reject empty english descriptions (model returned the slot but no text)
    empty = [i for i in expected_ids if not by_id[i]["en"].strip()]
    if empty:
        raise ValueError(f"batch incomplete: empty 'en' for ids {empty}")

    return [{"id": i, "improved": by_id[i]} for i in expected_ids]


def process_batch(
    entries: list[dict],
    output: dict,
    logger: logging.Logger,
    fetch_bottle_by_id: Callable[[int], dict | None],
    extract_metadata: Callable[[dict], dict],
    get_current_description_en: Callable[[dict], str],
    save_corrections: Callable[[dict], None],
    process_one_bottle: Callable[[dict, dict, logging.Logger], bool],
    batch_label: str = "",
) -> tuple[int, int]:
    """Process N bottles in a single Venice call. Falls back to per-bottle on failure.

    Returns (success_count, failed_count).
    """
    # Step 1: Strapi-fetch every bottle in the batch.
    items: list[dict] = []
    skipped: list[dict] = []
    for entry in entries:
        b_id = entry["id"]
        b_name = entry["name"]
        bottle_data = fetch_bottle_by_id(b_id)
        if not bottle_data:
            logger.warning(f"{batch_label} [FAIL id={b_id} name=\"{b_name}\"] reason=strapi_fetch")
            output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
            output["failed"].append({"id": b_id, "name": b_name, "error": "strapi_fetch"})
            skipped.append(entry)
            continue

        current_en = get_current_description_en(bottle_data)
        if not current_en:
            logger.warning(f"{batch_label} [FAIL id={b_id} name=\"{b_name}\"] reason=no_description")
            output["failed"] = [f for f in output["failed"] if f["id"] != b_id]
            output["failed"].append({"id": b_id, "name": b_name, "error": "no_description"})
            skipped.append(entry)
            continue

        items.append({
            "id": b_id,
            "name": b_name,
            "documentId": bottle_data.get("documentId", ""),
            "current_desc_en": current_en,
            "metadata": extract_metadata(bottle_data),
        })
        random_delay(0.3, 0.8)

    # Persist any per-bottle skip/strapi failures immediately
    if skipped:
        save_corrections(output)

    if not items:
        return 0, len(skipped)

    # Step 2: One Venice call for the whole batch.
    expected_ids = [item["id"] for item in items]
    prompt = build_batch_improvement_prompt(items)
    logger.info(f"{batch_label} calling Venice with {len(items)} bottles ids={expected_ids}")

    started = time.monotonic()
    try:
        batch_results = call_venice_ai_batch(prompt, expected_ids)
    except Exception as e:
        elapsed = time.monotonic() - started
        logger.warning(
            f"{batch_label} [FALLBACK] batch venice call failed after {elapsed:.1f}s: {e} "
            f"-> retrying {len(items)} bottles individually"
        )
        # Per-bottle fallback path. Each bottle goes through the original
        # single-bottle flow which has its own try/except + persist.
        success = 0
        failed = len(skipped)
        for item in items:
            entry = {"id": item["id"], "name": item["name"]}
            ok = process_one_bottle(entry, output, logger)
            if ok:
                success += 1
            else:
                failed += 1
            random_delay(1.0, 2.5)
        return success, failed

    # Step 3: Batch succeeded. Append all results atomically and drop any
    # stale failed entries for these ids (they were retries that now succeed).
    elapsed = time.monotonic() - started
    success_ids = {result["id"] for result in batch_results}
    output["failed"] = [f for f in output["failed"] if f["id"] not in success_ids]
    by_id_meta = {item["id"]: item for item in items}
    for result in batch_results:
        b_id = result["id"]
        meta_item = by_id_meta[b_id]
        improved = result["improved"]
        wc_orig = len(meta_item["current_desc_en"].split())
        wc_impr = len(improved.get("en", "").split())
        logger.info(
            f"{batch_label} [OK id={b_id} name=\"{meta_item['name']}\"] "
            f"{wc_orig} words -> {wc_impr} words"
        )
        output["corrections"].append({
            "id": b_id,
            "name": meta_item["name"],
            "documentId": meta_item["documentId"],
            "original_en": meta_item["current_desc_en"],
            "improved": improved,
            "metadata": meta_item["metadata"],
        })

    output["processed"] = len(output["corrections"])
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    save_corrections(output)
    logger.info(
        f"{batch_label} batch done: {len(items)} success in {elapsed:.1f}s "
        f"(total_done={output['processed']}, total_failed={len(output['failed'])})"
    )
    return len(items), len(skipped)
