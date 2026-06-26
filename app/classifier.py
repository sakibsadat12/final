"""Deterministic case classification.

Weighted keyword rules across English, Bangla script, and Banglish. English
patterns are applied to every complaint because Banglish frequently mixes English
words. Ties are broken by a fixed priority order so behaviour is fully
deterministic.

The LLM (when enabled) NEVER influences case_type — classification is pure code.
"""

from __future__ import annotations

from .enums import CaseType, UserType
from .normalizers import bengali_to_ascii_digits

# Priority order (index 0 = highest). Used to break score ties and to express the
# documented precedence: credential/scam > duplicate > agent cash-in >
# merchant settlement > payment failed > wrong transfer > refund > other.
_PRIORITY: list[CaseType] = [
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING,
    CaseType.DUPLICATE_PAYMENT,
    CaseType.AGENT_CASH_IN_ISSUE,
    CaseType.MERCHANT_SETTLEMENT_DELAY,
    CaseType.PAYMENT_FAILED,
    CaseType.WRONG_TRANSFER,
    CaseType.REFUND_REQUEST,
    CaseType.OTHER,
]
_PRIORITY_INDEX = {c: i for i, c in enumerate(_PRIORITY)}

# (keyword, weight) lists. Keywords are matched as substrings against a folded,
# lower-cased complaint. Bangla keywords are matched against the same string
# (Bengali characters survive lower-casing).
_PHISHING = [
    ("otp", 5.0), ("one time password", 5.0), ("one-time password", 5.0),
    ("verification code", 4.0), ("cvv", 4.0), ("social engineering", 5.0),
    ("phishing", 5.0), ("scam", 3.0), ("fraud call", 3.0), ("claiming to be", 3.0),
    ("pretending to be", 3.0), ("impersonat", 3.0), ("asked for my pin", 4.0),
    ("asked for my otp", 5.0), ("share my otp", 4.0), ("share my pin", 4.0),
    ("account will be blocked", 3.0), ("blocked if i don", 3.0),
    ("ওটিপি", 5.0), ("পিন চাইছে", 4.0), ("পাসওয়ার্ড চাইছে", 4.0),
    ("প্রতারণা", 4.0), ("স্ক্যাম", 4.0), ("ভেরিফিকেশন কোড", 4.0),
]
_DUPLICATE = [
    ("twice", 4.0), ("two times", 4.0), ("double charge", 4.0), ("double charged", 4.0),
    ("double payment", 4.0), ("duplicate", 5.0), ("deducted twice", 5.0),
    ("charged twice", 5.0), ("paid twice", 5.0), ("two payments", 3.0),
    ("দুইবার", 5.0), ("দুবার", 5.0), ("ডাবল", 4.0), ("দুই বার", 5.0),
]
_AGENT_CASH_IN = [
    ("cash in", 3.0), ("cash-in", 3.0), ("cashin", 3.0), ("cash_in", 3.0),
    ("ক্যাশ ইন", 3.0), ("ক্যাশইন", 3.0), ("ক্যাশ-ইন", 3.0),
]
_AGENT_TOKENS = [("agent", 2.5), ("এজেন্ট", 3.0)]
_MERCHANT_SETTLEMENT = [
    ("settlement", 4.0), ("settled", 4.0), ("not been settled", 5.0),
    ("settle to", 3.0), ("settlement delay", 5.0), ("settlement is delayed", 5.0),
    ("সেটেলমেন্ট", 5.0), ("সেটেল", 4.0),
]
_PAYMENT_FAILED = [
    ("failed", 4.0), ("payment failed", 5.0), ("transaction failed", 5.0),
    ("showed failed", 5.0), ("did not go through", 4.0), ("didn't go through", 4.0),
    ("unsuccessful", 3.0), ("balance was deducted", 2.5), ("balance deducted", 2.5),
    ("money was deducted", 2.0), ("deducted but", 2.5),
    ("ব্যর্থ", 4.0), ("ফেইল", 4.0), ("ফেল হয়েছে", 4.0),
]
_WRONG_TRANSFER = [
    ("wrong number", 5.0), ("wrong person", 5.0), ("wrong recipient", 5.0),
    ("wrong account", 4.0), ("wrong transfer", 5.0), ("wrong transaction", 4.0),
    ("wrong mobile", 4.0), ("sent to wrong", 5.0), ("sent to the wrong", 5.0),
    ("mistakenly sent", 4.0), ("by mistake", 3.0), ("typed it wrong", 4.0),
    ("typed the wrong", 4.0), ("didn't get it", 3.0), ("did not get it", 3.0),
    ("didn't receive", 3.0), ("did not receive", 3.0), ("hasn't received", 3.0),
    ("has not received", 3.0), ("not received", 2.5), ("never received", 3.0),
    ("ভুল নম্বর", 5.0), ("ভুল মানুষ", 5.0), ("ভুল ব্যক্তি", 5.0),
    ("ভুল করে পাঠিয়েছি", 5.0), ("ভুলে পাঠিয়েছি", 5.0),
]
_REFUND = [
    ("refund", 2.0), ("money back", 1.5), ("change my mind", 3.0),
    ("changed my mind", 3.0), ("don't want it", 2.5), ("do not want it", 2.5),
    ("cancel the order", 2.5), ("want a refund", 2.5), ("return my money", 1.5),
    ("রিফান্ড", 3.0), ("টাকা ফেরত", 2.5), ("ফেরত চাই", 3.0),
]


def _score(text: str, keywords: list[tuple[str, float]]) -> float:
    return sum(w for kw, w in keywords if kw in text)


def classify(complaint: str, user_type: UserType | None = None) -> tuple[CaseType, dict[str, float]]:
    """Return the most likely case type and the per-category score map."""
    text = bengali_to_ascii_digits(complaint).lower()

    scores: dict[CaseType, float] = {c: 0.0 for c in CaseType}
    scores[CaseType.PHISHING_OR_SOCIAL_ENGINEERING] = _score(text, _PHISHING)
    scores[CaseType.DUPLICATE_PAYMENT] = _score(text, _DUPLICATE)
    scores[CaseType.MERCHANT_SETTLEMENT_DELAY] = _score(text, _MERCHANT_SETTLEMENT)
    scores[CaseType.PAYMENT_FAILED] = _score(text, _PAYMENT_FAILED)
    scores[CaseType.WRONG_TRANSFER] = _score(text, _WRONG_TRANSFER)
    scores[CaseType.REFUND_REQUEST] = _score(text, _REFUND)

    # Agent cash-in requires BOTH an agent token and a cash-in token; either alone
    # is too weak (e.g. an unrelated mention of "agent").
    agent_score = _score(text, _AGENT_TOKENS)
    cashin_score = _score(text, _AGENT_CASH_IN)
    if agent_score > 0 and cashin_score > 0:
        scores[CaseType.AGENT_CASH_IN_ISSUE] = agent_score + cashin_score + 2.0

    # Merchant context boosts settlement when a settlement word is present.
    if scores[CaseType.MERCHANT_SETTLEMENT_DELAY] > 0:
        if user_type == UserType.MERCHANT or "merchant" in text or "i am a merchant" in text:
            scores[CaseType.MERCHANT_SETTLEMENT_DELAY] += 2.0

    best = max(scores.values())
    if best < 1.0:
        return CaseType.OTHER, scores

    # Among the top scorers, pick the highest-priority (lowest index) one.
    winners = [c for c, s in scores.items() if s == best]
    winners.sort(key=lambda c: _PRIORITY_INDEX[c])
    return winners[0], scores
