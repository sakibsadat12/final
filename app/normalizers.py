"""Text and value normalisation helpers.

Pure, deterministic functions. No I/O, no clock access.
"""

from __future__ import annotations

import re

# Bengali (Bangla) digit → ASCII digit translation table.
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Currency cues used to boost amount candidates. Lower-cased; Bangla kept as-is.
_CURRENCY_CUES = ("taka", "tk", "bdt", "৳", "টাকা", "tk.", "taka.")

# Time-token suffixes to exclude (e.g. "2pm", "11 am").
_TIME_SUFFIX = re.compile(r"\s*(am|pm)\b", re.IGNORECASE)


def bengali_to_ascii_digits(text: str) -> str:
    """Convert Bengali numerals to ASCII digits."""
    return text.translate(_BN_DIGITS)


def is_bangla(text: str) -> bool:
    """True if the text contains any character in the Bengali Unicode block."""
    return any("ঀ" <= ch <= "৿" for ch in text)


def normalize_phone(s: str) -> str:
    """Normalise a Bangladeshi phone number to +880XXXXXXXXXX form when possible."""
    digits = re.sub(r"\D", "", s)
    if digits.startswith("880") and len(digits) >= 12:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 11:
        return "+88" + digits
    if len(digits) == 10 and digits.startswith("1"):
        return "+880" + digits
    return "+" + digits if digits else s


def normalize_counterparty(s: str | None) -> str | None:
    """Normalise a counterparty identifier.

    Phone-like values are normalised as phone numbers; merchant/biller/agent IDs
    are upper-cased and stripped so comparisons are case-insensitive.
    """
    if not s:
        return s
    s = s.strip()
    digits = re.sub(r"\D", "", s)
    looks_phone = len(digits) >= 10 and (
        s.startswith("+")
        or digits.startswith("0")
        or digits.startswith("88")
        or digits.startswith("1")
    )
    if looks_phone:
        return normalize_phone(s)
    return s.upper()


def parse_amounts(text: str) -> list[float]:
    """Extract plausible monetary amounts from a complaint.

    Rules:
      * Bengali numerals are converted first.
      * Numbers that are part of an identifier (preceded by '-' or a letter, e.g.
        ``TXN-9101``) are ignored.
      * Phone-like numbers (10+ digits) are ignored.
      * Time tokens (``2pm``, ``11 am``) are ignored.
      * If any candidate sits next to a currency cue, only the cued candidates
        are returned (higher precision); otherwise all plausible candidates are
        returned.
    """
    folded = bengali_to_ascii_digits(text)
    lowered = folded.lower()

    cued: list[float] = []
    plain: list[float] = []

    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", folded):
        start, end = m.start(), m.end()

        # Skip identifiers like TXN-9101 / ABC123 (preceded by '-' or a letter).
        if start > 0:
            prev = folded[start - 1]
            if prev == "-" or prev.isalpha():
                continue

        raw = m.group(0)
        digits_only = re.sub(r"\D", "", raw)
        if len(digits_only) >= 10:  # phone-like
            continue

        # Skip time tokens like "2pm".
        if _TIME_SUFFIX.match(folded[end:end + 4]):
            continue

        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if val <= 0:
            continue

        window = lowered[max(0, start - 14):min(len(lowered), end + 14)]
        if any(cue in window for cue in _CURRENCY_CUES):
            cued.append(val)
        else:
            plain.append(val)

    chosen = cued if cued else plain
    # Preserve order, drop duplicates.
    seen: set[float] = set()
    out: list[float] = []
    for v in chosen:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
