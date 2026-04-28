"""Regression tests for integrations.whiskybase ban-detection markers.

The Cloudflare-challenge detection is a substring scan over page HTML. Any
marker that also appears on legitimate, fully-rendered WhiskyBase pages will
false-positive every successful scrape and starve the daemon of data.
"""

from integrations.whiskybase import CF_CHALLENGE_MARKERS


# Real fragment captured from a successful WB294019 fetch (200 OK, reviews
# present). Cloudflare's bot-detection JS is embedded on every page served
# through CF, so this string is NOT a challenge indicator.
SUCCESSFUL_PAGE_CF_JS_SNIPPET = (
    "<script>(function(){var a=document.createElement('script');"
    "a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';"
    "document.getElementsByTagName('head')[0].appendChild(a);})();</script>"
)


def test_challenge_platform_substring_does_not_trigger_ban():
    """Regression: 'challenge-platform' was a false-positive marker that
    misclassified every successful scrape as a Cloudflare ban."""
    assert not any(m in SUCCESSFUL_PAGE_CF_JS_SNIPPET for m in CF_CHALLENGE_MARKERS)


def test_real_cf_interstitial_markers_still_trigger():
    interstitials = [
        "<title>Just a moment...</title>",
        "<div id='cf-browser-verification'></div>",
        "<div class='cf-turnstile' data-sitekey='x'></div>",
    ]
    for html in interstitials:
        assert any(m in html for m in CF_CHALLENGE_MARKERS), (
            f"Expected to detect a CF challenge in: {html!r}"
        )


def test_challenge_platform_is_not_in_marker_tuple():
    # If anyone re-adds the false-positive marker, this guard fires.
    assert "challenge-platform" not in CF_CHALLENGE_MARKERS
