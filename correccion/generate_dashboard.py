"""Step 3: Generate a static HTML preview dashboard for client review."""

import json
import html
from pathlib import Path

INPUT_PATH = Path(__file__).parent / "data" / "corrections.json"
OUTPUT_PATH = Path(__file__).parent / "preview-dashboard.html"


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _build_cards_html(corrections: list[dict]) -> str:
    cards = []
    for i, c in enumerate(corrections, 1):
        name = _escape(c["name"])
        original = _escape(c.get("original_en", ""))
        improved = _escape(c.get("improved", {}).get("en", ""))
        meta = c.get("metadata", {})

        # Build metadata badges
        badges = []
        if meta.get("brand"):
            badges.append(_escape(str(meta["brand"])))
        if meta.get("productAge"):
            badges.append(f"{_escape(str(meta['productAge']))} Years")
        if meta.get("volumeInPercent"):
            badges.append(f"{_escape(str(meta['volumeInPercent']))}% ABV")
        if meta.get("category"):
            badges.append(_escape(str(meta["category"])))

        badges_html = "".join(
            f'<span class="meta-badge">{b}</span>' for b in badges
        )

        wc_orig = _word_count(c.get("original_en", ""))
        wc_impr = _word_count(c.get("improved", {}).get("en", ""))

        cards.append(f"""
        <div class="comparison-card">
          <div class="card-header">
            <div class="card-number">{i}</div>
            <div class="card-info">
              <div class="card-title">{name}</div>
              <div class="card-badges">{badges_html}</div>
            </div>
          </div>
          <div class="comparison-grid">
            <div class="desc-box original">
              <div class="desc-label">
                <span class="desc-tag tag-original">Original</span>
                <span class="word-count">{wc_orig} words</span>
              </div>
              <p class="desc-text">{original}</p>
            </div>
            <div class="desc-box improved">
              <div class="desc-label">
                <span class="desc-tag tag-improved">Improved</span>
                <span class="word-count">{wc_impr} words</span>
              </div>
              <p class="desc-text">{improved}</p>
            </div>
          </div>
        </div>""")

    return "\n".join(cards)


def generate_dashboard() -> None:
    """Load corrections and generate the preview HTML dashboard."""
    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    corrections = data.get("corrections", [])
    total_candidates = data.get("total", 0)
    sample_size = len(corrections)

    if not corrections:
        print("[Dashboard] No corrections found. Run improve_descriptions.py first.")
        return

    cards_html = _build_cards_html(corrections)
    html_content = _build_full_html(cards_html, total_candidates, sample_size)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[Dashboard] Generated: {OUTPUT_PATH}")
    print(f"[Dashboard] Showing {sample_size} bottles for review")


