from patchright.sync_api import sync_playwright, Browser, BrowserContext, Page
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
import re
import os
import random
import time

# Optional proxy format: http://username:password@ip:port
PROXY_URL = os.environ.get("PROXY_URL", None)

# Refresh the browser context after this many requests to avoid fingerprint tracking
_CONTEXT_REFRESH_EVERY = 10

class ScrapeBanException(Exception):
    """Raised when WhiskyBase shows a Cloudflare captcha — safe to retry."""
    pass


class ScrapeHardBanException(Exception):
    """Raised on HTTP 403/429 — hard IP block, do not retry."""
    pass


# --- Shared browser session ---
# Mutable dict avoids global declarations for counter state.
# Refreshed every _CONTEXT_REFRESH_EVERY requests to rotate fingerprint.

_session: dict = {
    "playwright": None,
    "browser": None,
    "context": None,
    "requests_count": 0,
}

# Realistic desktop viewport options — avoid always-1920x1080 headless signature
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]


def _get_context() -> BrowserContext:
    """Return (or create) the shared browser context. Refreshes every N requests."""
    # Proactively rotate fingerprint after every N requests
    if (
        _session["context"] is not None
        and _session["requests_count"] > 0
        and _session["requests_count"] % _CONTEXT_REFRESH_EVERY == 0
    ):
        print(f"    [Anti-Ban] Refreshing browser context after {_session['requests_count']} requests...")
        close_session()

    if _session["context"] is None:
        _session["playwright"] = sync_playwright().start()

        launch_kwargs: dict = {
            "headless": True,
            "channel": "chromium",  # New headless mode: full browser fidelity
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if PROXY_URL:
            launch_kwargs["proxy"] = {"server": PROXY_URL}

        _session["browser"] = _session["playwright"].chromium.launch(**launch_kwargs)
        _session["context"] = _session["browser"].new_context(
            # UA must match Playwright 1.50's bundled Chromium (132)
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            viewport=random.choice(_VIEWPORTS),
            device_scale_factor=1,
            has_touch=False,
            locale="en-US",
            timezone_id="America/New_York",
        )

    _session["requests_count"] += 1
    return _session["context"]


def close_session():
    """Closes the shared browser session safely."""
    try:
        if _session["browser"]:
            try:
                _session["browser"].close()
            except Exception as e:
                print(f"[WhiskyBase] Error closing browser: {e}")
    finally:
        try:
            if _session["playwright"]:
                _session["playwright"].stop()
        except Exception as e:
            print(f"[WhiskyBase] Error stopping playwright: {e}")
        finally:
            _session["browser"] = None
            _session["context"] = None
            _session["playwright"] = None
            _session["requests_count"] = 0


@retry(
    wait=wait_exponential(multiplier=2, min=30, max=180),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(ScrapeBanException),
    reraise=True,
)
def scrape_bottle_data(whiskybase_id: str) -> dict:
    """
    Scrapes the top 2 reviews and top 5 tasting tags from a WhiskyBase bottle page.
    Returns:
        {
            "description_en_raw": str | None,  # top 2 reviews joined by double newline
            "tasting_tags": list[str],          # top 5 tag names by vote count
        }
    """
    numeric_id = re.sub(r'[^0-9]', '', whiskybase_id)
    url = f"https://www.whiskybase.com/whiskies/whisky/{numeric_id}"

    data: dict = {
        "description_en_raw": None,
        "tasting_tags": [],
    }

    try:
        context = _get_context()
        page = context.new_page()
        # patchright patches CDP/fingerprinting automatically — no stealth_sync needed

        # Go to the bottle page
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Check for hard ban / block
        if response and response.status in [403, 429]:
            page.close()
            raise ScrapeHardBanException(f"Blocked by WhiskyBase! Status: {response.status}")

        # Brief human-like interaction: pause then scroll before extracting HTML
        time.sleep(random.uniform(1.0, 3.0))
        page.evaluate(f"window.scrollBy(0, {random.randint(300, 600)})")
        time.sleep(random.uniform(0.5, 1.5))

        html = page.content()
        final_url = page.url  # capture before close — page.url raises after close()
        page.close()

        # Check for Cloudflare Challenge (multiple detection patterns)
        if any(marker in html for marker in (
            "Just a moment...",
            "cf-browser-verification",
            "cf-turnstile",
            "challenge-platform",
        )):
            raise ScrapeBanException("Cloudflare challenge detected!")

        soup = BeautifulSoup(html, 'html.parser')

        # ── Reviews: top 2 by likes, then by length ───────────────────────────
        reviews = []
        for article in soup.select("article.wb--note"):
            if "blur" in article.get("class", []):
                continue
            msg_div = article.select_one("[data-translation-field='message']")
            if not msg_div:
                continue
            text = msg_div.get_text(strip=True)
            if not text:
                continue
            likes = 0
            like_elem = article.select_one("[data-count], .vote-count, .like-count, .wb--note--votes")
            if like_elem:
                raw = like_elem.get("data-count") or like_elem.get_text(strip=True)
                try:
                    likes = int(raw)
                except (ValueError, TypeError):
                    likes = 0
            reviews.append({"text": text, "likes": likes})

        top_reviews = sorted(reviews, key=lambda r: (r["likes"], len(r["text"])), reverse=True)[:2]
        if top_reviews:
            data["description_en_raw"] = "\n\n".join(r["text"] for r in top_reviews)

        # ── Tasting tags: top 5 by vote count (data-num attribute) ───────────
        tag_entries = []
        for tag_elem in soup.select("a.btn-tastingtag"):
            name_div = tag_elem.select_one(".tag-name")
            if not name_div:
                continue
            name = name_div.get_text(strip=True)
            try:
                count = int(tag_elem.get("data-num", 0))
            except (ValueError, TypeError):
                count = 0
            if count > 0:
                tag_entries.append((count, name))

        data["tasting_tags"] = [n for _, n in sorted(tag_entries, reverse=True)[:5]]

    except ScrapeHardBanException:
        raise  # Always propagate hard IP bans — never swallow

    except ScrapeBanException as e:
        print(f"    [Anti-Ban] Request blocked for {url}: {e} - Retrying...")
        raise  # Tenacity handles the retry backoff

    except Exception as e:
        print(f"[WhiskyBase] Unhandled Error scraping {url}: {e}")
        raise e

    return data
