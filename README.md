# Spiritoni Whisky Scraper

A Python data enrichment engine for whisky bottle records stored in Strapi CMS. For each bottle with a WhiskyBase ID, it scrapes reviews and tasting tags, generates multilingual marketing descriptions via Venice AI, and writes the results back to Strapi.

## What it does

For each bottle:
1. Fetches bottles from Strapi that have a `wbId` but are missing `description` or `tasting_note_1`
2. Scrapes WhiskyBase for top 2 reviews + top 5 tasting tags
3. Calls Venice AI to generate 2–3 sentence marketing descriptions in **5 languages** (DE, EN, ES, FR, IT)
4. Writes only missing fields — never overwrites existing data, never invents content
5. Saves a checkpoint after each bottle so runs can be safely interrupted and resumed

## Two run modes

| Script | Purpose |
|--------|---------|
| `scraper_engine.py` | **Full backfill** — processes all Strapi bottles missing data (run once) |
| `cron_daily.py` | **Daily daemon** — processes only bottles published in the last 24h (runs continuously) |

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
git clone https://github.com/AlejandroSIlvaRodriguez/spiritoni-whisky-scraper.git
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

**6. Install Playwright browser**

```cmd
playwright install chromium
```

**7. Configure environment variables**

Create a `.env` file in the project root (copy the template below):

```cmd
copy .env.example .env
```

Then open `.env` and fill in your credentials (see [Environment Variables](#environment-variables)).

**8. Save WhiskyBase session (one-time)**

```cmd
python save_wb_session.py
```

A real Chrome window will open — log in to WhiskyBase manually, then press Enter in the terminal.

**9. Run**

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
git clone https://github.com/AlejandroSIlvaRodriguez/spiritoni-whisky-scraper.git
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

**5. Install Playwright browser**

```bash
playwright install chromium
```

**6. Configure environment variables**

```bash
cp .env.example .env
nano .env   # fill in your credentials
```

**7. Save WhiskyBase session (one-time)**

```bash
python save_wb_session.py
```

A real Chrome window will open — log in to WhiskyBase manually, then press Enter.

**8. Run**

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

WHISKYBASE_USERNAME=your_whiskybase_username
WHISKYBASE_PASSWORD=your_whiskybase_password

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

# Reset checkpoint and start from scratch
python scraper_engine.py --reset-checkpoint --batch 100
```

### Daily Cron Daemon

Runs indefinitely. Wakes once per day at the configured UTC time, fetches bottles published in the **last 24 hours**, and runs the full pipeline.

```bash
# Default: midnight UTC
python cron_daily.py

# Custom trigger time (e.g. 06:30 UTC)
python cron_daily.py --hour 6 --minute 30

# Fire immediately, then enter normal schedule (useful for testing)
python cron_daily.py --run-now

# Production background run (Linux/macOS)
nohup python cron_daily.py > logs/cron.log 2>&1 &
```

### CSV Reports

Every run appends results to `logs/scraper.csv`. Columns:

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

---

## Renewing the WhiskyBase Session

Session cookies are stored in `wb_session.json` (gitignored). They expire every 7–30 days.

Signs of expiry in the logs:
```
[WhiskyBase] ⚠️  Session expired — reviews will be blurred.
```

To renew:
```bash
python save_wb_session.py
```

---

## Project Structure

```
scraper_engine.py         Full backfill orchestrator
cron_daily.py             Daily cron daemon
checkpoint_manager.py     Checkpoint read/write (scraper_state.json)
save_wb_session.py        WhiskyBase one-time login tool
requirements.txt          Python dependencies

integrations/
  strapi.py               Strapi API client (fetch + update)
  whiskybase.py           Playwright scraper (reviews + tasting tags)
  whiskyhunter.py         WhiskyHunter integration

utils/
  gemini.py               Venice AI description generator
  csv_logger.py           Appends rows to logs/scraper.csv
  tasting_tags.py         Validates tags against Strapi enum
  jitter.py               Random delays for anti-bot behavior

logs/
  scraper.csv             Persistent run log (all runs, append-only)
  cron.log                Cron daemon stdout (if redirected)
```

---

## License

Private — Spiritoni internal use only.
