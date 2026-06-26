"""Optional LLM text-polish layer (OFF by default).

This NEVER decides any scored field. It may only rewrite a narrative string, with
a strict timeout, temperature 0, a key allowlist, a circuit breaker, and a
deterministic fallback on any error. If anything goes wrong the original
deterministic text is returned unchanged.

Enable by setting LLM_ENABLED=true and ANTHROPIC_API_KEY. With the defaults the
service is fully deterministic and this module is never imported.
"""

from __future__ import annotations

import logging

from . import config

logger = logging.getLogger("queuestorm.llm")


class CircuitBreaker:
    """Trip open after repeated failures; auto-reset after a cooldown.

    Time is injected (no clock access at import time / in tests). The gate uses
    the real breaker state, never a hardcoded flag.
    """

    def __init__(self, max_failures: int = 3, cooldown_s: int = 60) -> None:
        self.max_failures = max_failures
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: float | None = None

    def is_open(self, now: float) -> bool:
        if self._opened_at is None:
            return False
        if now - self._opened_at >= self.cooldown_s:
            # Cooldown elapsed -> half-open: allow a trial call.
            self._failures = 0
            self._opened_at = None
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self, now: float) -> None:
        self._failures += 1
        if self._failures >= self.max_failures:
            self._opened_at = now


_breaker = CircuitBreaker()


def polish(field: str, deterministic: str, case_type: str, language: str) -> str:
    """Attempt an LLM rewrite of ``deterministic``. Returns deterministic text on
    any failure, when disabled, or when the breaker is open.

    Only ``customer_reply`` / ``recommended_next_action`` / ``agent_summary`` may
    be rewritten; anything else returns the deterministic text unchanged.
    """
    if field not in {"customer_reply", "recommended_next_action", "agent_summary"}:
        return deterministic
    if not config.llm_active():
        return deterministic

    import time

    now = time.monotonic()
    if _breaker.is_open(now):
        return deterministic

    try:
        import anthropic  # imported lazily; optional dependency

        client = anthropic.Anthropic(api_key=config.LLM_API_KEY)
        system = (
            "You rewrite a customer-service message to be clearer and more empathetic. "
            "Keep the SAME meaning and all transaction IDs. Never promise refunds, reversals, "
            "or unblocks. Never request PIN, OTP, password, or card numbers. Never add phone "
            "numbers. Reply in the same language. Output ONLY the rewritten message."
        )
        msg = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=400,
            temperature=0,
            timeout=config.LLM_TIMEOUT_S,
            system=system,
            messages=[{"role": "user", "content": deterministic}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        text = text.strip()
        if not text:
            raise ValueError("empty LLM response")
        _breaker.record_success()
        return text
    except Exception:  # noqa: BLE001 - any failure falls back deterministically
        _breaker.record_failure(time.monotonic())
        logger.warning("llm_polish_failed field=%s; using deterministic fallback", field)
        return deterministic
