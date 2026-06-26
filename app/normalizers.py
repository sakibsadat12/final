"""Text and value normalisation helpers.

Pure, deterministic functions. No I/O, no clock access.
"""

from __future__ import annotations

import re

# Bengali (Bangla) digit → ASCII digit translation table.
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Currency cues used to boost amount candidates. Lower-cased; Bangla kept as-is.
_CURRENCY_CUES = ("taka", "tk", "bdt", "৳", "টাকা", "poisa", "poysa")

# Time-token suffixes to exclude (e.g. "2pm", "11 am").
_TIME_SUFFIX = re.compile(r"\s*(am|pm)\b", re.IGNORECASE)

# Magnitude multipliers (English, Banglish, Bangla). Order matters: longer words
# first so "lakh" is tried before "k".
_MULTIPLIERS: list[tuple[str, int]] = [
    ("crore", 10_000_000), ("কোটি", 10_000_000), ("koti", 10_000_000),
    ("lakhs", 100_000), ("lakh", 100_000), ("lac", 100_000), ("লাখ", 100_000),
    ("lakkh", 100_000),
    ("thousand", 1_000), ("hajar", 1_000), ("হাজার", 1_000), ("hazar", 1_000),
    ("k", 1_000),
]
_MULT_RE = re.compile(
    r"\s*(crore|কোটি|koti|lakhs|lakh|lac|লাখ|lakkh|thousand|hajar|হাজার|hazar|k)\b",
    re.IGNORECASE,
)
_MULT_VALUE = {w: v for w, v in _MULTIPLIERS}


def bengali_to_ascii_digits(text: str) -> str:
    """Convert Bengali numerals to ASCII digits."""
    return text.translate(_BN_DIGITS)


def is_bangla(text: str) -> bool:
    """True if the text contains any character in the Bengali Unicode block."""
    return any("ঀ" <= ch <= "৿" for ch in text)


def dominant_script(text: str) -> str:
    """Return 'bn' if Bengali characters outnumber Latin letters, else 'en'."""
    bn = sum(1 for ch in text if "ঀ" <= ch <= "৿")
    latin = sum(1 for ch in text if ("a" <= ch <= "z") or ("A" <= ch <= "Z"))
    return "bn" if bn > latin else "en"


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


def extract_phones(text: str) -> set[str]:
    """Extract normalised phone numbers mentioned in a complaint."""
    folded = bengali_to_ascii_digits(text)
    out: set[str] = set()
    for m in re.finditer(r"\+?8?8?0?1\d[\d\s\-]{7,12}\d|\b01\d{9}\b|\b\d{11}\b", folded):
        token = re.sub(r"\D", "", m.group(0))
        if 10 <= len(token) <= 13:
            out.add(normalize_phone(token))
    return out


def parse_amounts(text: str) -> list[float]:
    """Extract plausible monetary amounts from a complaint.

    Handles magnitude shorthand (5k → 5000, 2 lakh → 200000, ৫ হাজার → 5000),
    decimals, and thousands separators. Numbers that are part of an identifier
    (preceded by '-' or a letter, e.g. ``TXN-9101``), phone-like numbers
    (10+ digits), and time tokens (``2pm``) are ignored.

    Candidates that sit next to a currency cue OR carry a magnitude suffix are
    treated as higher-confidence; if any exist, only those are returned.
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

        # Skip time tokens like "2pm" (but NOT if a magnitude word follows).
        tail = folded[end:end + 10]
        mult_match = _MULT_RE.match(tail)
        if _TIME_SUFFIX.match(folded[end:end + 4]) and not mult_match:
            continue

        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if val <= 0:
            continue

        has_mult = False
        if mult_match:
            val *= _MULT_VALUE[mult_match.group(1).lower()]
            has_mult = True

        window = lowered[max(0, start - 14):min(len(lowered), end + 14)]
        if has_mult or any(cue in window for cue in _CURRENCY_CUES):
            cued.append(val)
        else:
            plain.append(val)

    chosen = cued if cued else plain
    seen: set[float] = set()
    out: list[float] = []
    for v in chosen:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
