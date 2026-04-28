"""Tests for cron_daily scheduling + SIGTERM plumbing."""

import threading
import csv
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import cron_daily


def _now_utc():
    return datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_next_trigger_skips_to_tomorrow_when_time_already_passed():
    # now is 12:00; schedule is 06:00 -> next is tomorrow at 06:00
    trigger = cron_daily.next_trigger_dt(hour=6, minute=0, now=_now_utc())
    assert trigger == datetime(2026, 3, 16, 6, 0, tzinfo=timezone.utc)


def test_next_trigger_same_day_if_in_future():
    # now is 12:00; schedule is 18:00 -> later today
    trigger = cron_daily.next_trigger_dt(hour=18, minute=0, now=_now_utc())
    assert trigger == datetime(2026, 3, 15, 18, 0, tzinfo=timezone.utc)


def test_next_trigger_tomorrow_if_same_minute_now():
    # Exact same time as now: must be tomorrow (strictly in future)
    trigger = cron_daily.next_trigger_dt(hour=12, minute=0, now=_now_utc())
    assert trigger == datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)


def test_target_day_for_run_uses_previous_utc_day():
    target = cron_daily.target_day_for_run(datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc))
    assert target == date(2026, 3, 14)


def test_day_window_utc_returns_closed_day_bounds():
    start, end = cron_daily.day_window_utc(date(2026, 3, 14))
    assert start == datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)


def test_build_run_id_includes_target_date_and_trigger():
    run_id = cron_daily.build_run_id(
        datetime(2026, 3, 15, 12, 30, 45, tzinfo=timezone.utc),
        date(2026, 3, 14),
        "manual api",
    )
    assert run_id == "20260315T123045Z-2026-03-14-manual-api"


def test_append_run_report_writes_one_row_per_run(tmp_path):
    path = tmp_path / "runs.csv"
    cron_daily.append_run_report({
        "run_id": "run-1",
        "trigger": "manual_api",
        "started_at": "2026-03-15T12:00:00+00:00",
        "finished_at": "2026-03-15T12:01:00+00:00",
        "target_date": "2026-03-14",
        "window_start": "2026-03-14T00:00:00+00:00",
        "window_end": "2026-03-15T00:00:00+00:00",
        "batch_limit": 1,
        "venice_batch": 1,
        "status": "completed",
        "fetched_count": 0,
        "processed_count": 0,
        "skipped_complete_count": 0,
        "skipped_missing_wbid_count": 0,
        "scraped_count": 0,
        "ban_count": 0,
        "error_count": 0,
        "error_message": "",
        "scraper_csv": "logs/scraper.csv",
    }, filepath=str(path))

    rows = list(csv.DictReader(path.open()))
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["target_date"] == "2026-03-14"


def test_sigterm_handler_sets_stop_event(monkeypatch):
    # Reset the shared event to a known state
    cron_daily._STOP.clear()
    cron_daily._handle_sigterm(15, None)  # SIGTERM
    assert cron_daily._STOP.is_set()
    # Reset so other tests aren't affected
    cron_daily._STOP.clear()


def test_sleep_until_returns_immediately_when_target_in_past():
    cron_daily._STOP.clear()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    # Should not block
    cron_daily.sleep_until(past)


def test_sleep_until_returns_when_stop_event_set():
    """sleep_until must exit promptly when stop event is set, even if the
    target is far in the future."""
    cron_daily._STOP.clear()
    # Schedule stop after a very short delay on a background thread
    def _trigger():
        import time
        time.sleep(0.05)
        cron_daily._STOP.set()
    t = threading.Thread(target=_trigger, daemon=True)
    t.start()
    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    # Must return well before the 1-day target
    start = datetime.now(timezone.utc)
    cron_daily.sleep_until(far_future)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    assert elapsed < 5, f"sleep_until took {elapsed}s — stop event not honored"
    cron_daily._STOP.clear()


def test_run_cron_cycle_passes_created_window_and_stop_event_to_scraper(monkeypatch):
    """Regression guard: the cron cycle must forward the shared stop event
    and the venice_batch flag into run_scraper."""
    captured = {}
    def _fake_run(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "fetched_count": 0, "processed_count": 0}
    monkeypatch.setattr(cron_daily, "run_scraper", _fake_run)
    report = MagicMock()
    monkeypatch.setattr(cron_daily, "append_run_report", report)
    cron_daily._STOP.clear()
    cron_daily.run_cron_cycle(
        batch_size=50,
        venice_batch=3,
        target_day=date(2026, 3, 14),
        trigger="scheduled",
    )
    assert captured["stop_event"] is cron_daily._STOP
    assert captured["venice_batch"] == 3
    assert captured["batch_size"] == 50
    assert captured["created_since"] == datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert captured["created_until"] == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    assert captured["run_context"]["target_date"] == "2026-03-14"
    assert captured["run_context"]["trigger"] == "scheduled"
    assert report.call_args.args[0]["target_date"] == "2026-03-14"
    assert report.call_args.args[0]["trigger"] == "scheduled"


def test_run_cron_cycle_swallows_scraper_errors(monkeypatch, capsys):
    def _boom(**kwargs):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(cron_daily, "run_scraper", _boom)
    report = MagicMock()
    monkeypatch.setattr(cron_daily, "append_run_report", report)
    cron_daily._STOP.clear()
    # Must not propagate — daemon survives to next day
    cron_daily.run_cron_cycle(batch_size=1)
    captured = capsys.readouterr()
    assert "ERROR during scraper run" in captured.out
    assert report.call_args.args[0]["status"] == "error"
    assert report.call_args.args[0]["error_message"] == "simulated failure"
