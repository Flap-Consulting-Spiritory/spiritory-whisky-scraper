"""Shared Venice AI prompt builders — used by both the live cron pipeline
(`scraper_engine.py`) and the one-shot correction pipeline
(`correccion/improve_descriptions.py`).

Two families of prompts live here:

* `build_live_prompt` / `build_live_batch_prompt` — CREATE a new description
  from freshly-scraped WhiskyBase reviews + Strapi bottle metadata. Used on
  newly-published bottles by the daily cron.

* `build_improvement_prompt` / `build_batch_improvement_prompt` — ENHANCE an
  existing short description. Used by the correction batch.

Both families share the same few-shot style examples and metadata formatter
(see `utils.metadata`), so output quality is consistent across live and
correction runs.
"""

from utils.metadata import format_metadata_block

STYLE_EXAMPLES: list[dict[str, str]] = [
    {
        "name": "Glenfiddich 16 Years Old Aston Martin Formula One 2025",
        "text": (
            "The Glenfiddich 16 Years Old Aston Martin Formula One 2025 is an exclusive "
            "limited edition celebrating the partnership between Glenfiddich and the Aston "
            "Martin F1™ Team. Matured in a unique combination of American Oak Wine Casks, "
            "New American Barrels, and Second-fill Bourbon Casks, this single malt delivers "
            "layered notes of maple syrup, caramelised ginger, fresh fruits, and Chantilly "
            "cream. Bottled at 43% ABV, it impresses with a silky mouthfeel, elegant sweetness, "
            "and an exceptionally smooth finish. A modern Speyside classic that embodies "
            "craftsmanship, innovation, and iconic design."
        ),
    },
    {
        "name": "Ardbeg 15 Years Old Anthology – The Beithir’s Tale",
        "text": (
            "The Ardbeg 15 Years Old Anthology – The Beithir’s Tale is the final release "
            "in the acclaimed Anthology series, serving as the grand finale to this remarkable "
            "trilogy. Matured in specially crafted bourbon casks, this 15-year-old Islay single "
            "malt reveals a rich interplay of smoked butter, vanilla, menthol, and pine aromas "
            "– beautifully balanced with Ardbeg’s signature peaty character. Bottled at 46% "
            "ABV, non-chill filtered and natural in color, it delivers a sweet-complex depth "
            "that captivates both collectors and enthusiasts. Awarded ‘Gold Outstanding’ "
            "(98 points) at the IWSC 2025, it will be available from August 12, 2025, on "
            "Ardbeg.com and in Ardbeg Embassies, and from August 26 in specialist retailers."
        ),
    },
    {
        "name": "Glenfiddich 21 Years Old Gran Reserva Chinese New Year 2025",
        "text": (
            "The Glenfiddich 21 Years Old Gran Reserva Chinese New Year 2025 is a limited "
            "edition release celebrating the Lunar New Year on January 29, 2025. Matured for "
            "at least 21 years in a selection of ex-bourbon and Oloroso sherry casks, it is "
            "finished in Caribbean rum casks for a unique layer of richness and exotic "
            "character. Presented in a beautifully designed gift box featuring the iconic "
            "Highland stag, created by Finnish artist Santtu Mustonen, this award-winning "
            "classic is both a collector’s treasure and a refined tasting experience."
        ),
    },
    {
        "name": "Macallan The Harmony Collection – Phoenix Honey Orchid Tea (JING)",
        "text": (
            "The Macallan The Harmony Collection – Inspired by Phoenix Honey Orchid Tea in "
            "Collaboration with JING is a limited release available from August 5, 2025, in "
            "selected markets. Matured predominantly in American oak sherry casks, complemented "
            "by European oak sherry casks and ex-bourbon barrels, this single malt delivers a "
            "harmonious flavor profile inspired by the exquisite Phoenix Honey Orchid Oolong "
            "tea from the Phoenix Mountains in Guangdong, China. Bottled at 43.9% ABV, it "
            "offers warm honey notes alongside ripe peach, apricot, tropical fruit, and "
            "delicate toffee. A beautifully crafted whisky that unites tea culture with "
            "Macallan’s signature craftsmanship."
        ),
    },
    {
        "name": "Macallan Guardian Oak The Harmony Collection",
        "text": (
            "The Macallan The Harmony Collection, an exquisite single malt from the prestigious "
            "Macallan distillery in Speyside, Scotland, represents the essence of Scottish "
            "distillation. The bottling in 2024 promises exceptional quality, reinforced by an "
            "alcohol strength of 44.2%. With a bottle size of 700ml, this fine drop is perfect "
            "for aficionados who appreciate the depth and complexity of Speyside whiskies. The "
            "character of this whisky is characterised by a harmonious balance that is the "
            "result of careful maturation and selection. For connoisseurs and collectors of "
            "Macallan whiskies, this single malt from the Harmony Collection is an "
            "indispensable highlight in any collection."
        ),
    },
]


def _format_examples() -> str:
    parts = []
    for i, ex in enumerate(STYLE_EXAMPLES, 1):
        parts.append(f"Example {i} — {ex['name']}:\n\"{ex['text']}\"")
    return "\n\n".join(parts)


_SHARED_RULES = (
    "- Write 4–6 sentences (80–150 words) per language.\n"
    "- Tone: premium, evocative, trustworthy — match the style examples below.\n"
    "- Structure: open with product name and what makes it notable, then maturation/"
    "cask details, tasting profile, close with a value statement.\n"
    "- NEVER invent facts not present in the inputs provided for that bottle.\n"
    "- Keep brand/product names, numerals, and ABV% exactly as given.\n"
    "- If age, cask type, or ABV are in the metadata, weave them naturally into the text.\n"
)


