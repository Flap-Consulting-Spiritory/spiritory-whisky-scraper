import argparse
import warnings
warnings.filterwarnings("ignore", message=".*google.generativeai.*")
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime
from integrations.strapi import fetch_bottles as live_fetch_bottles, update_bottle as live_update_bottle
from integrations.whiskybase import scrape_bottle_data, ScrapeBanException, ScrapeHardBanException, close_session
from tenacity import RetryError as TenacityRetryError
import time
from utils.gemini import generate_description
from utils.tasting_tags import normalize_tag
from checkpoint_manager import load_checkpoint, save_checkpoint
from utils.jitter import random_delay
from utils.csv_logger import CSVLogger


def run_scraper(
    batch_size: int = 100,
    published_since: datetime | None = None,
    event_callback=None,
    stop_event=None,
):
    """
    Run the scraper pipeline.

    Args:
        batch_size: Maximum number of bottles to process.
        published_since: If set, only process bottles published after this datetime
            (cron mode — time-based filter). If None, uses ID-based checkpoint resume
            (full backfill mode).
        event_callback: Optional callable(event: dict) invoked for key events.
            event keys: ts, level, type, bottle_id, bottle_name, msg
        stop_event: Optional threading.Event; if set(), the loop exits gracefully.
    """
    from datetime import datetime as _dt

    def emit(level: str, event_type: str, message: str, bottle_id=None, bottle_name=None):
        print(message)
        if event_callback:
            event_callback({
                "ts": _dt.now().strftime("%H:%M:%S"),
                "level": level,
                "type": event_type,
                "bottle_id": bottle_id,
                "bottle_name": bottle_name,
                "msg": message,
            })

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    _csv_mode = "cron" if published_since else "live"
    emit("info", "start", f"--- Starting Scraper Engine (Mode: {_csv_mode}, Batch Size: {batch_size}) ---")

    _logger = CSVLogger(mode=_csv_mode)

    # Progressive cooldowns: each ban waits longer before retrying
    BAN_COOLDOWNS = [600, 1200, 2400, 3600]  # 10, 20, 40, 60 minutes
    MAX_BAN_RETRIES = 6
    ban_retries = 0
    processed_count = 0

    while True:
        if stopped():
            emit("warning", "stopped", "Run stopped by user.")
            break

        # Load checkpoint and fetch bottles (re-fetched after each ban cooldown)
        last_processed_id = load_checkpoint()
        if last_processed_id and not published_since:
            emit("info", "checkpoint", f"[Checkpoint] Resuming after Bottle ID: {last_processed_id}")

        remaining = batch_size - processed_count
        if remaining <= 0:
            emit("info", "finish", f"[Batch Limit] Reached max batch size of {batch_size}. Stopping.")
            break

        if published_since:
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

            wb_id = (bottle.get('wbId') or bottle.get('whiskybase_id') or '').strip()
            if not wb_id:
                emit("info", "skip", f"  -> Bottle {bottle.get('id')} has no wbId. Skipping.",
                     bottle_id=bottle.get('id'))
                continue

            b_id = bottle.get('id')
            b_name = bottle.get('name', '')
            emit("info", "processing", f"\nProcessing Bottle ID: {b_id} ({b_name}) [WB ID: {wb_id}]",
                 bottle_id=b_id, bottle_name=b_name)

            # Check what's already populated
            existing_desc = bottle.get('description')
            has_description = bool(existing_desc and isinstance(existing_desc, dict) and any(existing_desc.values()))
            has_tasting_1 = bottle.get('tasting_note_1') is not None
            has_tasting_2 = bottle.get('tasting_note_2') is not None

            if has_description and has_tasting_1 and has_tasting_2:
                emit("info", "skip", "  -> Already complete (description + tasting notes). Skipping.",
                     bottle_id=b_id, bottle_name=b_name)
                _logger.log(b_id, wb_id, b_name, "[already had data]", "[already had data]", "[already had data]")
                save_checkpoint(bottle['id'])
                processed_count += 1
                continue

            try:
                random_delay(12.0, 20.0)

                if stopped():
                    emit("warning", "stopped", "Run stopped by user.")
                    break

                # 1. Scrape WhiskyBase: top 2 reviews + top 2 tasting tags
                emit("info", "scraping", "  -> Scraping WhiskyBase...", bottle_id=b_id, bottle_name=b_name)
                wb_data = scrape_bottle_data(wb_id)

                reviews_text = wb_data.get("description_en_raw") or ""
                tasting_tags = wb_data.get("tasting_tags", [])

                emit("info", "info", f"  -> Tags scraped: {tasting_tags}",
                     bottle_id=b_id, bottle_name=b_name)
                if reviews_text:
                    preview = reviews_text[:500].replace('\n', ' ')
                    suffix = "..." if len(reviews_text) > 500 else ""
                    emit("info", "info", f"  -> Review text ({len(reviews_text)} chars): {preview}{suffix}",
                         bottle_id=b_id, bottle_name=b_name)
                else:
                    emit("warning", "info", "  -> No review text found on WhiskyBase.",
                         bottle_id=b_id, bottle_name=b_name)

                # 2. Build payload — only include fields that are missing AND have source data
                strapi_payload: dict = {}

                if not has_description:
                    if reviews_text:
                        emit("info", "generating", "  -> Generating description via Gemini...",
                             bottle_id=b_id, bottle_name=b_name)
                        description = generate_description(reviews_text, bottle.get('name', ''))
                        if description and any(description.values()):
                            strapi_payload["description"] = description
                    else:
                        emit("warning", "skip", "  -> No reviews found on WhiskyBase — skipping description.",
                             bottle_id=b_id, bottle_name=b_name)

                if tasting_tags:
                    valid_tags = [t for t in tasting_tags if normalize_tag(t)]
                    skipped_tags = [t for t in tasting_tags if not normalize_tag(t)]
                    if skipped_tags:
                        emit("warning", "skip",
                             f"  -> Tasting tags not in Strapi enum (skipped): {skipped_tags}",
                             bottle_id=b_id, bottle_name=b_name)
                    if not has_tasting_1 and len(valid_tags) >= 1:
                        strapi_payload["tasting_note_1"] = normalize_tag(valid_tags[0])
                    if not has_tasting_2 and len(valid_tags) >= 2:
                        strapi_payload["tasting_note_2"] = normalize_tag(valid_tags[1])

                # Compute CSV log cell values (used in all paths below)
                if has_description:
                    _desc_cell = "[already had data]"
                elif "description" in strapi_payload:
                    _desc_cell = strapi_payload["description"].get("en", "")[:500]
                else:
                    _desc_cell = "[no wb data]"

                if has_tasting_1:
                    _t1_cell = "[already had data]"
                elif "tasting_note_1" in strapi_payload:
                    _t1_cell = strapi_payload["tasting_note_1"]
                else:
                    _t1_cell = "[no wb data]"

                if has_tasting_2:
                    _t2_cell = "[already had data]"
                elif "tasting_note_2" in strapi_payload:
                    _t2_cell = strapi_payload["tasting_note_2"]
                else:
                    _t2_cell = "[no wb data]"

                if not strapi_payload:
                    emit("info", "skip", "  -> Nothing to update. Skipping.",
                         bottle_id=b_id, bottle_name=b_name)
                    _logger.log(b_id, wb_id, b_name, _desc_cell, _t1_cell, _t2_cell)
                    save_checkpoint(bottle['id'])
                    processed_count += 1
                    continue

                # 3. Update Strapi
                live_update_bottle(bottle.get('documentId', ''), strapi_payload)
                fields_written = list(strapi_payload.keys())
                emit("info", "writing", f"  -> Updated: {', '.join(fields_written)}",
                     bottle_id=b_id, bottle_name=b_name)

                # Emit actual values written
                if "description" in strapi_payload:
                    desc = strapi_payload["description"]
                    for lang in ("en", "de", "es", "fr", "it"):
                        val = desc.get(lang, "")
                        if val:
                            emit("info", "writing_detail", f"     description[{lang}]: {val}",
                                 bottle_id=b_id, bottle_name=b_name)
                if "tasting_note_1" in strapi_payload and strapi_payload["tasting_note_1"]:
                    emit("info", "writing_detail", f"     tasting_note_1: {strapi_payload['tasting_note_1']}",
                         bottle_id=b_id, bottle_name=b_name)
                if "tasting_note_2" in strapi_payload and strapi_payload["tasting_note_2"]:
                    emit("info", "writing_detail", f"     tasting_note_2: {strapi_payload['tasting_note_2']}",
                         bottle_id=b_id, bottle_name=b_name)

                _logger.log(b_id, wb_id, b_name, _desc_cell, _t1_cell, _t2_cell)
                save_checkpoint(bottle['id'])
                processed_count += 1

                # Reset ban counter on successful scrape
                ban_retries = 0

            except (ScrapeBanException, ScrapeHardBanException, TenacityRetryError) as e:
                ban_retries += 1
                _logger.log(b_id, wb_id, b_name, "[ban]", "[ban]", "[ban]")
                close_session()

                if ban_retries > MAX_BAN_RETRIES:
                    emit("error", "ban", f"\n[FATAL] Banned {MAX_BAN_RETRIES} times. Stopping permanently.")
                    break

                cooldown = BAN_COOLDOWNS[min(ban_retries - 1, len(BAN_COOLDOWNS) - 1)]
                emit("warning", "ban", f"\n[BAN] WhiskyBase ban detected: {e}",
                     bottle_id=b_id, bottle_name=b_name)
                emit("info", "ban",
                     f"[BAN] Closing browser & waiting {cooldown // 60} min before retry ({ban_retries}/{MAX_BAN_RETRIES})...")
                time.sleep(cooldown)
                emit("info", "ban", "[BAN] Cooldown complete. Resuming from checkpoint...")
                hit_ban = True
                break  # break for-loop → outer while re-fetches from checkpoint

            except Exception as e:
                emit("error", "error", f"\n[FATAL ERROR] Unexpected error on bottle {bottle.get('id')}: {e}. Halting scraper.",
                     bottle_id=b_id, bottle_name=b_name)
                _logger.log(b_id, wb_id, b_name, "[error]", "[error]", "[error]")
                close_session()
                break # break for-loop to stop scraping completely on unhandled exceptions

        # If we didn't hit a ban, we're done (all bottles processed, stopped, or batch limit)
        if not hit_ban:
            break

    _logger.close()
    emit("info", "finish", f"\n--- Scraper Engine Finished ({processed_count} bottles processed) ---")
    emit("info", "finish", f"CSV log saved to: {_logger.filepath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spiritory Whisky Scraper — full backfill mode")
    parser.add_argument("--batch", type=int, default=100, help="Number of bottles to process per run")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Clear the checkpoint before running")
    args = parser.parse_args()

    if args.reset_checkpoint:
        import os
        if os.path.exists("scraper_state.json"):
            os.remove("scraper_state.json")
            print("[Checkpoint] Cleared.")

    run_scraper(batch_size=args.batch)
