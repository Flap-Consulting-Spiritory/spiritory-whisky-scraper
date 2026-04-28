"""cron_daily.py — Daily cron daemon for Spiritory Whisky Scraper.

Runs as a long-lived background process. At the configured UTC time each day
(default: 00:00), fetches all bottles created during the previous UTC calendar
day, runs the full pipeline (WhiskyBase scrape → Venice description → Strapi
write), and appends a row per bottle to `logs/scraper.csv` (mode=cron).

Shutdown is graceful: SIGTERM flips a `threading.Event` that both the
scheduler and the scraper loop check, so a running batch stops after the
current bottle instead of finishing all 500.

Usage:
    python cron_daily.py                         # midnight UTC (default)
    python cron_daily.py --hour 6 --minute 30    # 06:30 UTC
    python cron_daily.py --run-now               # fire immediately, then enter schedule
    python cron_daily.py --venice-batch 5        # group 5 bottles per Venice call
    nohup python cron_daily.py > logs/cron.log 2>&1 &   # background production

Environment (optional overrides):
    CRON_HOUR    int 0-23   trigger hour   (default: 0)
    CRON_MINUTE  int 0-59   trigger minute (default: 0)
    VENICE_MODEL override Venice model id (default: gemini-3-flash-preview)
"""

import argparse
import csv
import os
import signal
import threading
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from dotenv import load_dotenv
load_dotenv()

from scraper_engine import run_scraper

# Single shared event: SIGTERM sets it, both the scheduler sleep loop and the
# scraper's inner loop check .is_set() to abort promptly.
_STOP = threading.Event()


def _handle_sigterm(signum, frame):
    print("\n[Cron] SIGTERM received. Will shut down after current bottle finishes.", flush=True)
    _STOP.set()


signal.signal(signal.SIGTERM, _handle_sigterm)


def next_trigger_dt(hour: int, minute: int, now: datetime | None = None) -> datetime:
    """Return the next UTC datetime at HH:MM that is strictly in the future.

    `now` is injectable for tests.
    """
    now = now or datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def sleep_until(target: datetime) -> None:
    """Sleep in 60-second intervals until target UTC time, returning early if
    the stop event is set."""
    while not _STOP.is_set():
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        # Prefer Event.wait (interruptible) over time.sleep so SIGTERM exits
        # the sleep immediately rather than waiting up to 60s.
        if _STOP.wait(timeout=min(60.0, remaining)):
            return


def target_day_for_run(now: datetime | None = None) -> date:
    """Return the closed UTC day this run should process."""
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    return now_utc.date() - timedelta(days=1)