def build_live_prompt(bottle_name: str, reviews_text: str, metadata: dict) -> str:
    """CREATE a new description from scraped reviews + Strapi metadata.
    Used by the daily cron on newly-published bottles."""
    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to WRITE a new "
        "product description for this bottle using ONLY the scraped WhiskyBase reviews "
        "and Strapi metadata provided.\n\n"
        "RULES:\n"
        f"{_SHARED_RULES}"
        "- Use the reviews as your primary tasting-profile source; weave metadata around them.\n"
        "- Output STRICT JSON only, no markdown fences, no extra text:\n"
        '  {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}\n\n'
        f"STYLE EXAMPLES (match this quality and length):\n{_format_examples()}\n\n"
        f"BOTTLE METADATA:\n{format_metadata_block(metadata)}\n\n"
        f'SCRAPED WHISKYBASE REVIEWS (use these for the tasting profile):\n"{reviews_text}"\n\n'
        f'BOTTLE NAME: "{bottle_name}"\n\n'
        "Now write the description in all 5 languages. Return ONLY the JSON."
    )


def build_live_batch_prompt(items: list[dict]) -> str:
    """CREATE N new descriptions in one Venice call. Each item requires
    {id, name, reviews_text, metadata}."""
    bottle_blocks = []
    for idx, item in enumerate(items, 1):
        bottle_blocks.append(
            f"--- BOTTLE {idx} ---\n"
            f"id: {item['id']}\n"
            f"name: {item['name']}\n"
            f"metadata:\n{format_metadata_block(item.get('metadata', {}))}\n"
            f'reviews: "{item.get("reviews_text", "")}"'
        )
    expected_ids = [item["id"] for item in items]
    count = len(items)
    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to WRITE "
        f"{count} new product descriptions, one per bottle, using ONLY that bottle's "
        "scraped WhiskyBase reviews and Strapi metadata.\n\n"
        "RULES (apply to EVERY bottle independently):\n"
        f"{_SHARED_RULES}"
        "- Use each bottle's reviews as its primary tasting-profile source.\n"
        "- Treat each bottle in isolation — do NOT mix facts between bottles.\n"
        "- You MUST return one result for EVERY input bottle, in the same order.\n"
        "- Output STRICT JSON only, no markdown fences, no extra text. Schema:\n"
        '  {"results": [\n'
        '    {"id": <int>, "improved": {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}},\n'
        "    ...\n"
        "  ]}\n"
        f"- The \"id\" field of each result MUST match exactly one of: {expected_ids}.\n\n"
        f"STYLE EXAMPLES (match this quality and length):\n{_format_examples()}\n\n"
        f"INPUT BOTTLES ({count} total):\n" + "\n\n".join(bottle_blocks) + "\n\n"
        f"Now write the description in all 5 languages for each of the {count} bottles. "
        "Return ONLY the JSON object with the \"results\" array."
    )


def build_improvement_prompt(bottle_name: str, current_desc_en: str, metadata: dict) -> str:
    """ENHANCE an existing short description. Used by the correction pipeline."""
    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to ENHANCE "
        "an existing short product description into a richer, more detailed version.\n\n"
        "RULES:\n"
        f"{_SHARED_RULES}"
        "- Output STRICT JSON only, no markdown fences, no extra text:\n"
        '  {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}\n\n'
        f"STYLE EXAMPLES (match this quality and length):\n{_format_examples()}\n\n"
        f"BOTTLE METADATA:\n{format_metadata_block(metadata)}\n\n"
        f'CURRENT DESCRIPTION (enhance this — do not discard its content):\n"{current_desc_en}"\n\n'
        "Now write the enhanced description in all 5 languages. Return ONLY the JSON."
    )


def build_batch_improvement_prompt(items: list[dict]) -> str:
    """Batched ENHANCE prompt. Each item requires {id, name, current_desc_en, metadata}."""
    bottle_blocks = []
    for idx, item in enumerate(items, 1):
        bottle_blocks.append(
            f"--- BOTTLE {idx} ---\n"
            f"id: {item['id']}\n"
            f"name: {item['name']}\n"
            f"metadata:\n{format_metadata_block(item.get('metadata', {}))}\n"
            f'current_description: "{item.get("current_desc_en", "")}"'
        )
    expected_ids = [item["id"] for item in items]
    count = len(items)
    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to ENHANCE "
        f"{count} existing short product descriptions into richer, more detailed versions.\n\n"
        "RULES (apply to EVERY bottle independently):\n"
        f"{_SHARED_RULES}"
        "- Treat each bottle in isolation — do NOT mix facts between bottles.\n"
        "- You MUST return one result for EVERY input bottle, in the same order.\n"
        "- Output STRICT JSON only, no markdown fences, no extra text. Schema:\n"
        '  {"results": [\n'
        '    {"id": <int>, "improved": {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}},\n'
        "    ...\n"
        "  ]}\n"
        f"- The \"id\" field of each result MUST match exactly one of: {expected_ids}.\n\n"
        f"STYLE EXAMPLES (match this quality and length):\n{_format_examples()}\n\n"
        f"INPUT BOTTLES ({count} total):\n" + "\n\n".join(bottle_blocks) + "\n\n"
        f"Now write the enhanced description in all 5 languages for each of the {count} bottles. "
        "Return ONLY the JSON object with the \"results\" array."
    )