def _build_full_html(
    cards_html: str, total_candidates: int, sample_size: int
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Spiritory \u2014 Description Correction Preview</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      background: #0a0a1a;
      background-image:
        radial-gradient(ellipse at 20% 20%, rgba(245,85,1,0.18) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 80%, rgba(5,17,242,0.18) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 50%, rgba(80,0,120,0.12) 0%, transparent 60%);
      color: #e2e8f0;
      overflow-x: hidden;
    }}

    .orb {{
      position: fixed;
      border-radius: 50%;
      filter: blur(80px);
      opacity: 0.25;
      pointer-events: none;
      animation: float 8s ease-in-out infinite;
    }}
    .orb-1 {{ width: 500px; height: 500px; background: #f55501; top: -100px; left: -100px; }}
    .orb-2 {{ width: 400px; height: 400px; background: #0511f2; bottom: -100px; right: -100px; animation-delay: 4s; }}
    .orb-3 {{ width: 300px; height: 300px; background: #9333ea; top: 50%; left: 50%; transform: translate(-50%,-50%); animation-delay: 2s; }}

    @keyframes float {{
      0%,100% {{ transform: translateY(0) scale(1); }}
      50% {{ transform: translateY(-30px) scale(1.05); }}
    }}

    .container {{
      max-width: 960px;
      margin: 0 auto;
      padding: 60px 24px 80px;
      position: relative;
      z-index: 1;
    }}

    .header {{
      text-align: center;
      margin-bottom: 48px;
    }}
    .logo {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
    }}
    .logo-icon {{
      width: 48px; height: 48px;
      background: linear-gradient(135deg, #f55501, #0511f2);
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      font-size: 22px;
    }}
    .logo-text {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
    .logo-sub {{ font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 2px; margin-top: 2px; }}
    h1 {{
      font-size: 38px;
      font-weight: 800;
      letter-spacing: -1.5px;
      line-height: 1.1;
      background: linear-gradient(135deg, #ffffff 0%, rgba(255,255,255,0.6) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 12px;
    }}
    .subtitle {{
      font-size: 15px;
      color: rgba(255,255,255,0.45);
      line-height: 1.6;
    }}

    /* Stats bar */
    .stats-bar {{
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-bottom: 40px;
    }}
    .stat-card {{
      background: rgba(255,255,255,0.05);
      backdrop-filter: blur(20px);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 14px;
      padding: 16px 28px;
      text-align: center;
    }}
    .stat-value {{
      font-size: 28px;
      font-weight: 800;
      background: linear-gradient(135deg, #f55501, #0511f2);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .stat-label {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: rgba(255,255,255,0.4);
      margin-top: 4px;
    }}

    /* Comparison cards */
    .cards {{ display: flex; flex-direction: column; gap: 24px; }}

    .comparison-card {{
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 20px;
      overflow: hidden;
      transition: border-color 0.2s;
    }}
    .comparison-card:hover {{ border-color: rgba(255,255,255,0.15); }}

    .card-header {{
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 20px 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .card-number {{
      width: 36px; height: 36px; min-width: 36px;
      border-radius: 50%;
      background: linear-gradient(135deg, #f55501, #0511f2);
      display: flex; align-items: center; justify-content: center;
      font-size: 14px; font-weight: 700; color: #fff;
      box-shadow: 0 0 0 4px rgba(245,85,1,0.15);
    }}
    .card-info {{ flex: 1; }}
    .card-title {{
      font-size: 16px;
      font-weight: 700;
      color: #f1f5f9;
      margin-bottom: 6px;
    }}
    .card-badges {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .meta-badge {{
      font-size: 11px;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 20px;
      background: rgba(255,255,255,0.06);
      color: rgba(255,255,255,0.5);
      border: 1px solid rgba(255,255,255,0.08);
    }}

    /* Description grid */
    .comparison-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
    }}
    @media (max-width: 700px) {{
      .comparison-grid {{ grid-template-columns: 1fr; }}
    }}

    .desc-box {{
      padding: 20px 24px;
    }}
    .desc-box.original {{
      border-right: 1px solid rgba(255,255,255,0.06);
    }}
    @media (max-width: 700px) {{
      .desc-box.original {{ border-right: none; border-bottom: 1px solid rgba(255,255,255,0.06); }}
    }}

    .desc-label {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .desc-tag {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 1px;
      padding: 3px 10px;
      border-radius: 6px;
    }}
    .tag-original {{
      background: rgba(251,191,36,0.12);
      color: #fbbf24;
      border: 1px solid rgba(251,191,36,0.2);
    }}
    .tag-improved {{
      background: rgba(34,197,94,0.12);
      color: #22c55e;
      border: 1px solid rgba(34,197,94,0.2);
    }}
    .word-count {{
      font-size: 11px;
      color: rgba(255,255,255,0.3);
      font-weight: 500;
    }}

    .desc-text {{
      font-size: 14px;
      line-height: 1.7;
      color: rgba(255,255,255,0.7);
    }}
    .desc-box.improved .desc-text {{
      color: rgba(255,255,255,0.85);
    }}

    .footer {{
      text-align: center;
      margin-top: 48px;
      font-size: 12px;
      color: rgba(255,255,255,0.2);
    }}
  </style>
</head>
<body>

  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>

  <div class="container">

    <div class="header">
      <div class="logo">
        <div class="logo-icon">\U0001f943</div>
        <div>
          <div class="logo-text">Spiritory</div>
          <div class="logo-sub">Description Correction</div>
        </div>
      </div>
      <h1>Description Preview</h1>
      <p class="subtitle">Side-by-side comparison of original (scraper) vs improved descriptions</p>
    </div>

    <div class="stats-bar">
      <div class="stat-card">
        <div class="stat-value">{total_candidates:,}</div>
        <div class="stat-label">Total Candidates</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{sample_size}</div>
        <div class="stat-label">Preview Sample</div>
      </div>
    </div>

    <div class="cards">
      {cards_html}
    </div>

    <div class="footer">
      Spiritory Description Correction Preview \u2014 Generated for client review
    </div>

  </div>
</body>
</html>"""


if __name__ == "__main__":
    generate_dashboard()
