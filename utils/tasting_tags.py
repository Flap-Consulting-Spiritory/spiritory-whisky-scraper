# Exact enum values accepted by Strapi's tasting_note_1 / tasting_note_2 fields.
VALID_TASTING_TAGS = [
    "Apple",
    "Caramel",
    "Chocolate",
    "Citric",
    "Coal-gas",
    "Cooked fruit",
    "Cooked mash",
    "Cooked vegetable",
    "Dried fruit",
    "Fragant",
    "Fresh fruit",
    "Green-House",
    "Hay-like",
    "Honey",
    "Husky",
    "Kippery",
    "Leafy",
    "Leathery",
    "Malt Extract",
    "Medicinal",
    "Mossy",
    "New Wood",
    "Nutty",
    "Oily",
    "Old Wood",
    "Pear",
    "Plastic",
    "Rubbery",
    "Sandy",
    "Sherried",
    "Smokey",
    "Solvent",
    "Sweaty",
    "Toasted",
    "Tobacco",
    "Vanilla",
    "Vegetative",
    "Yeasty",
]

# Pre-build a lowercase → canonical mapping for O(1) case-insensitive lookup
_TAG_MAP: dict[str, str] = {tag.lower(): tag for tag in VALID_TASTING_TAGS}


def normalize_tag(raw: str) -> str | None:
    """Return the canonical Strapi enum value for *raw*, or None if not recognised.

    Matching is case-insensitive and strips leading/trailing whitespace.
    Example: "Dried Fruit" → "Dried fruit", "HONEY" → "Honey"
    """
    return _TAG_MAP.get(raw.strip().lower())
