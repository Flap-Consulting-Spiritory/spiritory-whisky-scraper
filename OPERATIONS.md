# Spiritory Whisky Scraper — Operations

| Field | Value |
|---|---|
| Repo | https://github.com/Flap-Consulting-Spiritory/spiritory-whisky-scraper (`origin`, HTTPS) |
| Local dir | `/home/john/Desktop/Projects/Spirit/Scraper/` |
| VPS dir | `/home/flapagency/spiritory/scraper/` (cloned from GitHub) |
| Runtime | Long-lived Python process (`cron_daily.py`), launched with `nohup`. NO container. |
| Cron trigger | 00:00 UTC daily — fetches bottles created during the previous UTC day, runs WhiskyBase → Venice → Strapi |
| Logs | `logs/runs.csv` (per-run summary), `logs/scraper.csv` (cumulative per-bottle), `logs/cron.log` (stdout) |

## SSH

```bash
ssh spiritory-vps                 # flapagency@89.167.24.25:27
```

## Deploy a code change (GitHub → VPS)

```bash
cd /home/john/Desktop/Projects/Spirit/Scraper
git add -A && git commit -m "..." && git push

# VPS: pull, then restart the daemon
ssh spiritory-vps "cd ~/spiritory/scraper && git pull"
ssh spiritory-vps "pkill -f 'python.*cron_daily.py' || true; sleep 2"
ssh spiritory-vps "cd ~/spiritory/scraper && nohup python3 cron_daily.py > logs/cron.log 2>&1 &"
```

## One-off run (now)

```bash
ssh spiritory-vps "cd ~/spiritory/scraper && python3 cron_daily.py --run-now"
ssh spiritory-vps "cd ~/spiritory/scraper && python3 cron_daily.py --run-now --target-date 2026-04-27"
```

## Logs / debug

```bash
ssh spiritory-vps "tail -100 ~/spiritory/scraper/logs/cron.log"
ssh spiritory-vps "tail -20 ~/spiritory/scraper/logs/runs.csv"
ssh spiritory-vps "tail -50 ~/spiritory/scraper/logs/scraper.csv | column -t -s,"

# Cross-day failure triage (gzipped rotated logs)
ssh spiritory-vps "zgrep -h 'level=error' ~/spiritory/scraper/logs/cron.log* | tail -50"
```

## Env on VPS

`/home/flapagency/spiritory/scraper/.env` — keys: `STRAPI_API_KEY`, `VENICE_API_KEY`, `WHISKYBASE_*` (if any). See `README.md` in the repo for the full list.

## Tweaking the schedule

`cron_daily.py --hour 6 --minute 30` to change UTC trigger. Override via env: `CRON_HOUR`, `CRON_MINUTE`.

## Process check

```bash
ssh spiritory-vps "ps aux | grep -E 'cron_daily|scraper' | grep -v grep"
```
