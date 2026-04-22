"""Consolidated Venice AI client.

Replaces the old `utils/gemini.py` (which silently swallowed errors) with:

  * `generate_description_live(reviews, bottle_name, metadata)`
        one bottle → 5-language JSON dict, used by the daily cron.

  * `generate_descriptions_batch(items)`
        N bottles in one call → list of {id, improved} dicts, used when the
        scraper opts into `--venice-batch N>1`.

Errors are classified into two types so callers can decide what to do:

  * `VeniceTransientError` — 429 / 5xx / network — auto-retried by tenacity
    (3 attempts, 2→30 s exponential). After retries are exhausted, raised.

  * `VeniceParseError` — response arrived but was unparseable or incomplete.
    Not retried; caller falls back to per-bottle path (or marks bottle failed).
"""

import json
import os

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

VENICE_BASE_URL = "https://api.venice.ai/api/v1"
VENICE_MODEL = os.environ.get("VENICE_MODEL", "gemini-3-flash-preview")

_LANGS: tuple[str, ...] = ("de", "en", "es", "fr", "it")


class VeniceTransientError(RuntimeError):
    """Transient Venice failure (rate limit, 5xx, network). Retriable."""


class VeniceParseError(RuntimeError):
    """Venice responded but output is malformed or incomplete. Not retriable."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _client() -> openai.OpenAI:
    return openai.OpenAI(
        api_key=os.environ.get("VENICE_ADMIN_KEY", ""),
        base_url=VENICE_BASE_URL,
    )


def _strip_json_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _normalize_langs(parsed: dict) -> dict:
    """Return exactly the 5 language keys with empty-string defaults."""
    return {lang: parsed.get(lang, "") or "" for lang in _LANGS}


def _classify(e: Exception) -> Exception:
    """Turn openai.* exceptions into our two typed errors."""
    if isinstance(e, (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError)):
        return VeniceTransientError(str(e))
    if isinstance(e, openai.APIStatusError):
        code = getattr(e, "status_code", 0) or 0
        if code == 429 or code >= 500:
            return VeniceTransientError(f"HTTP {code}: {e}")
        return VeniceParseError(f"HTTP {code}: {e}")
    return e


@retry(
    retry=retry_if_exception_type(VeniceTransientError),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _venice_completion(prompt: str) -> str:
    """Call Venice chat completions with 3-attempt retry on transient errors.
    Returns the raw assistant message content."""
    try:
        response = _client().chat.completions.create(
            model=VENICE_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise _classify(e) from e
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Public: single-bottle (live path)
# ---------------------------------------------------------------------------


def generate_description_live(
    reviews_text: str, bottle_name: str, metadata: dict | None = None
) -> dict:
    """Generate a 5-language description for one freshly-scraped bottle.

    Returns `{"de","en","es","fr","it"}`. Raises `VeniceTransientError` after
    retry exhaustion, or `VeniceParseError` on unparseable output. Callers in
    the scraper catch these and log-then-skip the bottle (no silent drops).

    Empty reviews -> empty dict with no Venice call (defensive no-op).
    """
    if not reviews_text or not reviews_text.strip():
        return {lang: "" for lang in _LANGS}

    from utils.prompts import build_live_prompt  # lazy to avoid cycle in tests

    prompt = build_live_prompt(bottle_name, reviews_text, metadata or {})
    raw = _venice_completion(prompt)
    try:
        parsed = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as e:
        raise VeniceParseError(f"invalid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise VeniceParseError(f"expected dict, got {type(parsed).__name__}")

    out = _normalize_langs(parsed)
    if not out["en"].strip():
        raise VeniceParseError("empty 'en' in response")
    return out


# ---------------------------------------------------------------------------
# Public: batched (live path, --venice-batch N>1)
# ---------------------------------------------------------------------------


def generate_descriptions_batch(items: list[dict]) -> list[dict]:
    """Run one Venice call for N bottles.

    Each item must have: `id`, `name`, `reviews_text`, `metadata`.
    Returns list of `{"id": int, "improved": {de,en,es,fr,it}}` in the same
    order as input.

    Raises `VeniceTransientError` on retry-exhausted network/5xx failures.
    Raises `VeniceParseError` if the response is malformed, is missing any
    expected id, or any bottle's `en` field is empty — caller should fall
    back to per-bottle calls via `generate_description_live`.
    """
    if not items:
        return []

    from utils.prompts import build_live_batch_prompt  # lazy

    expected_ids = [item["id"] for item in items]
    prompt = build_live_batch_prompt(items)
    raw = _venice_completion(prompt)

    try:
        parsed = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as e:
        raise VeniceParseError(f"invalid JSON: {e}") from e

    results = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        raise VeniceParseError("missing 'results' array")

    by_id: dict[int, dict] = {}
    for entry in results:
        if not isinstance(entry, dict):
            continue
        try:
            rid = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        by_id[rid] = _normalize_langs(entry.get("improved") or {})

    missing = [i for i in expected_ids if i not in by_id]
    if missing:
        raise VeniceParseError(f"missing ids in response: {missing}")
    empty = [i for i in expected_ids if not by_id[i]["en"].strip()]
    if empty:
        raise VeniceParseError(f"empty 'en' for ids: {empty}")

    return [{"id": i, "improved": by_id[i]} for i in expected_ids]
