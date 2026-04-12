# Description Correction Pipeline — Spec [IMPLEMENTED]

## Purpose

Improve ~3,725 scraper-generated whisky descriptions that are too short (2-3 sentences) to match the client's quality standard (4-6 sentences, 80-150 words). The pipeline fetches bottle metadata from Strapi, enhances descriptions via Venice AI using few-shot examples from the n8n workflow, and provides a preview dashboard for client approval before applying changes.

## Data Flow

```
logs/scraper.csv
    |
    v
identify_bottles.py  -->  data/bottles_to_correct.json  (bottle IDs + names)
    |
    v
improve_descriptions.py  -->  data/corrections.json  (original + improved descriptions)
    |  (fetches metadata from Strapi, calls Venice AI)
    v
generate_dashboard.py  -->  preview-dashboard.html  (client review)
    |
    v  (after client approval)
apply_corrections.py  -->  Strapi PUT /skus/{documentId}
```

## Contracts

### identify_bottles.py
- **Input**: `../logs/scraper.csv`
- **Output**: `data/bottles_to_correct.json`
- **Filter**: rows where `description` is actual text (not `[already had data]`, `[no wb data]`, `[ban]`, `[error]`)
- **Dedup**: by `id`, keep latest timestamp

### improve_descriptions.py
- **Input**: `data/bottles_to_correct.json`
- **Output**: `data/corrections.json`
- **Flag**: `--limit N` (default 10)
- **API**: Venice AI via OpenAI-compatible client (same as `utils/gemini.py`)
- **Strapi fetch**: `GET /skus?filters[id][$eq]={id}` to get full metadata
- **Prompt**: few-shot examples + bottle metadata + current description -> 5-language JSON

### generate_dashboard.py
- **Input**: `data/corrections.json`
- **Output**: `preview-dashboard.html`
- **Style**: matches `setup-guide.html` (dark mode, glass morphism, orbs)
- **Content**: EN-only comparison cards with word count badges

### apply_corrections.py
- **Input**: `data/corrections.json`
- **Flag**: `--dry-run` (preview without writing)
- **Action**: `PUT /skus/{documentId}` with `{"description": {...5 langs...}}`
- **Requires**: fetching `documentId` from Strapi (CSV only has numeric `id`)

## Description Quality Target

- 4-6 sentences, 80-150 words per language
- Tone: premium, evocative, trustworthy
- Structure: open with product name + what makes it notable, maturation/cask details, tasting profile if available, close with value statement
- Never invent data not present in Strapi metadata or current description
- Keep brand names, numerals, ABV% exactly as source
