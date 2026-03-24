import openai
import json
import os


def generate_description(reviews_text: str, bottle_name: str) -> dict:
    """
    Given whisky review text, produces a marketing description in 5 languages via Venice AI.
    Returns {"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}
    Returns empty strings for all languages if reviews_text is empty or the API call fails.
    """
    if not reviews_text or not reviews_text.strip():
        return {"de": "", "en": "", "es": "", "fr": "", "it": ""}

    client = openai.OpenAI(
        api_key=os.environ.get("VENICE_ADMIN_KEY", ""),
        base_url="https://api.venice.ai/api/v1",
    )

    prompt = (
        f'You are a premium whisky copywriter. Based on the tasting reviews below, '
        f'write a short, evocative marketing description for the whisky "{bottle_name}" '
        f'(2-3 sentences). Then translate it into German (de), Spanish (es), French (fr), '
        f'and Italian (it).\n\n'
        f'Rules:\n'
        f'- Keep brand/product names, numerals, and ABV % exactly as in the source.\n'
        f'- Tone: premium, concise, inviting.\n'
        f'- Output STRICT JSON only, no markdown fences, no extra text:\n'
        f'{{"de": "...", "en": "...", "es": "...", "fr": "...", "it": "..."}}\n\n'
        f'Reviews:\n{reviews_text}'
    )

    try:
        response = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()

        # Strip possible markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        return {
            "de": parsed.get("de", ""),
            "en": parsed.get("en", ""),
            "es": parsed.get("es", ""),
            "fr": parsed.get("fr", ""),
            "it": parsed.get("it", ""),
        }
    except Exception as e:
        print(f"[Venice AI] Error generating description: {e}")
        return {"de": "", "en": "", "es": "", "fr": "", "it": ""}


def mock_generate_description(reviews_text: str, bottle_name: str) -> dict:
    """Returns a mock 5-language description without calling the API. Used in --mock mode."""
    if not reviews_text or not reviews_text.strip():
        return {"de": "", "en": "", "es": "", "fr": "", "it": ""}
    en = f"{bottle_name} is a remarkable whisky with exceptional character. {reviews_text[:80].strip()}..."
    return {
        "de": f"[DE] {en}",
        "en": en,
        "es": f"[ES] {en}",
        "fr": f"[FR] {en}",
        "it": f"[IT] {en}",
    }
