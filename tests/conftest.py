"""Pytest bootstrap for the Spiritory scraper test suite.

Why the sys.modules stubs:
  * `openai` and `patchright` are heavy runtime deps. Tests for prompt/logic
    code should not require installing a browser engine or the OpenAI SDK.
  * We install minimal stub modules BEFORE any test imports pull the real
    packages in. Each test that actually exercises Venice or patchright
    behavior can still monkeypatch the stub internals.
"""

import os
import sys
import types
from pathlib import Path

# Ensure project root is importable (tests run from anywhere).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Environment isolation: tests must never hit real backends.
os.environ.setdefault("STRAPI_BASE_URL", "http://test.invalid/api")
os.environ.setdefault("STRAPI_API_KEY", "test-key")
os.environ.setdefault("VENICE_ADMIN_KEY", "test-venice-key")


# ---------------------------------------------------------------------------
# openai stub
# ---------------------------------------------------------------------------

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _StubOpenAI:  # pragma: no cover - replaced per test
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda *a, **kw: (_ for _ in ()).throw(
                        RuntimeError("openai stub: monkeypatch me in your test")
                    )
                )
            )

    class _APIError(Exception):
        def __init__(self, message="", *args, **kwargs):
            super().__init__(message)

    class _APIStatusError(_APIError):
        def __init__(self, message="", status_code=500, *args, **kwargs):
            super().__init__(message)
            self.status_code = status_code

    openai_stub.OpenAI = _StubOpenAI
    openai_stub.APIError = _APIError
    openai_stub.APIStatusError = _APIStatusError
    openai_stub.APIConnectionError = type("APIConnectionError", (_APIError,), {})
    openai_stub.APITimeoutError = type("APITimeoutError", (_APIError,), {})
    openai_stub.RateLimitError = type("RateLimitError", (_APIError,), {})
    sys.modules["openai"] = openai_stub


# ---------------------------------------------------------------------------
# patchright stub — only needs enough surface for integrations.whiskybase
# to import without exploding. No tests exercise browser behavior.
# ---------------------------------------------------------------------------

if "patchright" not in sys.modules:
    patchright_stub = types.ModuleType("patchright")
    sync_api_stub = types.ModuleType("patchright.sync_api")

    def _sync_playwright_stub():  # pragma: no cover
        raise RuntimeError("patchright stub: tests must not start a browser")

    class _Browser: ...
    class _BrowserContext: ...
    class _Page: ...

    sync_api_stub.sync_playwright = _sync_playwright_stub
    sync_api_stub.Browser = _Browser
    sync_api_stub.BrowserContext = _BrowserContext
    sync_api_stub.Page = _Page
    patchright_stub.sync_api = sync_api_stub
    sys.modules["patchright"] = patchright_stub
    sys.modules["patchright.sync_api"] = sync_api_stub


# ---------------------------------------------------------------------------
# bs4 stub (used only by integrations.whiskybase at import time)
# ---------------------------------------------------------------------------

try:
    import bs4  # noqa: F401
except ImportError:  # pragma: no cover
    bs4_stub = types.ModuleType("bs4")
    bs4_stub.BeautifulSoup = lambda *a, **kw: None
    sys.modules["bs4"] = bs4_stub
