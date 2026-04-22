"""Per-bottle pipeline helpers shared by `scraper_engine.py`.

Keeps `scraper_engine.py` focused on orchestration (fetch → loop → ban
handling → arg parsing). Holds:

* `BottleTask` — data carrier for a scraped, pending-write bottle.
* `build_payload` — decide what Strapi update each bottle needs based on
  what's already populated vs. what WhiskyBase returned.
* `flush_venice_queue` — call Venice (batched or per-bottle) on a list of
  BottleTasks, merge descriptions into their payloads, write each to Strapi,
  log and (conditionally) checkpoint.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from integrations.strapi import update_bottle as live_update_bottle
from utils.tasting_tags import normalize_tag
from utils.venice import (
    VeniceParseError,
    VeniceTransientError,
    generate_description_live,
    generate_descriptions_batch,
)

EmitFn = Callable[..., None]
LogFn = Callable[[int, str, str, str, str, str], None]
CheckpointFn = Callable[[int], None]


@dataclass
class BottleTask:
    bottle_id: int
    wb_id: str
    document_id: str
    name: str
    has_description: bool
    has_tasting_1: bool
    has_tasting_2: bool
    reviews_text: str
    metadata: dict
    tasting_tags: list[str]
    payload: dict = field(default_factory=dict)


def build_payload(task: BottleTask, emit: EmitFn) -> None:
    """Populate `task.payload` with tasting notes only. Description is added
    later by `flush_venice_queue` after the Venice call."""
    if task.tasting_tags:
        valid = [normalize_tag(t) for t in task.tasting_tags if normalize_tag(t)]
        skipped = [t for t in task.tasting_tags if not normalize_tag(t)]
        if skipped:
            emit("warning", "skip",
                 f"  -> Tasting tags not in Strapi enum (skipped): {skipped}",
                 bottle_id=task.bottle_id, bottle_name=task.name)
        if not task.has_tasting_1 and len(valid) >= 1:
            task.payload["tasting_note_1"] = valid[0]
        if not task.has_tasting_2 and len(valid) >= 2:
            task.payload["tasting_note_2"] = valid[1]


def _cell(has_existing: bool, payload: dict, key: str) -> Any:
    if has_existing:
        return "[already had data]"
    if key in payload:
        val = payload[key]
        if isinstance(val, dict):
            return val.get("en", "")[:500]
        return val
    return "[no wb data]"


def _write_one(task: BottleTask, emit: EmitFn, logger_log: LogFn,
               save_cp: CheckpointFn | None) -> None:
    """Write task.payload to Strapi (if non-empty), log CSV row, checkpoint."""
    desc_cell = _cell(task.has_description, task.payload, "description")
    t1_cell = _cell(task.has_tasting_1, task.payload, "tasting_note_1")
    t2_cell = _cell(task.has_tasting_2, task.payload, "tasting_note_2")

    if not task.payload:
        emit("info", "skip", "  -> Nothing to update. Skipping.",
             bottle_id=task.bottle_id, bottle_name=task.name)
        logger_log(task.bottle_id, task.wb_id, task.name, desc_cell, t1_cell, t2_cell)
        if save_cp:
            save_cp(task.bottle_id)
        return

    live_update_bottle(task.document_id, task.payload)
    emit("info", "writing", f"  -> Updated: {', '.join(task.payload.keys())}",
         bottle_id=task.bottle_id, bottle_name=task.name)

    if "description" in task.payload:
        for lang in ("en", "de", "es", "fr", "it"):
            val = task.payload["description"].get(lang, "")
            if val:
                emit("info", "writing_detail", f"     description[{lang}]: {val}",
                     bottle_id=task.bottle_id, bottle_name=task.name)
    for key in ("tasting_note_1", "tasting_note_2"):
        if key in task.payload and task.payload[key]:
            emit("info", "writing_detail", f"     {key}: {task.payload[key]}",
                 bottle_id=task.bottle_id, bottle_name=task.name)

    logger_log(task.bottle_id, task.wb_id, task.name, desc_cell, t1_cell, t2_cell)
    if save_cp:
        save_cp(task.bottle_id)


def _venice_single(task: BottleTask, emit: EmitFn) -> bool:
    """Fill task.payload['description'] via one Venice call. Returns True on
    success, False on a per-bottle failure (caller decides whether to
    still write what it has). Short-circuits when the bottle already has a
    description or when there are no reviews to feed Venice."""
    if task.has_description or not (task.reviews_text or "").strip():
        return False
    emit("info", "generating", "  -> Generating description via Venice (live prompt)...",
         bottle_id=task.bottle_id, bottle_name=task.name)
    try:
        desc = generate_description_live(task.reviews_text, task.name, task.metadata)
    except VeniceTransientError as e:
        emit("error", "venice_transient",
             f"  -> Venice transient error after retries: {e}. Skipping description.",
             bottle_id=task.bottle_id, bottle_name=task.name)
        return False
    except VeniceParseError as e:
        emit("error", "venice_parse",
             f"  -> Venice parse error: {e}. Skipping description.",
             bottle_id=task.bottle_id, bottle_name=task.name)
        return False
    if desc and desc.get("en", "").strip():
        task.payload["description"] = desc
        return True
    return False


def flush_venice_queue(
    queue: list[BottleTask],
    emit: EmitFn,
    logger_log: LogFn,
    save_cp: CheckpointFn | None,
    batch_size: int,
) -> None:
    """Run Venice (batched if batch_size>1) on all queued tasks, merge into
    payloads, and write each to Strapi. Always drains the queue in place."""
    if not queue:
        return

    # Only tasks that (a) lack a description AND (b) have review text to feed
    # Venice are eligible for a Venice call. The rest will just be written
    # with whatever payload they already have (tasting notes only, or nothing).
    venice_eligible = [
        t for t in queue
        if not t.has_description and (t.reviews_text or "").strip()
    ]

    if batch_size > 1 and len(venice_eligible) > 1:
        items = [
            {"id": t.bottle_id, "name": t.name,
             "reviews_text": t.reviews_text, "metadata": t.metadata}
            for t in venice_eligible
        ]
        emit("info", "generating",
             f"  -> Venice batch call for {len(items)} bottles "
             f"(ids={[t.bottle_id for t in venice_eligible]})...")
        try:
            results = generate_descriptions_batch(items)
        except VeniceTransientError as e:
            emit("error", "venice_transient",
                 f"  -> Venice batch transient error after retries: {e}. Falling back to per-bottle.")
            results = None
        except VeniceParseError as e:
            emit("warning", "venice_parse",
                 f"  -> Venice batch parse error: {e}. Falling back to per-bottle.")
            results = None

        if results is not None:
            by_id = {r["id"]: r["improved"] for r in results}
            for task in venice_eligible:
                desc = by_id.get(task.bottle_id)
                if desc and desc.get("en", "").strip():
                    task.payload["description"] = desc
        else:
            for task in venice_eligible:
                _venice_single(task, emit)
    else:
        for task in venice_eligible:
            _venice_single(task, emit)

    for task in queue:
        _write_one(task, emit, logger_log, save_cp)
    queue.clear()
