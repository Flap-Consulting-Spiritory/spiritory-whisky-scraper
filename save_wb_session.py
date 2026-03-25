"""
Run this script once to save your WhiskyBase session cookies.
Uses nodriver (bypasses Cloudflare) — a real Chrome window will open.
Log in manually, then press Enter here.
The session is saved to wb_session.json and reused by the scraper.

Resilience: if cookie collection fails it retries up to MAX_COOKIE_RETRIES times.
If all cookie retries are exhausted, the browser restarts and you can log in again.
MAX_BROWSER_RESTARTS controls how many full browser restarts are allowed.
"""
import asyncio
import json
import os
import time

import nodriver as uc

SESSION_FILE = os.path.join(os.path.dirname(__file__), "wb_session.json")

MAX_COOKIE_RETRIES   = 3   # attempts to collect cookies per browser session
MAX_BROWSER_RESTARTS = 2   # full browser restarts if all cookie attempts fail
COOKIE_RETRY_DELAY   = 3   # seconds between cookie retry attempts
COOKIE_TIMEOUT       = 10  # seconds before a single CDP call is considered hung


async def _collect_cookies(browser) -> list:
    """Try main_tab first, then fall back to all open tabs."""
    active_page = browser.main_tab
    try:
        cookies = await asyncio.wait_for(
            active_page.send(uc.cdp.network.get_cookies()),
            timeout=COOKIE_TIMEOUT,
        )
        if cookies:
            return cookies
    except (asyncio.TimeoutError, Exception):
        pass

    print("  main_tab timed out — trying all open tabs...")
    for tab in browser.tabs:
        try:
            cookies = await asyncio.wait_for(
                tab.send(uc.cdp.network.get_cookies()),
                timeout=COOKIE_TIMEOUT,
            )
            if cookies:
                return cookies
        except Exception:
            continue

    return []


def _build_cookie_dicts(cookies: list) -> list[dict]:
    wb_cookies = [
        {
            "name":     c.name,
            "value":    c.value,
            "domain":   c.domain,
            "path":     c.path,
            "expires":  c.expires,
            "httpOnly": c.http_only,
            "secure":   c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies
        if "whiskybase" in (c.domain or "")
    ]
    if wb_cookies:
        return wb_cookies
    # Fallback: save all cookies if none matched whiskybase domain
    return [
        {
            "name":     c.name,
            "value":    c.value,
            "domain":   c.domain,
            "path":     c.path,
            "expires":  c.expires,
            "httpOnly": c.http_only,
            "secure":   c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies
    ]


async def main():
    for browser_attempt in range(1, MAX_BROWSER_RESTARTS + 1):
        print(f"\n[Attempt {browser_attempt}/{MAX_BROWSER_RESTARTS}] Opening WhiskyBase with nodriver...")
        print("Log in to your account, then come back here and press Enter.\n")

        browser = await uc.start()
        await browser.get("https://www.whiskybase.com/account/login")

        input(">>> Press Enter once you are logged in to WhiskyBase...")

        # Cookie collection with retry loop
        save_cookies: list[dict] = []
        for cookie_attempt in range(1, MAX_COOKIE_RETRIES + 1):
            print(f"\nCollecting cookies (attempt {cookie_attempt}/{MAX_COOKIE_RETRIES})...")
            try:
                raw = await _collect_cookies(browser)
                if raw:
                    save_cookies = _build_cookie_dicts(raw)
                    if save_cookies:
                        break  # success
                    print("  Got cookies but none matched whiskybase domain — retrying...")
                else:
                    print("  No cookies returned from any tab.")
            except Exception as e:
                print(f"  Cookie collection error: {e}")

            if cookie_attempt < MAX_COOKIE_RETRIES:
                print(f"  Waiting {COOKIE_RETRY_DELAY}s before retry...")
                await asyncio.sleep(COOKIE_RETRY_DELAY)

        try:
            browser.stop()
        except Exception:
            pass

        if save_cookies:
            break  # don't restart browser if we got cookies

        # All cookie attempts failed for this browser session
        if browser_attempt < MAX_BROWSER_RESTARTS:
            print(f"\n[!] All {MAX_COOKIE_RETRIES} cookie attempts failed.")
            print(f"    Restarting browser (attempt {browser_attempt + 1}/{MAX_BROWSER_RESTARTS})...")
            time.sleep(2)
        else:
            print(f"\n[ERROR] All browser restarts exhausted. Could not collect cookies.")
            print("  Tips:")
            print("  - Make sure you are fully logged in before pressing Enter")
            print("  - Try refreshing the WhiskyBase page after logging in")
            print("  - Run: pip install --upgrade nodriver")
            return

    with open(SESSION_FILE, "w") as f:
        json.dump(save_cookies, f, indent=2)

    print(f"\nSession saved to: {SESSION_FILE}  ({len(save_cookies)} cookies)")
    print("You can now run the scraper normally — it will use this session.")


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
