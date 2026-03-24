from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from playwright_stealth import stealth_sync
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
import re
import os

# Optional proxy format: http://username:password@ip:port
PROXY_URL = os.environ.get("PROXY_URL", None)

WB_USERNAME = os.environ.get("WHISKYBASE_USERNAME", "")
WB_PASSWORD = os.environ.get("WHISKYBASE_PASSWORD", "")
WB_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "wb_session.json")

class ScrapeBanException(Exception):
    """Raised when WhiskyBase shows a Cloudflare captcha — safe to retry."""
    pass


class ScrapeHardBanException(Exception):
    """Raised on HTTP 403/429 — hard IP block, do not retry."""
    pass


# --- Shared browser session ---
# Kept alive across calls so login cookies persist for all scrapes in a process.

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None
_logged_in: bool = False


def _get_context() -> BrowserContext:
    """Return (or create) the shared browser context, logging in once if credentials exist."""
    global _playwright, _browser, _context, _logged_in

    if _context is None:
        _playwright = sync_playwright().start()

        launch_args: dict = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        _browser = _playwright.chromium.launch(**launch_args)
        _context = _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            has_touch=False,
            locale="en-US",
            timezone_id="America/New_York",
        )

    if not _logged_in:
        session_path = os.path.normpath(WB_SESSION_FILE)
        if os.path.exists(session_path):
            import json
            with open(session_path) as f:
                cookies = json.load(f)
            _context.add_cookies(cookies)
            _logged_in = True
            print(f"[WhiskyBase] Session loaded from {session_path} ({len(cookies)} cookies)")

    return _context


def close_session():
    """Closes the shared browser session safely."""
    global _playwright, _browser, _context, _logged_in
    
    try:
        if _browser:
            try:
                _browser.close()
            except Exception as e:
                print(f"[WhiskyBase] Error closing browser: {e}")
    finally:
        try:
            if _playwright:
                _playwright.stop()
        except Exception as e:
            print(f"[WhiskyBase] Error stopping playwright: {e}")
        finally:
            _browser = None
            _context = None
            _playwright = None
            _logged_in = False


@retry(
    wait=wait_exponential(multiplier=1, min=4, max=15),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(ScrapeBanException),
    reraise=True,
)
def scrape_bottle_data(whiskybase_id: str) -> dict:
    """
    Scrapes the top 2 reviews and top 2 tasting tags from a WhiskyBase bottle page.
    Returns:
        {
            "description_en_raw": str | None,  # top 2 reviews joined by double newline
            "tasting_tags": list[str],          # top 2 tag names by vote count
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
        stealth_sync(page)

        # Go to the bottle page
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Check for ban / block
        if response and response.status in [403, 429]:
            page.close()
            raise ScrapeHardBanException(f"Blocked by WhiskyBase! Status: {response.status}")

        html = page.content()
        final_url = page.url  # capture before close — page.url raises after close()
        page.close()

        # Check for Cloudflare Challenge
        if "Just a moment..." in html or "cf-browser-verification" in html:
            raise ScrapeBanException("Cloudflare Captcha hit!")

        # Check for expired / missing session (redirected to login page)
        if final_url and "/account/login" in final_url:
            print("\n[WhiskyBase] ⚠️  Session expired — reviews will be blurred.")
            print("  Run: python save_wb_session.py   and then restart the scraper.\n")

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

        # ── Tasting tags: top 2 by vote count (data-num attribute) ───────────
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
