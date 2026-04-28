# Spiritory Whisky Scraper

A Python data enrichment engine for whisky bottle records stored in Strapi CMS. For each bottle with a WhiskyBase ID, it scrapes reviews and tasting tags, generates multilingual marketing descriptions via Venice AI, and writes the results back to Strapi.

## What it does

For each bottle:
1. Fetches bottles from Strapi that have a `wbId` but are missing `description` or `tasting_note_1`
2. Scrapes WhiskyBase for top 2 reviews + top 5 tasting tags
3. Calls Venice AI with the **enriched prompt** (few-shot style examples + full Strapi bottle metadata + scraped reviews) to generate **4–6 sentence, 80–150 word** marketing descriptions in **5 languages** (DE, EN, ES, FR, IT) — same quality target as the one-shot correction batch
4. Writes only missing fields — never overwrites existing data, never invents content
5. **Backfill only:** saves a checkpoint (`scraper_state.json`) after each bottle so runs can be safely interrupted and resumed. Cron mode does not write this file.

## Two run modes

| Script | Purpose |
|--------|---------|
| `scraper_engine.py` | **Full backfill** — processes all Strapi bottles missing data (run once) |
| `cron_daily.py` | **Daily daemon** — processes only bottles created during the previous UTC day (runs continuously) |

---

## Installation

### Windows

> Requires Windows 10 or later.

**1. Install Python 3.12+**

