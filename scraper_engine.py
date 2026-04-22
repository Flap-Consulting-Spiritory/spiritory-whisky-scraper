"""Spiritory Whisky Scraper — orchestration loop.

Two run modes (selected by the presence of `published_since`):
  * Full backfill — iterates Strapi by ascending id, uses `scraper_state.json`
    as a resumable ID-based checkpoint.
  * Cron — fetches bottles published in the last N hours. Does NOT mutate the
    checkpoint file (the backfill's state stays intact across cron runs).

Per bottle:
  1. Skip if already complete (description + both tasting notes).
  2. Scrape WhiskyBase (reviews + tasting tags) via patchright.
  3. Build a partial Strapi payload (tasting notes → immediate).
  4. If a description is needed and reviews were found, either Venice-call
     now (batch_size=1) or queue for a batched Venice call (batch_size>1).
  5. Flush (write to Strapi + log + checkpoint if backfill).
"""

import argparse
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from dotenv import load_dotenv
load_dotenv()

from tenacity import RetryError as TenacityRetryError

from checkpoint_manager import load_checkpoint, save_checkpoint
from integrations.strapi import fetch_bottles as live_fetch_bottles
from integrations.whiskybase import (
    ScrapeBanException,
    ScrapeHardBanException,
    close_session,
    scrape_bottle_data,
)
from utils.csv_logger import CSVLogger
from utils.jitter import random_delay
from utils.metadata import extract_metadata
from utils.pipeline import BottleTask, build_payload, flush_venice_queue


