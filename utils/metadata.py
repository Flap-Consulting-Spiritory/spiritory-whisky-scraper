"""Strapi bottle-metadata extraction + formatting.

Shared by the live scraper (`scraper_engine.py`) and the correction batch
(`correccion/improve_descriptions.py`). Keeping this as a dedicated module
lets the prompt builders focus on prompt wording.
"""

from typing import Any

STRAPI_METADATA_FIELDS: tuple[str, ...] = (
    "name",
    "productAge",
    "volumeInPercent",
    "category",
    "subCategory",
    "brand",
    "bottlerName",
    "bottelingSerie",
    "distilledYear",
    "yearBottled",
    "bottleSizeInMl",
    "numberOfBottles",
    "batchNumber",
)

_METADATA_LABELS: dict[str, str] = {
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


def extract_metadata(bottle: dict) -> dict:
    """Pull the metadata fields Venice uses from a raw Strapi bottle record.

    Normalizes two common quirks:
      * ABV stored as per-ten (470 -> 47.0%).
      * -1 sentinel values on productAge / numberOfBottles -> dropped.

    Safe to call on partial records — missing keys are skipped.
    """
    meta: dict[str, Any] = {
        k: bottle.get(k) for k in STRAPI_METADATA_FIELDS if bottle.get(k) is not None
    }

    abv = meta.get("volumeInPercent")
    if isinstance(abv, (int, float)) and abv > 100:
        meta["volumeInPercent"] = round(abv / 10, 1)

    for key in ("productAge", "numberOfBottles"):
        val = meta.get(key)
        if isinstance(val, (int, float)) and val < 0:
            del meta[key]

    return meta


def format_metadata_block(metadata: dict) -> str:
    """Render metadata as a bullet list for inclusion in Venice prompts."""
    lines = []
    for key, label in _METADATA_LABELS.items():
        val = metadata.get(key)
        if val is not None and str(val).strip():
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "- No additional metadata available"
