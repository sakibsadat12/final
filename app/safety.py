"""Safety post-filter.

Guards every customer-facing and agent-facing string against:
  * requests for credentials (PIN/OTP/password/card) — but NOT safe warnings
    such as "do not share your PIN";
  * refund/reversal/unblock promises the service has no authority to make;
  * third-party phone numbers / "contact this number" instructions;
  * prompt-injection text echoed from the complaint.

If a string is unsafe it is replaced with a minimal safe fallback. Because the
deterministic templates are already safe, this layer is primarily a guard for the
optional LLM path.
"""

from __future__ import annotations

import re

_NEGATIONS = ("do not", "don't", "never", "n't", "no need", "without sharing", "not share")

# Verb + credential request (unsafe only when NOT negated).
_CRED_REQUEST = re.compile(
    r"\b(share|send|provide|give|enter|type|tell|submit|confirm)\b[^.?!]{0,30}?"
    r"\b(pin|otp|password|cvv|card number|verification code|one[- ]time password)\b",
    re.IGNORECASE,
)

# Unauthorised refund/reversal/unblock promises. Carefully avoids the SAFE phrase
# "returned through official channels".
_REFUND_PROMISE = re.compile(
    r"\b("
    r"we will refund|i will refund|we have refunded|refund (has been|is) (approved|processed|completed)|"
    r"refund approved|we will reverse|we have reversed|we will unblock|we will recover|"
    r"will be refunded to you|your money will be refunded|money has been refunded|"
    r"guaranteed refund|refund is confirmed"
    r")\b",
    re.IGNORECASE,
)

# A phone-like number appearing in customer-facing text (we never direct customers
# to a number).
_PHONE_IN_TEXT = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

# Prompt-injection echoes.
_INJECTION = re.compile(
    r"\b(ignore (the )?(previous|above)|disregard (the )?(previous|above)|"
    r"as an ai|system prompt|you are now)\b",
    re.IGNORECASE,
)


def _has_unnegated_cred_request(text: str) -> bool:
    for m in re.finditer(_CRED_REQUEST, text):
        prefix = text[max(0, m.start() - 24):m.start()].lower()
        if not any(neg in prefix for neg in _NEGATIONS):
            return True
    return False


def is_safe(text: str, *, customer_facing: bool = True) -> bool:
    if not text:
        return True
    if _has_unnegated_cred_request(text):
        return False
    if _REFUND_PROMISE.search(text):
        return False
    if _INJECTION.search(text):
        return False
    if customer_facing and _PHONE_IN_TEXT.search(text):
        return False
    return True


_FALLBACK_EN = (
    "Thank you for reaching out. Our team will review your case and contact you through official "
    "support channels. Please do not share your PIN or OTP with anyone."
)
_FALLBACK_BN = (
    "যোগাযোগ করার জন্য ধন্যবাদ। আমাদের টিম আপনার বিষয়টি পর্যালোচনা করে অফিসিয়াল চ্যানেলে আপনার সাথে "
    "যোগাযোগ করবে। অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
)


def ensure_safe_reply(text: str, lang: str) -> str:
    """Return ``text`` if safe, else a minimal safe fallback in the right language."""
    if is_safe(text, customer_facing=True):
        return text
    return _FALLBACK_BN if lang == "bn" else _FALLBACK_EN


def ensure_safe_internal(text: str) -> str:
    """Sanitise agent-facing text (agent_summary / recommended_next_action).

    Neutralises injected credential requests, refund promises, third-party phone
    numbers, and injected instructions that may have arrived via transaction_id /
    counterparty fields. Per safety rule 4, ALL output fields must stay clean.
    """
    if _has_unnegated_cred_request(text) or _REFUND_PROMISE.search(text) \
            or _INJECTION.search(text) or _PHONE_IN_TEXT.search(text):
        cleaned = _REFUND_PROMISE.sub("the case will be reviewed", text)
        cleaned = _CRED_REQUEST.sub("the reported transaction", cleaned)
        cleaned = _INJECTION.sub("", cleaned)
        cleaned = _PHONE_IN_TEXT.sub("[redacted]", cleaned)
        return cleaned.strip() or "Review the case per standard policy."
    return text