def run_scraper(
    batch_size: int = 100,
    published_since: datetime | None = None,
    event_callback=None,
    stop_event=None,
    venice_batch: int = 1,
):
    """Run the scraper pipeline.

    Args:
        batch_size: Maximum bottles to process this run.
        published_since: If set, cron mode (time filter, no checkpoint writes).
            If None, backfill mode (id-based checkpoint).
        event_callback: Optional callable(event: dict) for structured events.
        stop_event: Optional threading.Event — if set, loop exits gracefully.
        venice_batch: Group N bottles per Venice call (default 1 = per-bottle).
    """
    def emit(level, event_type, message, bottle_id=None, bottle_name=None):
        print(message, flush=True)
        if event_callback:
            event_callback({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "level": level, "type": event_type,
                "bottle_id": bottle_id, "bottle_name": bottle_name, "msg": message,
            })

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    is_cron = published_since is not None
    mode = "cron" if is_cron else "live"
    save_cp = None if is_cron else save_checkpoint
    emit("info", "start", f"--- Starting Scraper Engine (Mode: {mode}, Batch Size: {batch_size}, "
                          f"Venice Batch: {venice_batch}) ---")

    _logger = CSVLogger(mode=mode)

    BAN_COOLDOWNS = [600, 1200, 2400, 3600]  # 10, 20, 40, 60 min
    MAX_BAN_RETRIES = 6
    ban_retries = 0
    processed_count = 0
    venice_queue: list[BottleTask] = []

    while True:
        if stopped():
            emit("warning", "stopped", "Run stopped by user.")
            break

        last_processed_id = load_checkpoint() if not is_cron else None
        if last_processed_id:
            emit("info", "checkpoint", f"[Checkpoint] Resuming after Bottle ID: {last_processed_id}")

        remaining = batch_size - processed_count
        if remaining <= 0:
            emit("info", "finish", f"[Batch Limit] Reached max batch size of {batch_size}. Stopping.")
            break

        if is_cron:
            bottles = live_fetch_bottles(limit=remaining, published_since=published_since)
            emit("info", "info", f"Fetched {len(bottles)} bottles published since {published_since.isoformat()}.")
        else:
            bottles = live_fetch_bottles(after_id=last_processed_id, limit=remaining)
            emit("info", "info", f"Fetched {len(bottles)} bottles (server-side filtered).")

        if not bottles:
            break

        hit_ban = False

        for bottle in bottles:
            if stopped():
                emit("warning", "stopped", "Run stopped by user.")
                break
            if processed_count >= batch_size:
                emit("info", "finish", f"[Batch Limit] Reached max batch size of {batch_size}. Stopping.")
                break

            wb_id = (bottle.get("wbId") or bottle.get("whiskybase_id") or "").strip()
            b_id = bottle.get("id")
            b_name = bottle.get("name", "")

            if not wb_id:
                emit("info", "skip", f"  -> Bottle {b_id} has no wbId. Skipping.", bottle_id=b_id)
                continue

            emit("info", "processing", f"\nProcessing Bottle ID: {b_id} ({b_name}) [WB ID: {wb_id}]",
                 bottle_id=b_id, bottle_name=b_name)

            existing_desc = bottle.get("description")
            has_desc = bool(existing_desc and isinstance(existing_desc, dict) and any(existing_desc.values()))
            has_t1 = bottle.get("tasting_note_1") is not None
            has_t2 = bottle.get("tasting_note_2") is not None

            if has_desc and has_t1 and has_t2:
                emit("info", "skip", "  -> Already complete. Skipping.", bottle_id=b_id, bottle_name=b_name)
                _logger.log(b_id, wb_id, b_name, "[already had data]", "[already had data]", "[already had data]")
                if save_cp:
                    save_cp(b_id)
                processed_count += 1
                continue

            try:
                random_delay(12.0, 20.0)
                if stopped():
                    emit("warning", "stopped", "Run stopped by user.")
                    break

                emit("info", "scraping", "  -> Scraping WhiskyBase...", bottle_id=b_id, bottle_name=b_name)
                wb_data = scrape_bottle_data(wb_id)
                reviews_text = wb_data.get("description_en_raw") or ""
                tasting_tags = wb_data.get("tasting_tags", [])

                emit("info", "info", f"  -> Tags scraped: {tasting_tags}", bottle_id=b_id, bottle_name=b_name)
                if reviews_text:
                    preview = reviews_text[:500].replace("\n", " ")
                    suffix = "..." if len(reviews_text) > 500 else ""
                    emit("info", "info", f"  -> Review text ({len(reviews_text)} chars): {preview}{suffix}",
                         bottle_id=b_id, bottle_name=b_name)
                else:
                    emit("warning", "info", "  -> No review text found on WhiskyBase.",
                         bottle_id=b_id, bottle_name=b_name)

                task = BottleTask(
                    bottle_id=b_id, wb_id=wb_id, document_id=bottle.get("documentId", ""),
                    name=b_name, has_description=has_desc, has_tasting_1=has_t1,
                    has_tasting_2=has_t2, reviews_text=reviews_text,
                    metadata=extract_metadata(bottle), tasting_tags=tasting_tags,
                )
                build_payload(task, emit)

                needs_desc = (not has_desc) and bool(reviews_text)
                if not needs_desc:
                    if not has_desc and not reviews_text:
                        emit("warning", "skip",
                             "  -> No reviews found on WhiskyBase — skipping description.",
                             bottle_id=b_id, bottle_name=b_name)
                    # Flush immediately: no description needed
                    flush_venice_queue([task], emit, _logger.log, save_cp, batch_size=1)
                    processed_count += 1
                    ban_retries = 0
                    continue

                venice_queue.append(task)
                processed_count += 1
                ban_retries = 0
                if len(venice_queue) >= venice_batch:
                    flush_venice_queue(venice_queue, emit, _logger.log, save_cp, venice_batch)

            except (ScrapeBanException, ScrapeHardBanException, TenacityRetryError) as e:
                ban_retries += 1
                _logger.log(b_id, wb_id, b_name, "[ban]", "[ban]", "[ban]")
                # Flush any queued Venice writes before cooldown so work isn't lost
                flush_venice_queue(venice_queue, emit, _logger.log, save_cp, venice_batch)
                close_session()

                if ban_retries > MAX_BAN_RETRIES:
                    emit("error", "ban", f"\n[FATAL] Banned {MAX_BAN_RETRIES} times. Stopping permanently.")
                    break
                cooldown = BAN_COOLDOWNS[min(ban_retries - 1, len(BAN_COOLDOWNS) - 1)]
                emit("warning", "ban", f"\n[BAN] WhiskyBase ban detected: {e}",
                     bottle_id=b_id, bottle_name=b_name)
                emit("info", "ban",
                     f"[BAN] Closing browser & waiting {cooldown // 60} min before retry "
                     f"({ban_retries}/{MAX_BAN_RETRIES})...")
                time.sleep(cooldown)
                emit("info", "ban", "[BAN] Cooldown complete. Resuming from checkpoint...")
                hit_ban = True
                break

            except Exception as e:
                emit("error", "error",
                     f"\n[FATAL ERROR] Unexpected error on bottle {b_id}: {e}. Halting scraper.",
                     bottle_id=b_id, bottle_name=b_name)
                _logger.log(b_id, wb_id, b_name, "[error]", "[error]", "[error]")
                flush_venice_queue(venice_queue, emit, _logger.log, save_cp, venice_batch)
                close_session()
                break

        # Flush any remaining queued Venice writes at end of this fetch page
        flush_venice_queue(venice_queue, emit, _logger.log, save_cp, venice_batch)

        if not hit_ban:
            break

    _logger.close()
    emit("info", "finish", f"\n--- Scraper Engine Finished ({processed_count} bottles processed) ---")
    emit("info", "finish", f"CSV log saved to: {_logger.filepath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spiritory Whisky Scraper — full backfill mode")
    parser.add_argument("--batch", type=int, default=100, help="Bottles per run")
    parser.add_argument("--venice-batch", type=int, default=1,
                        help="Bottles per Venice call (1 = per-bottle, N>1 = batched)")
    parser.add_argument("--reset-checkpoint", action="store_true",
                        help="Clear the checkpoint before running")
    args = parser.parse_args()

    if args.reset_checkpoint:
        import os
        if os.path.exists("scraper_state.json"):
            os.remove("scraper_state.json")
            print("[Checkpoint] Cleared.")

    run_scraper(batch_size=args.batch, venice_batch=args.venice_batch)