def day_window_utc(target_day: date) -> tuple[datetime, datetime]:
    """Return [start, end) UTC datetimes for a calendar day."""
    start = datetime(target_day.year, target_day.month, target_day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def build_run_id(started_at: datetime, target_day: date, trigger: str) -> str:
    safe_trigger = "".join(ch if ch.isalnum() else "-" for ch in trigger).strip("-")
    return f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{target_day.isoformat()}-{safe_trigger}"


def append_run_report(row: dict, filepath: str = "logs/runs.csv") -> None:
    """Append a one-row-per-run summary for presentation/auditing."""
    columns = [
        "run_id",
        "trigger",
        "started_at",
        "finished_at",
        "target_date",
        "window_start",
        "window_end",
        "batch_limit",
        "venice_batch",
        "status",
        "fetched_count",
        "processed_count",
        "skipped_complete_count",
        "skipped_missing_wbid_count",
        "scraped_count",
        "ban_count",
        "error_count",
        "error_message",
        "scraper_csv",
    ]
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_cron_cycle(
    batch_size: int,
    venice_batch: int = 1,
    target_day: date | None = None,
    trigger: str = "manual_api",
) -> None:
    """Execute one daily pipeline run for a closed UTC createdAt day."""
    started_at = datetime.now(timezone.utc)
    target_day = target_day or target_day_for_run(started_at)
    created_since, created_until = day_window_utc(target_day)
    run_id = build_run_id(started_at, target_day, trigger)

    print(
        f"\n[Cron] === Run started: run_id={run_id} trigger={trigger} "
        f"started_at={started_at.isoformat(timespec='seconds')} UTC ===",
        flush=True,
    )
    print(
        f"[Cron] Scope: target_date={target_day.isoformat()} UTC, "
        f"createdAt_window=[{created_since.isoformat(timespec='seconds')}, "
        f"{created_until.isoformat(timespec='seconds')}), "
        f"batch_limit={batch_size}, venice_batch={venice_batch}.",
        flush=True,
    )
    print(
        "[Cron] Reports: logs/runs.csv is one row per run; "
        "logs/scraper.csv is cumulative per bottle across all runs.",
        flush=True,
    )

    stats = {
        "run_id": run_id,
        "status": "error",
        "fetched_count": 0,
        "processed_count": 0,
        "skipped_complete_count": 0,
        "skipped_missing_wbid_count": 0,
        "scraped_count": 0,
        "ban_count": 0,
        "error_count": 1,
        "error_message": "",
        "scraper_csv": "logs/scraper.csv",
    }
    try:
        result = run_scraper(
            batch_size=batch_size,
            created_since=created_since,
            created_until=created_until,
            stop_event=_STOP,
            venice_batch=venice_batch,
            run_context={
                "run_id": run_id,
                "trigger": trigger,
                "target_date": target_day.isoformat(),
                "window_start": created_since.isoformat(timespec="seconds"),
                "window_end": created_until.isoformat(timespec="seconds"),
            },
        )
        if result:
            stats.update(result)
    except Exception as e:
        stats["error_message"] = str(e)
        print(f"[Cron] ERROR during scraper run: {e}", flush=True)
    finally:
        finished_at = datetime.now(timezone.utc)
        report_row = {
            **stats,
            "run_id": run_id,
            "trigger": trigger,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "target_date": target_day.isoformat(),
            "window_start": created_since.isoformat(timespec="seconds"),
            "window_end": created_until.isoformat(timespec="seconds"),
            "batch_limit": batch_size,
            "venice_batch": venice_batch,
        }
        append_run_report(report_row)
        print(
            f"[Cron] === Run finished: run_id={run_id} status={report_row['status']} "
            f"target_date={target_day.isoformat()} fetched={report_row['fetched_count']} "
            f"processed={report_row['processed_count']} "
            f"already_complete={report_row['skipped_complete_count']} "
            f"scraped={report_row['scraped_count']} errors={report_row['error_count']} ===",
            flush=True,
        )
        print("[Cron] Run summary saved to: logs/runs.csv", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily cron daemon for Spiritory Whisky Scraper")
    parser.add_argument("--hour", type=int, default=int(os.environ.get("CRON_HOUR", 0)),
                        help="UTC hour to trigger daily run (0-23, default: 0)")
    parser.add_argument("--minute", type=int, default=int(os.environ.get("CRON_MINUTE", 0)),
                        help="UTC minute to trigger daily run (0-59, default: 0)")
    parser.add_argument("--batch", type=int, default=500,
                        help="Max bottles to process per daily run (default: 500)")
    parser.add_argument("--venice-batch", type=int, default=1,
                        help="Bottles per Venice call (default: 1 = per-bottle)")
    parser.add_argument("--run-now", action="store_true",
                        help="Fire the pipeline immediately before entering the normal schedule")
    parser.add_argument("--target-date", type=str, default=None,
                        help="UTC date YYYY-MM-DD to process with --run-now (default: yesterday UTC)")
    args = parser.parse_args()

    if args.target_date and not args.run_now:
        parser.error("--target-date is only valid together with --run-now")

    target_date = None
    if args.target_date:
        try:
            target_date = date.fromisoformat(args.target_date)
        except ValueError:
            parser.error("--target-date must use YYYY-MM-DD")

    print(
        f"[Cron] Daemon started. Trigger: {args.hour:02d}:{args.minute:02d} UTC daily. "
        f"Batch: {args.batch}. Venice batch: {args.venice_batch}. "
        f"Send SIGTERM to shut down cleanly.",
        flush=True,
    )

    if args.run_now:
        print("[Cron] --run-now: firing immediately.", flush=True)
        run_cron_cycle(
            batch_size=args.batch,
            venice_batch=args.venice_batch,
            target_day=target_date,
            trigger="manual_cli",
        )

    while not _STOP.is_set():
        trigger = next_trigger_dt(args.hour, args.minute)
        wait_h = (trigger - datetime.now(timezone.utc)).total_seconds() / 3600
        print(
            f"[Cron] Next run scheduled for {trigger.isoformat(timespec='seconds')} UTC "
            f"({wait_h:.1f}h from now).",
            flush=True,
        )
        sleep_until(trigger)
        if _STOP.is_set():
            break
        run_cron_cycle(batch_size=args.batch, venice_batch=args.venice_batch, trigger="scheduled")

    print("[Cron] Daemon exited cleanly.", flush=True)


if __name__ == "__main__":
    main()
