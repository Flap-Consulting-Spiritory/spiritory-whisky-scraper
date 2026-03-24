"""
Run this script once to save your WhiskyBase session cookies.
Uses nodriver (bypasses Cloudflare) — a real Chrome window will open.
Log in manually, then press Enter here.
The session is saved to wb_session.json and reused by the scraper.
"""
import asyncio
import json
import os

import nodriver as uc

SESSION_FILE = os.path.join(os.path.dirname(__file__), "wb_session.json")


async def main():
    print("Opening WhiskyBase with nodriver (bypasses Cloudflare)...")
    print("Log in to your account, then come back here and press Enter.\n")

    browser = await uc.start()
    page = await browser.get("https://www.whiskybase.com/account/login")

    input(">>> Press Enter once you are logged in to WhiskyBase...")

    # Re-fetch the active tab after login redirect (page ref may be stale)
    print("Collecting cookies...")
    active_page = browser.main_tab
    cookies = await active_page.send(uc.cdp.network.get_cookies())
    wb_cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "expires": c.expires,
            "httpOnly": c.http_only,
            "secure": c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies
        if "whiskybase" in (c.domain or "")
    ]

    save_cookies = wb_cookies if wb_cookies else [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "expires": c.expires,
            "httpOnly": c.http_only,
            "secure": c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies
    ]

    with open(SESSION_FILE, "w") as f:
        json.dump(save_cookies, f, indent=2)

    print(f"\nSession saved to: {SESSION_FILE}  ({len(save_cookies)} cookies)")
    print("You can now run the scraper normally — it will use this session.")
    browser.stop()


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
