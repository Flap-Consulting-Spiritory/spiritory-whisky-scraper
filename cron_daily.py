"""
cron_daily.py — Daily cron daemon for Spiritoni Whisky Scraper.

Runs as a long-lived background process. At the configured UTC time each day
(default: 00:00), fetches all bottles published in the last 24 hours, runs the
full pipeline (WhiskyBase scrape → Gemini description → Strapi write), and saves
a CSV report to logs/.

Usage:
    python cron_daily.py                         # midnight UTC (default)
    python cron_daily.py --hour 6 --minute 30    # 06:30 UTC
    python cron_daily.py --run-now               # fire immediately, then enter schedule
    nohup python cron_daily.py > logs/cron.log 2>&1 &   # background production

Environment (optional overrides):
    CRON_HOUR    int 0-23   trigger hour   (default: 0)
    CRON_MINUTE  int 0-59   trigger minute (default: 0)
"""

import argparse
import os
import signal
import sys
import time
import warnings

warnings.filterwarnings("ignore", message=".*pkg_resources.*")
warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from dotenv import load_dotenv
load_dotenv()

# Compatibility shim: playwright-stealth requires pkg_resources (deprecated since setuptools 81)
try:
    import pkg_resources  # type: ignore
except ImportError:
    import importlib.resources
    class MockPkgResources:
        @staticmethod
        def resource_string(package, resource_name):
            return importlib.resources.files(package).joinpath(resource_name).read_bytes()
    sys.modules['pkg_resources'] = MockPkgResources()  # type: ignore

    import importlib.metadata
    importlib.metadata.resource_string = MockPkgResources.resource_string  # type: ignore

from datetime import datetime, timedelta, timezone

from scraper_engine import run_scraper

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_SHUTDOWN = False


def _handle_sigterm(signum, frame):
    global _SHUTDOWN
    print("\n[Cron] SIGTERM received. Will shut down after current run completes.", flush=True)
    _SHUTDOWN = True


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def next_trigger_dt(hour: int, minute: int) -> datetime:
    """Return the next UTC datetime at HH:MM that is strictly in the future."""
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def sleep_until(target: datetime) -> None:
    """Sleep in 60-second intervals until target UTC time, checking _SHUTDOWN each tick."""
    global _SHUTDOWN
    while not _SHUTDOWN:
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(60.0, remaining))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_cron_cycle(batch_size: int) -> None:
    """Execute one daily pipeline run: fetch last-24h bottles and process them."""
    now_utc = datetime.now(timezone.utc)
    published_since = now_utc - timedelta(hours=24)

    print(
        f"\n[Cron] === Daily run triggered at {now_utc.isoformat(timespec='seconds')} UTC ===",
        flush=True,
    )
    print(
        f"[Cron] Fetching bottles published since: {published_since.isoformat(timespec='seconds')} UTC",
        flush=True,
    )

    try:
        run_scraper(batch_size=batch_size, published_since=published_since)
    except Exception as e:
        print(f"[Cron] ERROR during scraper run: {e}", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily cron daemon for Spiritoni Whisky Scraper"
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=int(os.environ.get("CRON_HOUR", 0)),
        help="UTC hour to trigger daily run (0-23, default: 0)",
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=int(os.environ.get("CRON_MINUTE", 0)),
        help="UTC minute to trigger daily run (0-59, default: 0)",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=500,
        help="Max bottles to process per daily run (default: 500)",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Fire the pipeline immediately before entering the normal schedule",
    )
    args = parser.parse_args()

    print(
        f"[Cron] Daemon started. Trigger: {args.hour:02d}:{args.minute:02d} UTC daily. "
        f"Batch size: {args.batch}. Send SIGTERM to shut down cleanly.",
        flush=True,
    )

    if args.run_now:
        print("[Cron] --run-now: firing immediately.", flush=True)
        run_cron_cycle(batch_size=args.batch)

    while not _SHUTDOWN:
        trigger = next_trigger_dt(args.hour, args.minute)
        wait_h = (trigger - datetime.now(timezone.utc)).total_seconds() / 3600
        print(
            f"[Cron] Next run scheduled for {trigger.isoformat(timespec='seconds')} UTC "
            f"({wait_h:.1f}h from now).",
            flush=True,
        )
        sleep_until(trigger)

        if _SHUTDOWN:
            break

        run_cron_cycle(batch_size=args.batch)

    print("[Cron] Daemon exited cleanly.", flush=True)


if __name__ == "__main__":
    main()
