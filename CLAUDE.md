# Spiritory Whisky Scraper

## Project Overview

The **Spiritory Whisky Scraper** is a Python-based data enrichment engine for whisky bottle records stored in a Strapi CMS backend. For each bottle with a WhiskyBase ID (`wbId`), the engine scrapes reviews and tasting tags from **WhiskyBase**, generates multilingual marketing descriptions via **Venice AI** (OpenAI-compatible), and writes the results back to Strapi.

### What it does per bottle
1. Fetches bottles from Strapi that have a `wbId` but are missing `description` or `tasting_note_1`
2. Scrapes the WhiskyBase page for that bottle: top 2 reviews + top 5 tasting tags
3. If reviews were found, calls Venice AI to generate a 2–3 sentence marketing description in 5 languages (de, en, es, fr, it)
4. Only writes fields that are missing AND have real source data — never overwrites existing data, never invents content
5. Saves a checkpoint after each successful bottle so runs can be safely resumed

### Key Features
- **Two run modes:** Full backfill (`scraper_engine.py`) and daily cron daemon (`cron_daily.py`)
- **Stateful / Resumable:** `scraper_engine.py` uses `scraper_state.json` to track the last processed bottle ID
- **Anti-Bot Resilience:** Random jitter delays, `patchright` (CDP-level fingerprint patching) + context rotation — no login or session cookies required
- **No hallucinations:** Venice AI is only called when WhiskyBase returned actual review text

---

## Project Structure

```
scraper_engine.py         Full backfill — processes all Strapi bottles missing data (run once)
cron_daily.py             Daily daemon — processes bottles published in the last 24h (runs continuously)
checkpoint_manager.py     Read/write scraper_state.json (used by scraper_engine only)
requirements.txt          Python dependencies

integrations/
  strapi.py               Live Strapi: paginated fetch + PUT update
  whiskybase.py           Playwright scraper — reviews + tasting tags
  whiskyhunter.py         WhiskyHunter integration (pricing data)

utils/
  gemini.py               Venice AI — multilingual description generator
  csv_logger.py           CSVLogger — writes logs/scraper_{date}_{time}_{mode}.csv
  tasting_tags.py         normalize_tag() — validates against Strapi enum
  jitter.py               random_delay() for humanized request timing

logs/                     CSV reports from each run (auto-generated, gitignored)
scraper_state.json        Checkpoint state file (auto-generated, do not commit)
```

---

## Setup

Requires Python 3.12+.

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Patchright browser (required for WhiskyBase scraping)
patchright install chromium
```

> **No WhiskyBase login required.** `patchright` patches Chromium's browser fingerprint at the C++ level to bypass Cloudflare, and WhiskyBase serves review content without authentication — confirmed by inspecting cookies, `localStorage`, and `sessionStorage` after login: all are empty. No session file is needed.

### Environment Variables (`.env`)
```
STRAPI_BASE_URL=https://strapi.spiritory.com/api
STRAPI_API_KEY=<your Strapi bearer token>
VENICE_ADMIN_KEY=<Venice AI API key>

# Optional — residential proxy to reduce Cloudflare bans (http://user:pass@ip:port)
# PROXY_URL=

# Optional — override cron trigger time (default: midnight UTC)
# CRON_HOUR=0
# CRON_MINUTE=0
```

---

## Running the Scraper

### Full Backfill — one-time run over all Strapi bottles

Fetches every bottle in Strapi that has a `wbId` but is missing `description` or `tasting_note_1`. Uses an ID-based checkpoint so it can be safely interrupted and resumed.

```bash
python scraper_engine.py --batch 100

# Reset checkpoint and start from the beginning
python scraper_engine.py --reset-checkpoint --batch 100
```

Output: CSV report in `logs/scraper_{date}_{time}_live.csv`

### Daily Cron Daemon — production continuous mode

Runs as a long-lived background process. Wakes at the configured UTC time each day, fetches only bottles published in the **last 24 hours**, runs the full pipeline, and writes a CSV report.

```bash
# Foreground (for testing)
python cron_daily.py --hour 0 --minute 0

# Fire immediately then enter normal schedule (useful to verify setup)
python cron_daily.py --run-now

# Background production (redirect output to log file)
nohup python cron_daily.py > logs/cron.log 2>&1 &

# Custom trigger time
python cron_daily.py --hour 6 --minute 30

