"""Generate CSV + HTML reports from corrections.json after applying changes."""

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path

CORRECTIONS_PATH = Path(__file__).parent / "data" / "corrections.json"
BOTTLES_PATH = Path(__file__).parent / "data" / "bottles_to_correct.json"
CSV_OUTPUT = Path(__file__).parent / "data" / "corrections_report.csv"
HTML_OUTPUT = Path(__file__).parent / "final-report.html"


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _load_data() -> tuple[list[dict], list[dict], dict[int, str]]:
    """Load corrections, failed items, and wbId lookup."""
    with open(CORRECTIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    corrections = data.get("corrections", [])
    failed = data.get("failed", [])

    wb_map: dict[int, str] = {}
    if BOTTLES_PATH.exists():
        with open(BOTTLES_PATH, encoding="utf-8") as f:
            bottles = json.load(f).get("bottles", [])
        wb_map = {b["id"]: b.get("wbId", "") for b in bottles}

    return corrections, failed, wb_map


def _compute_metrics(corrections: list[dict], failed: list[dict]) -> dict:
    """Compute summary metrics."""
    total = len(corrections) + len(failed)
    orig_wcs = []
    impr_wcs = []
    for c in corrections:
        ow = _word_count(c.get("original_en", ""))
        iw = _word_count(c.get("improved", {}).get("en", ""))
        orig_wcs.append(ow)
        impr_wcs.append(iw)

    avg_orig = round(sum(orig_wcs) / len(orig_wcs), 1) if orig_wcs else 0
    avg_impr = round(sum(impr_wcs) / len(impr_wcs), 1) if impr_wcs else 0
    avg_pct = round(
        sum((iw - ow) / ow * 100 for ow, iw in zip(orig_wcs, impr_wcs) if ow > 0)
        / max(sum(1 for ow in orig_wcs if ow > 0), 1),
        1,
    )
    return {
        "total": total,
        "success": len(corrections),
        "failed": len(failed),
        "rate": round(len(corrections) / total * 100, 1) if total else 0,
        "avg_orig": avg_orig,
        "avg_impr": avg_impr,
        "avg_pct": avg_pct,
    }


def write_csv(
    corrections: list[dict],
    failed: list[dict],
    wb_map: dict[int, str],
    metrics: dict,
) -> None:
    """Write the CSV report."""
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "id", "wbId", "name",
            "original_en_word_count", "improved_en_word_count",
            "improvement_pct", "status", "error_reason",
        ])
        for c in corrections:
            ow = _word_count(c.get("original_en", ""))
            iw = _word_count(c.get("improved", {}).get("en", ""))
            pct = round((iw - ow) / ow * 100, 1) if ow > 0 else 0
            w.writerow([
                c["id"], wb_map.get(c["id"], ""), c["name"],
                ow, iw, pct, "success", "",
            ])
        for fail in failed:
            w.writerow([
                fail["id"], wb_map.get(fail["id"], ""), fail["name"],
                "", "", "", "failed", fail.get("error", ""),
            ])
        # Summary
        w.writerow([])
        w.writerow(["SUMMARY"])
        w.writerow(["Total Processed", metrics["total"]])
        w.writerow(["Successful", metrics["success"]])
        w.writerow(["Failed", metrics["failed"]])
        w.writerow(["Success Rate", f"{metrics['rate']}%"])
        w.writerow(["Avg Original Words", metrics["avg_orig"]])
        w.writerow(["Avg Improved Words", metrics["avg_impr"]])
        w.writerow(["Avg Improvement %", f"{metrics['avg_pct']}%"])

    print(f"[Report] CSV: {CSV_OUTPUT}")


def write_html(
    corrections: list[dict],
    failed: list[dict],
    wb_map: dict[int, str],
    metrics: dict,
) -> None:
    """Write the HTML visual report with search + pagination."""
    cards_data = []
    for c in corrections:
        meta = c.get("metadata", {})
        badges = []
        if meta.get("brand"):
            badges.append(str(meta["brand"]))
        if meta.get("productAge"):
            badges.append(f"{meta['productAge']} Years")
        if meta.get("volumeInPercent"):
            badges.append(f"{meta['volumeInPercent']}% ABV")
        if meta.get("category"):
            badges.append(str(meta["category"]))

        cards_data.append({
            "id": c["id"],
            "wbId": wb_map.get(c["id"], ""),
            "name": c["name"],
            "original": c.get("original_en", ""),
            "improved": c.get("improved", {}).get("en", ""),
            "wc_orig": _word_count(c.get("original_en", "")),
            "wc_impr": _word_count(c.get("improved", {}).get("en", "")),
            "badges": badges,
            "status": "success",
        })
    for fail in failed:
        cards_data.append({
            "id": fail["id"],
            "wbId": wb_map.get(fail["id"], ""),
            "name": fail["name"],
            "original": "",
            "improved": "",
            "wc_orig": 0,
            "wc_impr": 0,
            "badges": [],
            "status": "failed",
            "error": fail.get("error", ""),
        })

    cards_json = json.dumps(cards_data, ensure_ascii=False)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_content = _build_html(cards_json, metrics, now)

    with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[Report] HTML: {HTML_OUTPUT}")


