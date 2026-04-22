"""Tests for cron_daily scheduling + SIGTERM plumbing."""

import threading
from datetime import datetime, timedelta, timezone
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


def test_run_cron_cycle_passes_stop_event_to_scraper(monkeypatch):
    """Regression guard: the cron cycle must forward the shared stop event
    and the venice_batch flag into run_scraper."""
    captured = {}
    def _fake_run(**kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(cron_daily, "run_scraper", _fake_run)
    cron_daily._STOP.clear()
    cron_daily.run_cron_cycle(batch_size=50, venice_batch=3)
    assert captured["stop_event"] is cron_daily._STOP
    assert captured["venice_batch"] == 3
    assert captured["batch_size"] == 50
    assert captured["published_since"] is not None
    # published_since should be ~24h before now
    delta = datetime.now(timezone.utc) - captured["published_since"]
    assert timedelta(hours=23, minutes=55) < delta < timedelta(hours=24, minutes=5)


def test_run_cron_cycle_swallows_scraper_errors(monkeypatch, capsys):
    def _boom(**kwargs):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(cron_daily, "run_scraper", _boom)
    cron_daily._STOP.clear()
    # Must not propagate — daemon survives to next day
    cron_daily.run_cron_cycle(batch_size=1)
    captured = capsys.readouterr()
    assert "ERROR during scraper run" in captured.out
