"""Tests for utils/pipeline.py — per-bottle helpers.

These tests mock Venice + Strapi so the pipeline can be exercised fully
without network calls.
"""

from unittest.mock import MagicMock

import pytest

from utils import pipeline
from utils.pipeline import BottleTask, build_payload, flush_venice_queue
from utils.venice import VeniceParseError, VeniceTransientError


def _task(bottle_id=1, **overrides):
    defaults = dict(
        wb_id="123",
        document_id="doc-abc",
        name="Test Whisky",
        has_description=False,
        has_tasting_1=False,
        has_tasting_2=False,
        reviews_text="Smoky, rich vanilla finish.",
        metadata={"productAge": 12},
        tasting_tags=[],
    )
    defaults.update(overrides)
    return BottleTask(bottle_id=bottle_id, **defaults)


def _noop_emit(*args, **kwargs):
    pass


def test_build_payload_adds_tasting_notes_in_order():
    task = _task(tasting_tags=["Honey", "Smokey", "Vanilla"])
    build_payload(task, _noop_emit)
    assert task.payload["tasting_note_1"] == "Honey"
    assert task.payload["tasting_note_2"] == "Smokey"


def test_build_payload_skips_already_populated_tasting_slots():
    """Slot_2 is always filled from the 2nd-ranked tag even when slot_1
    already had data — this preserves the original behavior and avoids the
    awkward case of writing the same tag into a slot whose neighbour
    already holds it."""
    task = _task(tasting_tags=["Honey", "Smokey"], has_tasting_1=True)
    build_payload(task, _noop_emit)
    assert "tasting_note_1" not in task.payload
    assert task.payload["tasting_note_2"] == "Smokey"


def test_build_payload_filters_invalid_tags():
    task = _task(tasting_tags=["NOT-A-TAG", "Honey", "ALSO-INVALID"])
    build_payload(task, _noop_emit)
    assert task.payload.get("tasting_note_1") == "Honey"
    assert "tasting_note_2" not in task.payload


# ---------------------------------------------------------------------------
# flush_venice_queue — per-bottle mode
# ---------------------------------------------------------------------------


def test_flush_single_bottle_writes_strapi_and_checkpoints(monkeypatch):
    task = _task(tasting_tags=["Honey"])
    build_payload(task, _noop_emit)

    monkeypatch.setattr(pipeline, "generate_description_live",
                        lambda r, n, m: {"de": "d", "en": "english", "es": "s", "fr": "f", "it": "i"})
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pipeline, "live_update_bottle", update_mock)

    log = MagicMock()
    save_cp = MagicMock()
    flush_venice_queue([task], _noop_emit, log, save_cp, batch_size=1)

    update_mock.assert_called_once()
    doc_id, payload = update_mock.call_args.args
    assert doc_id == "doc-abc"
    assert payload["description"]["en"] == "english"
    assert payload["tasting_note_1"] == "Honey"
    save_cp.assert_called_once_with(1)
    log.assert_called_once()


def test_flush_does_not_checkpoint_when_save_cp_is_none(monkeypatch):
    """Cron mode: save_cp=None must NOT touch the backfill checkpoint."""
    task = _task()
    build_payload(task, _noop_emit)
    monkeypatch.setattr(pipeline, "generate_description_live",
                        lambda r, n, m: {"de": "d", "en": "e", "es": "s", "fr": "f", "it": "i"})
    monkeypatch.setattr(pipeline, "live_update_bottle", lambda *a, **kw: True)
    flush_venice_queue([task], _noop_emit, MagicMock(), None, batch_size=1)
    # No exception = OK. Nothing to assert on save_cp (was None).


def test_flush_transient_error_skips_description_but_writes_tasting(monkeypatch):
    task = _task(tasting_tags=["Honey"])
    build_payload(task, _noop_emit)

    def _raise_transient(*args, **kwargs):
        raise VeniceTransientError("upstream 503 after retries")
    monkeypatch.setattr(pipeline, "generate_description_live", _raise_transient)
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pipeline, "live_update_bottle", update_mock)

    flush_venice_queue([task], _noop_emit, MagicMock(), MagicMock(), batch_size=1)

    # Tasting note still written, but description absent
    payload = update_mock.call_args.args[1]
    assert "description" not in payload
    assert payload["tasting_note_1"] == "Honey"


def test_flush_parse_error_skips_description(monkeypatch):
    task = _task(tasting_tags=["Honey"])
    build_payload(task, _noop_emit)
    monkeypatch.setattr(pipeline, "generate_description_live",
                        lambda *a, **kw: (_ for _ in ()).throw(VeniceParseError("bad json")))
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pipeline, "live_update_bottle", update_mock)
    flush_venice_queue([task], _noop_emit, MagicMock(), MagicMock(), batch_size=1)
    payload = update_mock.call_args.args[1]
    assert "description" not in payload


# ---------------------------------------------------------------------------
# flush_venice_queue — batched mode
# ---------------------------------------------------------------------------


def test_flush_batched_success(monkeypatch):
    t1 = _task(bottle_id=1)
    t2 = _task(bottle_id=2, document_id="doc-2")
    build_payload(t1, _noop_emit)
    build_payload(t2, _noop_emit)

    def _batch(items):
        return [
            {"id": it["id"],
             "improved": {"de": "d", "en": f"en-{it['id']}", "es": "s", "fr": "f", "it": "i"}}
            for it in items
        ]
    monkeypatch.setattr(pipeline, "generate_descriptions_batch", _batch)
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pipeline, "live_update_bottle", update_mock)

    flush_venice_queue([t1, t2], _noop_emit, MagicMock(), MagicMock(), batch_size=2)

    assert update_mock.call_count == 2
    written = {c.args[0]: c.args[1] for c in update_mock.call_args_list}
    assert written["doc-abc"]["description"]["en"] == "en-1"
    assert written["doc-2"]["description"]["en"] == "en-2"


def test_flush_batch_parse_error_falls_back_to_per_bottle(monkeypatch):
    t1 = _task(bottle_id=1)
    t2 = _task(bottle_id=2, document_id="doc-2")

    def _batch_fails(items):
        raise VeniceParseError("missing id")
    calls = []
    def _single(r, n, m):
        calls.append(n)
        return {"de": "d", "en": f"en-{n}", "es": "s", "fr": "f", "it": "i"}
    monkeypatch.setattr(pipeline, "generate_descriptions_batch", _batch_fails)
    monkeypatch.setattr(pipeline, "generate_description_live", _single)
    monkeypatch.setattr(pipeline, "live_update_bottle", MagicMock(return_value=True))

    flush_venice_queue([t1, t2], _noop_emit, MagicMock(), MagicMock(), batch_size=2)
    assert len(calls) == 2  # fallback ran per bottle


def test_flush_clears_the_queue_in_place(monkeypatch):
    task = _task()
    monkeypatch.setattr(pipeline, "generate_description_live",
                        lambda *a, **kw: {"de": "d", "en": "e", "es": "s", "fr": "f", "it": "i"})
    monkeypatch.setattr(pipeline, "live_update_bottle", lambda *a, **kw: True)
    q = [task]
    flush_venice_queue(q, _noop_emit, MagicMock(), MagicMock(), batch_size=1)
    assert q == []


def test_flush_empty_queue_is_noop(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("should not call venice on empty queue")
    monkeypatch.setattr(pipeline, "generate_description_live", _boom)
    monkeypatch.setattr(pipeline, "generate_descriptions_batch", _boom)
    flush_venice_queue([], _noop_emit, MagicMock(), MagicMock(), batch_size=5)
