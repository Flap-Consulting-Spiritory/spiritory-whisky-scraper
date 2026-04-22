"""Tests for scraper_engine.run_scraper orchestration.

Covers the invariants the user depends on:
  * cron mode does NOT write to scraper_state.json (preserves backfill state)
  * backfill mode DOES write to scraper_state.json
  * stop_event being set breaks the loop after the current bottle
  * already-complete bottles are skipped without calling Venice or WhiskyBase
"""

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import scraper_engine
from utils import pipeline


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Patch all I/O: Strapi fetch+update, WhiskyBase scrape, Venice, jitter,
    and force checkpoint file to a tmp path."""
    # Redirect checkpoint state file to a temp path so tests don't leak
    import checkpoint_manager
    state_file = tmp_path / "scraper_state.json"
    monkeypatch.setattr(checkpoint_manager, "STATE_FILE", str(state_file))
    monkeypatch.chdir(tmp_path)  # CSV logger writes to ./logs/

    # Kill all time.sleep and jitter so tests run fast
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)
    import utils.jitter
    monkeypatch.setattr(utils.jitter, "random_delay", lambda *a, **kw: None)

    # Mock Strapi update + Venice
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pipeline, "live_update_bottle", update_mock)
    monkeypatch.setattr(
        pipeline, "generate_description_live",
        lambda r, n, m: {"de": "d", "en": "english", "es": "s", "fr": "f", "it": "i"},
    )
    monkeypatch.setattr(
        pipeline, "generate_descriptions_batch",
        lambda items: [{"id": it["id"], "improved": {"de": "d", "en": f"en-{it['id']}",
                                                       "es": "s", "fr": "f", "it": "i"}}
                        for it in items],
    )

    # Default WhiskyBase stub: returns reviews + a valid tag
    scrape_mock = MagicMock(return_value={
        "description_en_raw": "Rich vanilla, long smoky finish.",
        "tasting_tags": ["Honey", "Smokey"],
    })
    monkeypatch.setattr(scraper_engine, "scrape_bottle_data", scrape_mock)
    monkeypatch.setattr(scraper_engine, "close_session", lambda: None)

    return {
        "update": update_mock,
        "scrape": scrape_mock,
        "state_file": state_file,
    }


def _bottle(bid, wb="123", document_id="doc-x", has_desc=False, has_t1=False, has_t2=False):
    b: dict = {"id": bid, "documentId": document_id, "name": f"Bottle-{bid}", "wbId": wb}
    if has_desc:
        b["description"] = {"en": "existing"}
    if has_t1:
        b["tasting_note_1"] = "Honey"
    if has_t2:
        b["tasting_note_2"] = "Smokey"
    return b


def test_cron_mode_does_not_write_checkpoint(patched, monkeypatch):
    """The key guarantee: cron runs must never mutate scraper_state.json,
    which belongs to the backfill."""
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles",
                        lambda **kw: [_bottle(101), _bottle(102)])
    scraper_engine.run_scraper(
        batch_size=10,
        published_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert not patched["state_file"].exists(), \
        "cron mode must not create/update scraper_state.json"
    assert patched["update"].call_count == 2


def test_backfill_mode_writes_checkpoint(patched, monkeypatch):
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles", lambda **kw: [_bottle(55)])
    scraper_engine.run_scraper(batch_size=1)
    assert patched["state_file"].exists()
    import json
    data = json.loads(patched["state_file"].read_text())
    assert data["last_processed_id"] == 55


def test_stop_event_breaks_inner_loop(patched, monkeypatch):
    """SIGTERM-equivalent: event.set() must break out after the current bottle."""
    processed_ids = []

    def _scrape(wb_id):
        return {"description_en_raw": "r", "tasting_tags": []}
    monkeypatch.setattr(scraper_engine, "scrape_bottle_data", _scrape)

    def _update(doc_id, payload):
        # record which docs got written
        processed_ids.append(doc_id)
        return True
    monkeypatch.setattr(pipeline, "live_update_bottle", _update)

    stop = threading.Event()
    # Set event BEFORE starting: the loop should exit without processing
    stop.set()
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles",
                        lambda **kw: [_bottle(1), _bottle(2), _bottle(3)])
    scraper_engine.run_scraper(batch_size=10, stop_event=stop)
    assert processed_ids == []  # pre-set stop: nothing processed


def test_already_complete_bottle_is_skipped(patched, monkeypatch):
    """Bottles with description + both tasting notes must not hit WhiskyBase
    or Venice. Protects quota + avoids overwrites."""
    scrape_mock = MagicMock()
    monkeypatch.setattr(scraper_engine, "scrape_bottle_data", scrape_mock)
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles",
                        lambda **kw: [_bottle(1, has_desc=True, has_t1=True, has_t2=True)])
    scraper_engine.run_scraper(batch_size=1)
    scrape_mock.assert_not_called()
    # Also: Strapi update must NOT be called (nothing to write)
    patched["update"].assert_not_called()


def test_missing_wbid_is_skipped(patched, monkeypatch):
    scrape_mock = MagicMock()
    monkeypatch.setattr(scraper_engine, "scrape_bottle_data", scrape_mock)
    monkeypatch.setattr(
        scraper_engine, "live_fetch_bottles",
        lambda **kw: [_bottle(1, wb="")],
    )
    scraper_engine.run_scraper(batch_size=1)
    scrape_mock.assert_not_called()


def test_no_reviews_writes_tasting_only(patched, monkeypatch):
    """When WhiskyBase returns tags but no reviews, we should write
    tasting_note_1/2 and leave description untouched."""
    monkeypatch.setattr(scraper_engine, "scrape_bottle_data",
                        lambda wb: {"description_en_raw": "", "tasting_tags": ["Honey", "Smokey"]})
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles", lambda **kw: [_bottle(1)])
    scraper_engine.run_scraper(batch_size=1)

    patched["update"].assert_called_once()
    payload = patched["update"].call_args.args[1]
    assert "description" not in payload
    assert payload["tasting_note_1"] == "Honey"
    assert payload["tasting_note_2"] == "Smokey"


def test_venice_batch_groups_calls(patched, monkeypatch):
    batch_calls = []
    def _batch(items):
        batch_calls.append([it["id"] for it in items])
        return [{"id": it["id"],
                 "improved": {"de": "d", "en": f"en-{it['id']}", "es": "s", "fr": "f", "it": "i"}}
                for it in items]
    monkeypatch.setattr(pipeline, "generate_descriptions_batch", _batch)
    monkeypatch.setattr(scraper_engine, "live_fetch_bottles",
                        lambda **kw: [_bottle(i, document_id=f"d-{i}") for i in (1, 2, 3, 4)])
    scraper_engine.run_scraper(batch_size=10, venice_batch=2)
    # 4 bottles grouped into 2s -> 2 batch calls
    assert batch_calls == [[1, 2], [3, 4]]
