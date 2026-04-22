"""Back-compat shim — the prompt builders now live in `utils.prompts`.

Kept so existing imports (`from correccion.prompt_templates import ...`)
in batch_runner.py and any external scripts keep working.
"""

from utils.prompts import (  # noqa: F401 — re-export
    STYLE_EXAMPLES,
    build_batch_improvement_prompt,
    build_improvement_prompt,
    build_live_batch_prompt,
    build_live_prompt,
)