Download from [python.org/downloads](https://www.python.org/downloads/) and run the installer.
During installation, **check "Add Python to PATH"**.

Verify:
```cmd
python --version
```

**2. Install Git**

Download from [git-scm.com/download/win](https://git-scm.com/download/win) and install with default options.

**3. Clone the repository**

```cmd
git clone https://github.com/AlejandroTechFlap/spiritory-whisky-scraper.git
cd spiritoni-whisky-scraper
```

**4. Create and activate virtual environment**

```cmd
python -m venv venv
venv\Scripts\activate.bat
```

If you use PowerShell:
```powershell
venv\Scripts\Activate.ps1
```
> If PowerShell blocks the script, run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**5. Install dependencies**

```cmd
pip install -r requirements.txt
```

**6. Install Patchright browser**

```cmd
patchright install chromium
```

**7. Configure environment variables**

Create a `.env` file in the project root (copy the template below):

```cmd
copy .env.example .env
```

Then open `.env` and fill in your credentials (see [Environment Variables](#environment-variables)).

**8. Run**

Full backfill (one-time, all bottles):
```cmd
python scraper_engine.py --batch 100
```

Daily cron daemon (runs continuously, midnight UTC by default):
```cmd
python cron_daily.py
```

To run the cron daemon in the background on Windows, use **Windows Task Scheduler** or open a minimized terminal:
```cmd
start /min python cron_daily.py
```

---

### Linux / macOS

**1. Install Python 3.12+**

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install python3.12 python3.12-venv python3-pip -y

# macOS (with Homebrew)
brew install python@3.12
```

**2. Clone the repository**

```bash
git clone https://github.com/AlejandroTechFlap/spiritory-whisky-scraper.git
cd spiritoni-whisky-scraper
```

**3. Create and activate virtual environment**

```bash
python3.12 -m venv venv
source venv/bin/activate
```

**4. Install dependencies**

```bash
pip install -r requirements.txt
```

**5. Install Patchright browser**

```bash
patchright install chromium
```

**6. Configure environment variables**

```bash
cp .env.example .env
nano .env   # fill in your credentials
```

**7. Run**

Full backfill (one-time, all bottles):
```bash
python scraper_engine.py --batch 100
```

Daily cron daemon (background, midnight UTC):
```bash
nohup python cron_daily.py > logs/cron.log 2>&1 &
```

Stop the daemon cleanly:
```bash
kill -TERM <pid>
```

---

## Environment Variables

Create a `.env` file in the project root with the following content:

```env
STRAPI_BASE_URL=https://your-strapi-instance.com/api
STRAPI_API_KEY=your_strapi_bearer_token

VENICE_ADMIN_KEY=your_venice_ai_api_key

# Optional: residential proxy to reduce Cloudflare bans (format: http://user:pass@ip:port)
# PROXY_URL=

# Optional: override cron trigger time (default: midnight UTC)
# CRON_HOUR=0
# CRON_MINUTE=0
```

> `.env` is gitignored and will never be committed.

---

## Usage

### Full Backfill

Processes all bottles in Strapi that are missing `description` or `tasting_note_1`. Uses an ID-based checkpoint so it can be safely stopped and resumed.

```bash
# Run with default batch size (100)
python scraper_engine.py --batch 100

# Group 5 bottles per Venice call (cheaper, automatic per-bottle fallback on failure)
python scraper_engine.py --batch 100 --venice-batch 5

# Reset checkpoint and start from scratch
python scraper_engine.py --reset-checkpoint --batch 100
```

### Daily Cron Daemon

Runs indefinitely. Wakes once per day at the configured UTC time, fetches bottles created during the **previous UTC calendar day**, and runs the full pipeline.

The daemon filters by Strapi `createdAt`, not `publishedAt`. `publishedAt` can change when a SKU is updated, which would make already-processed bottles appear again in a daily job.

```bash
# Default: midnight UTC
python cron_daily.py

# Custom trigger time (e.g. 06:30 UTC)
python cron_daily.py --hour 6 --minute 30

# Fire immediately, then enter normal schedule (useful for testing)
python cron_daily.py --run-now

# Fire for a specific UTC date, then enter normal schedule
python cron_daily.py --run-now --target-date 2026-04-27

# Group 5 bottles per Venice call inside each daily cycle
python cron_daily.py --venice-batch 5

# Production background run (Linux/macOS)
nohup python cron_daily.py > logs/cron.log 2>&1 &

# Stop cleanly (finishes current bottle, then exits)
kill -TERM <pid>
```

### CSV Reports

Every run appends results to `logs/scraper.csv`. Columns:

`logs/runs.csv` is the one-row-per-run summary. Use it first when checking
whether a scheduled/manual run found bottles for a specific UTC target date.
`logs/scraper.csv` is cumulative per bottle across all runs, so `tail` may show
rows from an earlier target date.

| Column | Description |
|--------|-------------|
| `id` | Strapi bottle ID |
| `wbId` | WhiskyBase ID |
| `name` | Bottle name |
| `description` | Generated EN description (first 500 chars) or status tag |
| `tasting_1` | First tasting note written |
| `tasting_2` | Second tasting note written |
| `mode` | `live` or `cron` |
| `timestamp` | ISO 8601 timestamp of processing |

Status tags: `[already had data]`, `[no wb data]`, `[ban]`, `[error]`

Run summary columns in `logs/runs.csv` include `run_id`, `trigger`,
`target_date`, `window_start`, `window_end`, `batch_limit`, `status`,
`fetched_count`, `processed_count`, `skipped_complete_count`, `scraped_count`,
and `error_count`.

---

## WhiskyBase Access — No Login Required

**No WhiskyBase account or session cookies are needed.**

`patchright` patches Chromium's fingerprint at the C++ level (CDP leaks, `navigator.webdriver`, UA consistency, WebGL renderer) to bypass Cloudflare. WhiskyBase serves review content without authentication — confirmed by inspecting cookies, `localStorage`, and `sessionStorage` after login: all are empty. The scraper works out of the box.

---

## Project Structure

```
scraper_engine.py         Full backfill orchestrator
cron_daily.py             Daily cron daemon
checkpoint_manager.py     Checkpoint read/write (scraper_state.json)
requirements.txt          Python dependencies

integrations/
  strapi.py               Strapi API client (fetch + update)
  whiskybase.py           Playwright scraper (reviews + tasting tags)
  whiskyhunter.py         WhiskyHunter integration

utils/
  venice.py               Venice AI client (live + batch, with typed errors)
  prompts.py              Shared prompt builders (few-shot + metadata)
  metadata.py             Strapi metadata extraction + formatter
  pipeline.py             Per-bottle helpers (build payload, flush Venice queue)
  csv_logger.py           Appends rows to logs/scraper.csv
  tasting_tags.py         Validates tags against Strapi enum
  jitter.py               Random delays for anti-bot behavior

correccion/
  prompt_templates.py     Back-compat shim → re-exports from utils/prompts
  improve_descriptions.py One-shot correction batch (pre-existing descriptions)
  batch_runner.py         Batched Venice client for the correction pipeline
  apply_corrections.py    Applies approved corrections to Strapi

tests/                    pytest suite — 56 tests covering prompts, venice, pipeline, scraper, cron

logs/
  scraper.csv             Persistent run log (all runs, append-only)
  cron.log                Cron daemon stdout (if redirected)
```

---

## Running the Tests

```bash
python -m pytest tests/ -q
```

The suite runs without requiring `openai` or `patchright` installed — `tests/conftest.py` stubs those heavy deps for import-time compatibility.

---

## License

Private — Spiritory internal use only.