# Stop cleanly
kill -TERM <pid>   # daemon finishes current bottle then exits
```

Output: CSV report in `logs/scraper_{date}_{time}_cron.csv` after each daily run.

---

## Checkpoint / Resume Behavior

Applies to **`scraper_engine.py` only**. After every successfully processed bottle, the bottle's ID is saved to `scraper_state.json`. If the script stops for any reason (ban, network error, Ctrl+C), re-running resumes from exactly that point.

`cron_daily.py` does **not** use the ID-based checkpoint — it uses Strapi's `publishedAt` field to filter to the last 24 hours. Each daily run is self-contained.

To reset the backfill checkpoint:
```bash
python scraper_engine.py --reset-checkpoint --batch 100
# or manually:
rm scraper_state.json
```

---

## WhiskyBase Access — No Login Required

**WhiskyBase does not require authentication to read reviews.**

After exhaustive investigation (multiple nodriver/CDP approaches, browser cookie inspection via Cookie-Editor, and manual `localStorage`/`sessionStorage` checks), it was confirmed that:
- WhiskyBase sets **zero cookies** after login
- `localStorage` and `sessionStorage` are both empty (`{}`)
- Review content is served to any request that passes Cloudflare's bot check

`patchright` handles the Cloudflare bypass by patching Chromium's fingerprint at the C++ level (CDP leaks, WebGL renderer, `navigator.webdriver`, UA consistency). No credentials, session file, or `save_wb_session.py` script is needed. The `wb_session.json` file and `WHISKYBASE_USERNAME`/`WHISKYBASE_PASSWORD` env vars have been removed.

> **History:** `save_wb_session.py` was originally written using **nodriver** to collect cookies via CDP (`network.get_cookies`). Chrome 130+ introduced a `CookiePartitionKey` parsing bug that causes all CDP cookie retrieval methods to hang indefinitely. After exhausting every CDP approach (`storage.get_cookies`, `network.get_all_cookies`, explicit-URL variants, response header interception), we discovered via Cookie-Editor that WhiskyBase simply has no cookies to collect — making the entire session-saving approach unnecessary.

---

## Pre-Production Validation Checklist

```bash
# 1. Confirm Patchright browser is installed
patchright install chromium

# 2. Test Strapi connectivity
python -c "
from dotenv import load_dotenv; load_dotenv()
from integrations.strapi import fetch_bottles
b = fetch_bottles(limit=3)
print(f'OK: {len(b)} bottles, first id={b[0][\"id\"] if b else None}')
"

# 3. Test Venice AI (description generation)
python -c "
from dotenv import load_dotenv; load_dotenv()
from utils.gemini import generate_description
print(generate_description('Smoky, rich, vanilla finish.', 'Test Whisky'))
"

# 4. Test cron daemon startup
python cron_daily.py --hour 0 --minute 0
# Expected: "[Cron] Next run scheduled for ... UTC (N.Nh from now)."
# Ctrl+C to stop

# 5. Confirm imports are clean
python -c "from scraper_engine import run_scraper; print('OK')"
python -c "from cron_daily import run_cron_cycle; print('OK')"
```

---

## Development Conventions

- **Modular integrations:** Each data source lives in `integrations/`. Interface: `fetch_bottles() -> list[dict]` / `update_bottle(id, payload) -> bool`
- **No hallucinations:** Only call Venice AI if `description_en_raw` from WhiskyBase is non-empty. Only write tasting notes if WhiskyBase returned tags
- **Error handling:** `ScrapeBanException` → Tenacity retries with 30–180s exponential backoff (5 attempts). If that exhausts → outer ban loop with progressive cooldowns (10→20→40→60 min), max 6 retries. `ScrapeHardBanException` → propagates immediately. All other per-bottle exceptions → log `[error]` and halt
- **Warnings suppression:** `google.generativeai` deprecation warnings are suppressed at entry points with `warnings.filterwarnings`
- **Type hints:** Maintain `def fetch_bottles() -> list[dict]:` style across all functions
- **Jitter:** Always call `random_delay()` before WhiskyBase requests

---

## Global Invariants (apply to all sessions)

See `~/.claude/CLAUDE.md` for the full rules. Summary:

1. **Document First** — update/create spec with `[DRAFT]` before writing any code
2. **Max 300 lines per file** — split proactively at 250 lines; single responsibility; DRY
3. **WebSearch before coding** — always fetch latest docs for any external library or API
4. **MANDATORY: Ask before architecture** — never assume folder structure, patterns, libraries, schemas, or any architectural decision. Always ask Alejandro and wait for confirmation
