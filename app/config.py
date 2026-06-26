"""Runtime configuration. All values have safe deterministic defaults.

The service is fully functional with NO environment variables set. LLM usage is
opt-in and OFF by default; the deterministic path is always the source of truth
for the scored fields.
"""

from __future__ import annotations

import os

# Maximum accepted request body size. Spec: payloads over 16 KB return 413.
MAX_BODY_BYTES: int = 16 * 1024

# Optional LLM text-polish layer. Disabled unless explicitly enabled AND a key
# is present. Even when enabled it may only rewrite narrative text, never the
# scored decision fields, and always falls back to deterministic templates.
LLM_ENABLED: bool = os.getenv("LLM_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
LLM_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_TIMEOUT_S: float = float(os.getenv("LLM_TIMEOUT_S", "6"))

# Duplicate-payment detection window (seconds).
DUPLICATE_WINDOW_S: int = int(os.getenv("DUPLICATE_WINDOW_S", "300"))

# How many prior transfers to the same counterparty make a "wrong transfer"
# claim look inconsistent (established-recipient pattern).
ESTABLISHED_RECIPIENT_MIN_PRIORS: int = 2


def llm_active() -> bool:
    """LLM is only active when explicitly enabled and an API key is present."""
    return LLM_ENABLED and bool(LLM_API_KEY)
