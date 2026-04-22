from utils.metadata import extract_metadata, format_metadata_block


def test_extract_metadata_happy_path():
    bottle = {
        "id": 1,
        "name": "Glenfiddich 16 YO",
        "productAge": 16,
        "volumeInPercent": 46.0,
        "category": "Single Malt",
        "brand": "Glenfiddich",
        "documentId": "abc",  # unrelated field, should be ignored
    }
    meta = extract_metadata(bottle)
    assert meta == {
        "name": "Glenfiddich 16 YO",
        "productAge": 16,
        "volumeInPercent": 46.0,
        "category": "Single Malt",
        "brand": "Glenfiddich",
    }
    # documentId must NOT leak into the prompt context
    assert "documentId" not in meta


def test_extract_metadata_normalizes_per_ten_abv():
    # Strapi sometimes stores ABV as integer per-ten (470 = 47.0%)
    meta = extract_metadata({"name": "X", "volumeInPercent": 470})
    assert meta["volumeInPercent"] == 47.0


def test_extract_metadata_drops_sentinel_minus_one():
    meta = extract_metadata({
        "name": "X", "productAge": -1, "numberOfBottles": -1, "volumeInPercent": 40.0,
    })
    assert "productAge" not in meta
    assert "numberOfBottles" not in meta
    assert meta["volumeInPercent"] == 40.0


def test_extract_metadata_keeps_legit_zero_like_values():
    # 0 is NOT -1 and should be kept (e.g. an old bottling pre-date field)
    meta = extract_metadata({"name": "X", "distilledYear": 0})
    assert meta["distilledYear"] == 0


def test_format_metadata_block_renders_bullets():
    block = format_metadata_block({
        "name": "Ardbeg 10",
        "productAge": 10,
        "volumeInPercent": 46.0,
    })
    assert "- Name: Ardbeg 10" in block
    assert "- Age (years): 10" in block
    assert "- ABV (%): 46.0" in block


def test_format_metadata_block_empty_gets_fallback():
    assert "No additional metadata" in format_metadata_block({})
