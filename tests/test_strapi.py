"""Tests for integrations/strapi.py."""

from datetime import datetime, timezone

from integrations import strapi


class _Response:
    ok = True

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_fetch_bottles_respects_limit(monkeypatch):
    def _fake_get(url, headers):
        return _Response({
            "data": [{"id": 1}, {"id": 2}, {"id": 3}],
            "meta": {"pagination": {"total": 3}},
        })

    monkeypatch.setattr(strapi.requests, "get", _fake_get)

    assert strapi.fetch_bottles(limit=2) == [{"id": 1}, {"id": 2}]


def test_fetch_bottles_adds_created_window_filters(monkeypatch):
    captured = {}

    def _fake_get(url, headers):
        captured["url"] = url
        return _Response({
            "data": [],
            "meta": {"pagination": {"total": 0}},
        })

    monkeypatch.setattr(strapi.requests, "get", _fake_get)

    strapi.fetch_bottles(
        limit=1,
        created_since=datetime(2026, 4, 27, tzinfo=timezone.utc),
        created_until=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )

    assert "filters[createdAt][$gte]=2026-04-27T00:00:00.000Z" in captured["url"]
    assert "filters[createdAt][$lt]=2026-04-28T00:00:00.000Z" in captured["url"]