def _build_html(cards_json: str, m: dict, generated_at: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Spiritory — Applied Changes Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>{_get_css()}</style>
</head>
<body>
<div class="orb orb-1"></div><div class="orb orb-2"></div><div class="orb orb-3"></div>
<div class="container">
  <div class="header">
    <div class="logo">
      <div class="logo-icon">\U0001f943</div>
      <div><div class="logo-text">Spiritory</div>
      <div class="logo-sub">Applied Changes Report</div></div>
    </div>
    <h1>Description Corrections</h1>
    <p class="subtitle">All corrections applied to Strapi — {generated_at}</p>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-value">{m['success']:,}</div><div class="stat-label">Successful</div></div>
    <div class="stat-card"><div class="stat-value">{m['failed']}</div><div class="stat-label">Failed</div></div>
    <div class="stat-card"><div class="stat-value">{m['rate']}%</div><div class="stat-label">Success Rate</div></div>
    <div class="stat-card"><div class="stat-value">+{m['avg_pct']}%</div><div class="stat-label">Avg Word Increase</div></div>
  </div>
  <div class="intro-box">
    <h2>About these changes</h2>
    <p>
      Each bottle below shows the <strong>original scraper-generated English description</strong>
      (Original) next to the <strong>enhanced version</strong> (Improved) that was written to Strapi.
      Enhanced descriptions expand the original from 2&ndash;3 sentences to 4&ndash;6 sentences
      (80&ndash;150 words), add structure (product name &rarr; maturation / cask details &rarr;
      tasting profile &rarr; value statement), and are generated in <strong>five languages</strong>
      (German, English, Spanish, French, Italian) &mdash; only the English version is shown
      here for readability. Bottle metadata badges (brand, age, ABV, category) are displayed
      on every card.
    </p>
    <p>
      <strong>ABV</strong> stands for <em>Alcohol by Volume</em> &mdash; the percentage of
      pure alcohol in the bottle. Most whiskies sit at <strong>40&ndash;46% ABV</strong>
      (the industry standard, diluted with water before bottling). Bottles at
      <strong>46&ndash;54% ABV</strong> are typically non-chill-filtered or higher-proof
      expressions, while anything at <strong>55% ABV and above</strong> is considered
      <strong>cask strength</strong> &mdash; poured straight from the barrel without
      dilution, delivering the most concentrated, unfiltered expression of the cask.
    </p>
    <p>
      <strong>Scope:</strong> this report covers the <strong>{m['success']:,} bottles</strong>
      that the scraper pipeline updated in Strapi. Every bottle in this list had
      <strong>no description stored in the Strapi database</strong> but <strong>did have review
      data on WhiskyBase</strong>, which is why they were eligible for scraping and
      enhancement. The remaining bottles in the Spiritory catalog were
      <strong>not touched</strong> because they either already had a description in Strapi,
      or they had no reviews / no usable tasting data on WhiskyBase for the scraper to work
      from &mdash; and the pipeline never invents content that is not in the source.
    </p>
  </div>
  <div class="search-bar">
    <input type="text" id="search" placeholder="Search by name, ID, or wbId..." />
  </div>
  <div id="cards" class="cards"></div>
  <div class="pagination" id="pagination"></div>
  <div class="footer">Spiritory Applied Changes Report — Generated {generated_at}</div>
</div>
<script>
const DATA={cards_json};
const PER_PAGE=50;
let filtered=DATA,page=1;
const $=id=>document.getElementById(id);
function esc(s){{const d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
function renderCards(){{
  const start=(page-1)*PER_PAGE,slice=filtered.slice(start,start+PER_PAGE);
  let h='';
  slice.forEach((c,i)=>{{
    const n=start+i+1;
    const badges=c.badges.map(b=>'<span class="meta-badge">'+esc(b)+'</span>').join('');
    const status=c.status==='failed'?'<span class="status-failed">FAILED: '+esc(c.error||'')+'</span>':'';
    h+='<div class="comparison-card'+(c.status==='failed'?' card-failed':'')+'">'+
      '<div class="card-header"><div class="card-number">'+n+'</div>'+
      '<div class="card-info"><div class="card-title">'+esc(c.name)+'</div>'+
      '<div class="card-badges">'+badges+status+'</div></div></div>';
    if(c.status==='success'){{
      h+='<div class="comparison-grid">'+
        '<div class="desc-box original"><div class="desc-label">'+
        '<span class="desc-tag tag-original">Original</span>'+
        '<span class="word-count">'+c.wc_orig+' words</span></div>'+
        '<p class="desc-text">'+esc(c.original)+'</p></div>'+
        '<div class="desc-box improved"><div class="desc-label">'+
        '<span class="desc-tag tag-improved">Improved</span>'+
        '<span class="word-count">'+c.wc_impr+' words</span></div>'+
        '<p class="desc-text">'+esc(c.improved)+'</p></div></div>';
    }}
    h+='</div>';
  }});
  $('cards').innerHTML=h;
  renderPagination();
}}
function renderPagination(){{
  const total=Math.ceil(filtered.length/PER_PAGE);
  if(total<=1){{$('pagination').innerHTML='';return;}}
  let h='';
  const range=3;
  for(let p=1;p<=total;p++){{
    if(p===1||p===total||Math.abs(p-page)<=range){{
      h+='<button class="page-btn'+(p===page?' active':'')+'" onclick="goPage('+p+')">'+p+'</button>';
    }}else if(p===2||p===total-1){{h+='<span class="ellipsis">...</span>';}}
  }}
  $('pagination').innerHTML=h;
}}
window.goPage=function(p){{page=p;renderCards();window.scrollTo(0,0);}};
$('search').addEventListener('input',function(){{
  const q=this.value.toLowerCase();
  filtered=q?DATA.filter(c=>c.name.toLowerCase().includes(q)||String(c.id).includes(q)||(c.wbId||'').toLowerCase().includes(q)):DATA;
  page=1;renderCards();
}});
renderCards();
</script>
</body></html>"""


def _get_css() -> str:
    return """*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;min-height:100vh;background:#0a0a1a;
background-image:radial-gradient(ellipse at 20% 20%,rgba(245,85,1,.18) 0%,transparent 50%),
radial-gradient(ellipse at 80% 80%,rgba(5,17,242,.18) 0%,transparent 50%),
radial-gradient(ellipse at 50% 50%,rgba(80,0,120,.12) 0%,transparent 60%);
color:#e2e8f0;overflow-x:hidden}
.orb{position:fixed;border-radius:50%;filter:blur(80px);opacity:.25;pointer-events:none;animation:float 8s ease-in-out infinite}
.orb-1{width:500px;height:500px;background:#f55501;top:-100px;left:-100px}
.orb-2{width:400px;height:400px;background:#0511f2;bottom:-100px;right:-100px;animation-delay:4s}
.orb-3{width:300px;height:300px;background:#9333ea;top:50%;left:50%;transform:translate(-50%,-50%);animation-delay:2s}
@keyframes float{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-30px) scale(1.05)}}
.container{max-width:960px;margin:0 auto;padding:60px 24px 80px;position:relative;z-index:1}
.header{text-align:center;margin-bottom:48px}
.logo{display:inline-flex;align-items:center;gap:12px;margin-bottom:20px}
.logo-icon{width:48px;height:48px;background:linear-gradient(135deg,#f55501,#0511f2);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px}
.logo-text{font-size:22px;font-weight:800;letter-spacing:-.5px}
.logo-sub{font-size:12px;color:rgba(255,255,255,.5);text-transform:uppercase;letter-spacing:2px;margin-top:2px}
h1{font-size:38px;font-weight:800;letter-spacing:-1.5px;line-height:1.1;background:linear-gradient(135deg,#fff 0%,rgba(255,255,255,.6) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:12px}
.subtitle{font-size:15px;color:rgba(255,255,255,.45);line-height:1.6}
.stats-bar{display:flex;gap:16px;justify-content:center;margin-bottom:32px;flex-wrap:wrap}
.stat-card{background:rgba(255,255,255,.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:16px 28px;text-align:center}
.stat-value{font-size:28px;font-weight:800;background:linear-gradient(135deg,#f55501,#0511f2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,.4);margin-top:4px}
.intro-box{background:rgba(255,255,255,.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:28px 32px;margin-bottom:32px}
.intro-box h2{font-size:18px;font-weight:700;color:#f1f5f9;margin-bottom:14px;letter-spacing:-.3px}
.intro-box p{font-size:14px;line-height:1.75;color:rgba(255,255,255,.7);margin-bottom:12px}
.intro-box p:last-child{margin-bottom:0}
.intro-box strong{color:rgba(255,255,255,.92);font-weight:600}
.intro-box em{color:rgba(245,85,1,.9);font-style:normal;font-weight:500}
.search-bar{margin-bottom:24px;text-align:center}
.search-bar input{width:100%;max-width:500px;padding:12px 20px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#e2e8f0;font-size:14px;outline:none;transition:border-color .2s}
.search-bar input:focus{border-color:rgba(245,85,1,.5)}
.search-bar input::placeholder{color:rgba(255,255,255,.3)}
.cards{display:flex;flex-direction:column;gap:24px}
.comparison-card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;overflow:hidden;transition:border-color .2s}
.comparison-card:hover{border-color:rgba(255,255,255,.15)}
.card-failed{border-color:rgba(239,68,68,.3)}
.card-header{display:flex;align-items:center;gap:16px;padding:20px 24px;border-bottom:1px solid rgba(255,255,255,.06)}
.card-number{width:36px;height:36px;min-width:36px;border-radius:50%;background:linear-gradient(135deg,#f55501,#0511f2);display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;color:#fff;box-shadow:0 0 0 4px rgba(245,85,1,.15)}
.card-info{flex:1}
.card-title{font-size:16px;font-weight:700;color:#f1f5f9;margin-bottom:6px}
.card-badges{display:flex;flex-wrap:wrap;gap:6px}
.meta-badge{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px;background:rgba(255,255,255,.06);color:rgba(255,255,255,.5);border:1px solid rgba(255,255,255,.08)}
.status-failed{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px;background:rgba(239,68,68,.12);color:#ef4444;border:1px solid rgba(239,68,68,.2)}
.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media(max-width:700px){.comparison-grid{grid-template-columns:1fr}}
.desc-box{padding:20px 24px}
.desc-box.original{border-right:1px solid rgba(255,255,255,.06)}
@media(max-width:700px){.desc-box.original{border-right:none;border-bottom:1px solid rgba(255,255,255,.06)}}
.desc-label{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.desc-tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;padding:3px 10px;border-radius:6px}
.tag-original{background:rgba(251,191,36,.12);color:#fbbf24;border:1px solid rgba(251,191,36,.2)}
.tag-improved{background:rgba(34,197,94,.12);color:#22c55e;border:1px solid rgba(34,197,94,.2)}
.word-count{font-size:11px;color:rgba(255,255,255,.3);font-weight:500}
.desc-text{font-size:14px;line-height:1.7;color:rgba(255,255,255,.7)}
.desc-box.improved .desc-text{color:rgba(255,255,255,.85)}
.pagination{display:flex;gap:6px;justify-content:center;margin-top:32px;flex-wrap:wrap}
.page-btn{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);color:#e2e8f0;padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;transition:all .2s}
.page-btn:hover{background:rgba(255,255,255,.12)}
.page-btn.active{background:linear-gradient(135deg,#f55501,#0511f2);border-color:transparent}
.ellipsis{color:rgba(255,255,255,.3);padding:8px 4px;font-size:13px}
.footer{text-align:center;margin-top:48px;font-size:12px;color:rgba(255,255,255,.2)}"""


def main() -> None:
    corrections, failed, wb_map = _load_data()
    if not corrections and not failed:
        print("[Report] No data in corrections.json. Run improve_descriptions.py first.")
        return

    metrics = _compute_metrics(corrections, failed)
    write_csv(corrections, failed, wb_map, metrics)
    write_html(corrections, failed, wb_map, metrics)

    print(f"\n[Report] Summary: {metrics['success']} successful, {metrics['failed']} failed")
    print(f"[Report] Success rate: {metrics['rate']}%")
    print(f"[Report] Avg words: {metrics['avg_orig']} -> {metrics['avg_impr']} (+{metrics['avg_pct']}%)")


if __name__ == "__main__":
    main()
