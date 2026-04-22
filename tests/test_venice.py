import json
import types

import pytest

from utils import venice
from utils.venice import (
    VeniceParseError,
    VeniceTransientError,
    _normalize_langs,
    _strip_json_fences,
    generate_description_live,
    generate_descriptions_batch,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_strip_json_fences_plain():
    assert _strip_json_fences('{"en": "x"}') == '{"en": "x"}'


def test_strip_json_fences_markdown_json():
    raw = '```json\n{"en": "x"}\n```'
    assert _strip_json_fences(raw) == '{"en": "x"}'


def test_strip_json_fences_markdown_bare():
    assert _strip_json_fences("```\n{\"en\": \"x\"}\n```") == '{"en": "x"}'


def test_normalize_langs_fills_missing():
    out = _normalize_langs({"en": "hi", "fr": None})
    assert out == {"de": "", "en": "hi", "es": "", "fr": "", "it": ""}


# ---------------------------------------------------------------------------
# Monkeypatching helper
# ---------------------------------------------------------------------------


def _fake_completion(content: str):
    """Patch venice._venice_completion to return a fixed payload."""
    def _fake(prompt):
        return content
    return _fake


# ---------------------------------------------------------------------------
# generate_description_live
# ---------------------------------------------------------------------------


def test_generate_description_live_happy(monkeypatch):
    payload = json.dumps({
        "de": "deutsch", "en": "english", "es": "espanol", "fr": "francais", "it": "italiano",
    })
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(payload))
    out = generate_description_live("smoky", "Ardbeg 10", {"productAge": 10})
    assert out["en"] == "english"
    assert out["de"] == "deutsch"
    assert set(out.keys()) == {"de", "en", "es", "fr", "it"}


def test_generate_description_live_strips_fences(monkeypatch):
    payload = '```json\n{"de":"d","en":"e","es":"s","fr":"f","it":"i"}\n```'
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(payload))
    out = generate_description_live("r", "N", {})
    assert out["en"] == "e"


def test_generate_description_live_empty_reviews_short_circuits(monkeypatch):
    # Should never even call Venice
    def _boom(_):
        raise AssertionError("Venice must not be called on empty reviews")
    monkeypatch.setattr(venice, "_venice_completion", _boom)
    out = generate_description_live("", "N", {})
    assert out == {"de": "", "en": "", "es": "", "fr": "", "it": ""}


def test_generate_description_live_raises_on_malformed_json(monkeypatch):
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion("not json"))
    with pytest.raises(VeniceParseError):
        generate_description_live("r", "N", {})


def test_generate_description_live_raises_on_empty_en(monkeypatch):
    payload = json.dumps({"de": "d", "en": "", "es": "", "fr": "", "it": ""})
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(payload))
    with pytest.raises(VeniceParseError):
        generate_description_live("r", "N", {})


def test_generate_description_live_raises_on_non_dict(monkeypatch):
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion('["a","b"]'))
    with pytest.raises(VeniceParseError):
        generate_description_live("r", "N", {})


# ---------------------------------------------------------------------------
# generate_descriptions_batch
# ---------------------------------------------------------------------------


def _batch_payload(ids_with_langs):
    return json.dumps({
        "results": [
            {"id": i, "improved": {"de": "d", "en": f"en-{i}", "es": "s", "fr": "f", "it": "i"}}
            for i in ids_with_langs
        ]
    })


def test_batch_happy(monkeypatch):
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(_batch_payload([1, 2])))
    items = [
        {"id": 1, "name": "A", "reviews_text": "ra", "metadata": {}},
        {"id": 2, "name": "B", "reviews_text": "rb", "metadata": {}},
    ]
    out = generate_descriptions_batch(items)
    assert [r["id"] for r in out] == [1, 2]
    assert out[0]["improved"]["en"] == "en-1"


def test_batch_missing_id_raises_parse_error(monkeypatch):
    # Ask for [1,2] but only get back [1]
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(_batch_payload([1])))
    items = [
        {"id": 1, "name": "A", "reviews_text": "ra", "metadata": {}},
        {"id": 2, "name": "B", "reviews_text": "rb", "metadata": {}},
    ]
    with pytest.raises(VeniceParseError):
        generate_descriptions_batch(items)


def test_batch_empty_en_raises_parse_error(monkeypatch):
    payload = json.dumps({
        "results": [{"id": 1, "improved": {"en": "", "de": "", "es": "", "fr": "", "it": ""}}]
    })
    monkeypatch.setattr(venice, "_venice_completion", _fake_completion(payload))
    with pytest.raises(VeniceParseError):
        generate_descriptions_batch([{"id": 1, "name": "A", "reviews_text": "", "metadata": {}}])


def test_batch_no_items_returns_empty_without_calling(monkeypatch):
    def _boom(_):
        raise AssertionError("must not call Venice with empty batch")
    monkeypatch.setattr(venice, "_venice_completion", _boom)
    assert generate_descriptions_batch([]) == []


# ---------------------------------------------------------------------------
# Retry classification: 429 -> transient, 400 -> parse
# ---------------------------------------------------------------------------


def test_classify_rate_limit_becomes_transient():
    import openai
    err = openai.RateLimitError("rate limited")
    assert isinstance(venice._classify(err), VeniceTransientError)


def test_classify_connection_error_becomes_transient():
    import openai
    err = openai.APIConnectionError("net down")
    assert isinstance(venice._classify(err), VeniceTransientError)


def test_classify_5xx_status_becomes_transient():
    import openai
    err = openai.APIStatusError("bad", status_code=503)
    assert isinstance(venice._classify(err), VeniceTransientError)


def test_classify_4xx_status_becomes_parse_error():
    import openai
    err = openai.APIStatusError("bad request", status_code=400)
    assert isinstance(venice._classify(err), VeniceParseError)
