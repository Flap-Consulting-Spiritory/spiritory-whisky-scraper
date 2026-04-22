from utils.prompts import (
    build_batch_improvement_prompt,
    build_improvement_prompt,
    build_live_batch_prompt,
    build_live_prompt,
)


def test_live_prompt_includes_name_reviews_and_metadata():
    prompt = build_live_prompt(
        bottle_name="Lagavulin 16",
        reviews_text="Smoky, peaty, seaweed, long finish.",
        metadata={"productAge": 16, "volumeInPercent": 43.0, "brand": "Lagavulin"},
    )
    assert "Lagavulin 16" in prompt
    assert "Smoky, peaty, seaweed, long finish." in prompt
    assert "- Age (years): 16" in prompt
    assert "- ABV (%): 43.0" in prompt
    assert "- Brand: Lagavulin" in prompt
    # Rules carry the correct structural hints
    assert "4–6 sentences" in prompt
    assert "80–150 words" in prompt
    assert "NEVER invent" in prompt
    # 5 languages in the output schema
    assert '"de"' in prompt and '"en"' in prompt
    assert '"es"' in prompt and '"fr"' in prompt and '"it"' in prompt


def test_live_prompt_with_empty_metadata_still_valid():
    prompt = build_live_prompt("X", "Rich vanilla.", {})
    assert "No additional metadata available" in prompt
    assert "Rich vanilla." in prompt


def test_live_batch_prompt_enumerates_ids_and_blocks():
    items = [
        {"id": 101, "name": "A", "reviews_text": "ra", "metadata": {"productAge": 10}},
        {"id": 202, "name": "B", "reviews_text": "rb", "metadata": {"brand": "Macallan"}},
    ]
    prompt = build_live_batch_prompt(items)
    assert "[101, 202]" in prompt
    assert "BOTTLE 1" in prompt and "BOTTLE 2" in prompt
    assert "id: 101" in prompt and "id: 202" in prompt
    assert '"results"' in prompt
    # Per-bottle content flows through
    assert "- Age (years): 10" in prompt
    assert "- Brand: Macallan" in prompt


def test_improvement_prompt_includes_current_description():
    prompt = build_improvement_prompt(
        bottle_name="X",
        current_desc_en="A simple short description.",
        metadata={"productAge": 12},
    )
    assert "A simple short description." in prompt
    assert "- Age (years): 12" in prompt
    assert "ENHANCE" in prompt


def test_batch_improvement_prompt_schema():
    items = [
        {"id": 1, "name": "A", "current_desc_en": "ca", "metadata": {}},
        {"id": 2, "name": "B", "current_desc_en": "cb", "metadata": {}},
    ]
    prompt = build_batch_improvement_prompt(items)
    assert "[1, 2]" in prompt
    assert '"results"' in prompt
    assert "current_description" in prompt


def test_correccion_shim_still_exports_builders():
    """correccion/prompt_templates.py must remain import-compatible."""
    from correccion.prompt_templates import (  # noqa: F401
        STYLE_EXAMPLES,
        build_batch_improvement_prompt,
        build_improvement_prompt,
    )
    assert len(STYLE_EXAMPLES) >= 3
