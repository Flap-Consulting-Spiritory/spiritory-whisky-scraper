"""Few-shot style examples and prompt builder for description improvement."""

STYLE_EXAMPLES = [
    {
        "name": "Glenfiddich 16 Years Old Aston Martin Formula One 2025",
        "text": (
            "The Glenfiddich 16 Years Old Aston Martin Formula One 2025 is an exclusive "
            "limited edition celebrating the partnership between Glenfiddich and the Aston "
            "Martin F1\u2122 Team. Matured in a unique combination of American Oak Wine Casks, "
            "New American Barrels, and Second-fill Bourbon Casks, this single malt delivers "
            "layered notes of maple syrup, caramelised ginger, fresh fruits, and Chantilly "
            "cream. Bottled at 43% ABV, it impresses with a silky mouthfeel, elegant sweetness, "
            "and an exceptionally smooth finish. A modern Speyside classic that embodies "
            "craftsmanship, innovation, and iconic design."
        ),
    },
    {
        "name": "Ardbeg 15 Years Old Anthology \u2013 The Beithir\u2019s Tale",
        "text": (
            "The Ardbeg 15 Years Old Anthology \u2013 The Beithir\u2019s Tale is the final release "
            "in the acclaimed Anthology series, serving as the grand finale to this remarkable "
            "trilogy. Matured in specially crafted bourbon casks, this 15-year-old Islay single "
            "malt reveals a rich interplay of smoked butter, vanilla, menthol, and pine aromas "
            "\u2013 beautifully balanced with Ardbeg\u2019s signature peaty character. Bottled at 46% "
            "ABV, non-chill filtered and natural in color, it delivers a sweet-complex depth "
            "that captivates both collectors and enthusiasts. Awarded \u2018Gold Outstanding\u2019 "
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
            "classic is both a collector\u2019s treasure and a refined tasting experience."
        ),
    },
    {
        "name": "Macallan The Harmony Collection \u2013 Phoenix Honey Orchid Tea (JING)",
        "text": (
            "The Macallan The Harmony Collection \u2013 Inspired by Phoenix Honey Orchid Tea in "
            "Collaboration with JING is a limited release available from August 5, 2025, in "
            "selected markets. Matured predominantly in American oak sherry casks, complemented "
            "by European oak sherry casks and ex-bourbon barrels, this single malt delivers a "
            "harmonious flavor profile inspired by the exquisite Phoenix Honey Orchid Oolong "
            "tea from the Phoenix Mountains in Guangdong, China. Bottled at 43.9% ABV, it "
            "offers warm honey notes alongside ripe peach, apricot, tropical fruit, and "
            "delicate toffee. A beautifully crafted whisky that unites tea culture with "
            "Macallan\u2019s signature craftsmanship."
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
        parts.append(f"Example {i} \u2014 {ex['name']}:\n\"{ex['text']}\"")
    return "\n\n".join(parts)


def _format_metadata(metadata: dict) -> str:
    lines = []
    field_map = {
        "name": "Name",
        "productAge": "Age (years)",
        "volumeInPercent": "ABV (%)",
        "category": "Category",
        "subCategory": "Sub-category",
        "brand": "Brand",
        "bottlerName": "Bottler",
        "bottelingSerie": "Bottling series",
        "distilledYear": "Distilled year",
        "yearBottled": "Year bottled",
        "bottleSizeInMl": "Bottle size (ml)",
        "numberOfBottles": "Number of bottles",
        "batchNumber": "Batch number",
    }
    for key, label in field_map.items():
        val = metadata.get(key)
        if val is not None and str(val).strip():
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "- No additional metadata available"


def build_improvement_prompt(
    bottle_name: str, current_desc_en: str, metadata: dict
) -> str:
    """Build the Venice AI prompt for description improvement."""
    examples_block = _format_examples()
    metadata_block = _format_metadata(metadata)

    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to ENHANCE "
        "an existing short product description into a richer, more detailed version.\n\n"
        "RULES:\n"
        "- Write 4\u20136 sentences (80\u2013150 words) per language.\n"
        "- Tone: premium, evocative, trustworthy \u2014 match the style examples below.\n"
        "- Structure: open with product name and what makes it notable, then maturation/"
        "cask details, tasting profile from the original text, close with a value statement.\n"
        "- NEVER invent facts not present in CURRENT DESCRIPTION or BOTTLE METADATA.\n"
        "- Keep brand/product names, numerals, and ABV% exactly as given.\n"
        "- If age, cask type, or ABV are in the metadata, weave them naturally into the text.\n"
        "- Output STRICT JSON only, no markdown fences, no extra text:\n"
        '  {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}\n\n'
        f"STYLE EXAMPLES (match this quality and length):\n{examples_block}\n\n"
        f"BOTTLE METADATA:\n{metadata_block}\n\n"
        f'CURRENT DESCRIPTION (enhance this \u2014 do not discard its content):\n"{current_desc_en}"\n\n'
        "Now write the enhanced description in all 5 languages. Return ONLY the JSON."
    )


def build_batch_improvement_prompt(items: list[dict]) -> str:
    """Build a single Venice AI prompt that improves N bottles in one call.

    items: list of dicts with keys {id, name, current_desc_en, metadata}
    Returns a prompt instructing the model to return strict JSON of shape
    {"results": [{"id": <int>, "improved": {"de":"...","en":"...","es":"...","fr":"...","it":"..."}}, ...]}.

    The few-shot examples block is sent ONCE for all bottles in the batch
    instead of once per bottle, which is the cost saving.
    """
    examples_block = _format_examples()

    bottle_blocks = []
    for idx, item in enumerate(items, 1):
        meta_block = _format_metadata(item.get("metadata", {}))
        current_desc = item.get("current_desc_en", "")
        bottle_blocks.append(
            f"--- BOTTLE {idx} ---\n"
            f"id: {item['id']}\n"
            f"name: {item['name']}\n"
            f"metadata:\n{meta_block}\n"
            f'current_description: "{current_desc}"'
        )
    bottles_section = "\n\n".join(bottle_blocks)

    expected_ids = [item["id"] for item in items]
    expected_count = len(items)

    return (
        "You are a premium whisky copywriter for Spiritory. Your task is to ENHANCE "
        f"{expected_count} existing short product descriptions into richer, more detailed versions.\n\n"
        "RULES (apply to EVERY bottle independently):\n"
        "- Write 4\u20136 sentences (80\u2013150 words) per language.\n"
        "- Tone: premium, evocative, trustworthy \u2014 match the style examples below.\n"
        "- Structure: open with product name and what makes it notable, then maturation/"
        "cask details, tasting profile from the original text, close with a value statement.\n"
        "- NEVER invent facts not present in that bottle's CURRENT DESCRIPTION or METADATA.\n"
        "- Keep brand/product names, numerals, and ABV% exactly as given.\n"
        "- If age, cask type, or ABV are in the metadata, weave them naturally into the text.\n"
        "- Treat each bottle in isolation \u2014 do NOT mix facts between bottles.\n"
        "- You MUST return one result for EVERY input bottle, in the same order.\n"
        "- Output STRICT JSON only, no markdown fences, no extra text. Schema:\n"
        '  {"results": [\n'
        '    {"id": <int>, "improved": {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}},\n'
        "    ...\n"
        "  ]}\n"
        f"- The \"id\" field of each result MUST match exactly one of: {expected_ids}.\n\n"
        f"STYLE EXAMPLES (match this quality and length):\n{examples_block}\n\n"
        f"INPUT BOTTLES ({expected_count} total):\n{bottles_section}\n\n"
        f"Now write the enhanced description in all 5 languages for each of the {expected_count} bottles. "
        "Return ONLY the JSON object with the \"results\" array."
    )
