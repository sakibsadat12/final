"""Deterministic, evidence-aware case classification.

Two layers, both pure code (the LLM never influences case_type):

1. Weighted keyword rules across English, Bangla script, and Banglish (romanized
   Bangla). Ties are broken by a fixed priority order.
2. Evidence fallback: when the text alone is inconclusive ("other"), the
   transaction history is consulted — a pending settlement, a pending agent
   cash-in, a failed payment, or a duplicate pair lets the investigator infer the
   case the way a human agent would. A genuinely vague complaint with an
   unremarkable history stays "other".

A final evidence-correction step fixes the common Bangla/English collision where a
"want my money back" phrase on a wrong-transfer or failed-payment ticket would
otherwise be miscoded as a merchant refund_request.
"""

from __future__ import annotations

from .enums import CaseType, TransactionStatus, TransactionType, UserType
from .normalizers import bengali_to_ascii_digits

# Priority order (index 0 = highest). Breaks score ties and expresses precedence:
# credential/scam > duplicate > agent cash-in > merchant settlement >
# payment failed > wrong transfer > refund > other.
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

# ── Phishing / social-engineering detection ──────────────────────────────────
_CRED_WORDS = (
    "otp", "o.t.p", "one time password", "one-time password", "pin", "pin number",
    "pin code", "password", "secret code", "secret pin", "secret number",
    "verification code", "verification number", "security code", "cvv",
    "card number", "ওটিপি", "পিন", "পাসওয়ার্ড", "গোপন", "ভেরিফিকেশন কোড",
    "সিকিউরিটি কোড", "গোপন কোড", "গোপন পিন",
)
_SOLICIT_WORDS = (
    "ask", "asked", "asking", "want", "wants", "wanted", "wanna", "need", "needs",
    "needed", "demand", "demanded", "share", "sharing", "send", "sending", "give",
    "given", "giving", "gave", "provide", "tell", "told", "enter", "read", "type",
    "want to know", "wants to know", "jante", "jante", "chaiche", "chailo",
    "cheyeche", "chay", "জানতে", "চাইছে", "চাইল", "চেয়েছে", "দিতে", "শেয়ার",
    "বলছে", "চায়", "চাইতেছে",
)
_THIRD_PARTY_WORDS = (
    "someone", "somebody", "a man", "a person", "a guy", "a caller", "caller",
    "stranger", "unknown", "they ", "them ", "he ", "she ", "call", "called",
    "calling", "phone", "phoned", "message", "messaged", "sms", "text me",
    "texted", "email", "claiming", "pretending", "from bkash", "from bank",
    "from the bank", "from the company", "কেউ", "একজন", "ফোন", "কল", "লোক",
    "মেসেজ", "এসএমএস", "অপরিচিত",
)
_SCAM_WORDS = (
    "scam", "fraud", "phishing", "fake", "suspicious", "hacker", "hacked",
    "social engineering", "fishing", "prtarona", "protarona", "protarok",
    "প্রতারণা", "স্ক্যাম", "ভুয়া", "প্রতারক", "হ্যাক", "জালিয়াতি",
)
_SOCIAL_ENG_PHRASES = (
    "will be blocked", "account will be blocked", "blocked if", "unlock", "unblock",
    "verify your account", "to verify", "or your account", "lose your money",
    "ব্লক", "অ্যাকাউন্ট বন্ধ", "যাচাই",
)


def _any(text: str, words) -> bool:
    return any(w in text for w in words)


def _phishing_score(text: str) -> float:
    cred = _any(text, _CRED_WORDS)
    solicit = _any(text, _SOLICIT_WORDS)
    third = _any(text, _THIRD_PARTY_WORDS)
    scam = _any(text, _SCAM_WORDS)
    social = _any(text, _SOCIAL_ENG_PHRASES)
    otp = ("otp" in text) or ("ওটিপি" in text) or ("one time password" in text)

    score = 0.0
    # Someone soliciting a credential is the strongest signal.
    if cred and solicit and (third or scam or social):
        score = 7.0
    elif cred and (third or scam) and (solicit or social):
        score = 6.0
    elif otp and (third or solicit or scam):
        score = 5.0
    elif scam and (third or "account" in text or "money" in text or "wallet" in text):
        score = 4.0
    elif cred and social and third:
        score = 5.0
    # OTP mentioned alongside any external-contact context is almost always phishing.
    if otp and third:
        score = max(score, 5.0)
    return score


# ── Keyword tables (substring match against a folded, lower-cased complaint) ──
_DUPLICATE = [
    ("twice", 4.0), ("two times", 4.0), ("2 times", 4.0), ("double charge", 4.5),
    ("double charged", 4.5), ("double payment", 4.5), ("doubly", 3.0),
    ("duplicate", 5.0), ("deducted twice", 5.0), ("charged twice", 5.0),
    ("charged me twice", 5.0), ("paid twice", 5.0), ("two payments", 3.5),
    ("two separate", 4.0), ("two identical", 4.0), ("second charge", 4.0),
    ("second time", 3.0), ("extra charge", 3.5), ("charged again", 4.0),
    ("deducted again", 4.0), ("three times", 4.0), ("four times", 4.0),
    ("multiple times", 4.0), ("several times", 4.0), ("thrice", 4.0),
    ("more than once", 4.0), ("repeated", 3.0), ("repeatedly", 3.0),
    ("দুইবার", 5.0), ("দুবার", 5.0), ("দুই বার", 5.0), ("ডাবল", 4.0),
    ("একাধিকবার", 4.0), ("তিনবার", 4.0), ("দ্বিতীয়বার", 4.0),
    ("duibar", 5.0), ("dui bar", 5.0), ("dui ba", 4.0), ("barbar", 3.5),
]
_AGENT_CASH_IN_TOKENS = [
    ("cash in", 3.0), ("cash-in", 3.0), ("cashin", 3.0), ("cash_in", 3.0),
    ("top up", 2.5), ("topup", 2.5), ("top-up", 2.5), ("topped up", 2.5),
    ("deposited cash", 3.0), ("gave cash", 2.5), ("cash deposit", 3.0),
    ("load money", 2.0), ("deposit", 2.0),
    ("ক্যাশ ইন", 3.0), ("ক্যাশইন", 3.0), ("ক্যাশ-ইন", 3.0), ("নগদ জমা", 3.0),
    ("টাকা জমা", 2.5), ("নগদ দিয়েছি", 2.5),
]
_AGENT_TOKENS = [("agent", 2.5), ("এজেন্ট", 3.0), ("agent er", 2.5), ("agent ke", 2.5)]
_MERCHANT_SETTLEMENT = [
    ("settlement", 4.0), ("settled", 4.0), ("settle", 3.0), ("not been settled", 5.0),
    ("settlement delay", 5.0), ("settlement is delayed", 5.0), ("paid out", 3.5),
    ("payout", 4.0), ("pay out", 3.5), ("disbursement", 4.0), ("disbursed", 4.0),
    ("not credited", 3.0), ("not been paid", 3.0), ("haven't been paid", 3.0),
    ("takings", 3.0), ("সেটেলমেন্ট", 5.0), ("সেটেল", 4.0), ("বিক্রির টাকা", 3.0),
]
_MERCHANT_CONTEXT = ("merchant", "shop", "store", "business", "seller", "my sales",
                     "i run a", "দোকান", "মার্চেন্ট", "ব্যবসা", "bikri", "dokan")
_PAYMENT_FAILED = [
    ("failed", 4.0), ("payment failed", 5.0), ("transaction failed", 5.0),
    ("showed failed", 5.0), ("did not go through", 4.0), ("didn't go through", 4.0),
    ("did not complete", 4.0), ("didn't complete", 4.0), ("incomplete", 2.5),
    ("unsuccessful", 3.5), ("declined", 3.5), ("payment error", 3.5),
    ("transaction error", 3.5), ("app error", 2.5), ("got an error", 3.0),
    ("gave an error", 3.0), ("balance was deducted", 2.5), ("balance deducted", 2.5),
    ("money was deducted", 2.0), ("money is gone", 3.0), ("money gone", 3.0),
    ("deducted but", 2.5), ("charged but", 2.5), ("cut from my balance", 2.5),
    ("ব্যর্থ", 4.0), ("ফেইল", 4.0), ("ফেল হয়েছে", 4.0), ("ফেল", 3.0),
    ("কেটে গেছে", 2.5), ("কেটে নিয়েছে", 2.5), ("টাকা কাটা", 2.5), ("সম্পন্ন হয়নি", 3.5),
    ("fail dekha", 4.0), ("fail hoye", 4.0), ("kete geche", 2.5), ("kete niyeche", 2.5),
    ("kete nilo", 2.5), ("taka kete", 2.5),
]
_WRONG_TRANSFER = [
    ("wrong number", 6.0), ("wrong person", 6.0), ("wrong recipient", 6.0),
    ("wrong account", 5.0), ("wrong transfer", 6.0), ("wrong transaction", 4.5),
    ("wrong mobile", 5.0), ("wrong guy", 4.5), ("wrong man", 4.5),
    ("sent to wrong", 5.5), ("sent to the wrong", 5.5), ("sent to a stranger", 4.5),
    ("sent to a wrong", 5.5), ("mistakenly sent", 4.5), ("accidentally sent", 4.5),
    ("by mistake", 3.0), ("by accident", 3.0), ("typed it wrong", 4.0),
    ("typed the wrong", 4.0), ("fat-fingered", 4.0), ("one digit off", 4.0),
    ("keyed the wrong", 4.0), ("meant for", 2.5), ("instead of", 2.5),
    ("didn't reach", 3.0), ("did not reach", 3.0), ("hasn't reached", 3.0),
    ("never reached", 3.0), ("didn't get it", 3.0), ("did not get it", 3.0),
    ("didn't receive", 3.0), ("did not receive", 3.0), ("hasn't received", 3.0),
    ("not received", 2.5), ("never received", 3.0),
    ("ভুল নম্বর", 6.0), ("ভুল মানুষ", 6.0), ("ভুল ব্যক্তি", 6.0), ("ভুল জায়গায়", 5.0),
    ("ভুল করে পাঠিয়েছি", 5.0), ("ভুলে পাঠিয়েছি", 5.0), ("অন্য নম্বরে", 4.0),
    ("bhul number", 6.0), ("vul number", 6.0), ("bhul manush", 5.0),
    ("bhul kore", 4.0), ("vul kore", 4.0), ("onno number", 4.0),
]
_REFUND = [
    ("refund", 1.5), ("money back", 1.0), ("get my money back", 1.0),
    ("change my mind", 3.0), ("changed my mind", 3.0), ("don't want it", 2.5),
    ("do not want it", 2.5), ("no longer want", 2.5), ("cancel the order", 2.5),
    ("cancel my order", 2.5), ("return the product", 2.5), ("returned the item", 2.5),
    ("want a refund", 2.5), ("would like a refund", 2.5), ("not satisfied", 2.0),
    ("রিফান্ড", 2.5), ("ফেরত চাই", 1.5), ("টাকা ফেরত", 1.0), ("ফেরত দিন", 1.5),
    ("বাতিল", 2.0), ("ferot chai", 1.5), ("taka ferot", 1.0), ("refund chai", 2.0),
]

_SEND_HINTS = ("sent", "send", "sending", "transfer", "transferred", "pathai",
               "pathai", "pathiye", "পাঠি", "পাঠা", "ট্রান্সফার")
_MONEY_CONTEXT = ("money", "taka", "tk", "bdt", "payment", "paid", "pay", "charge",
                  "charged", "deduct", "balance", "transfer", "transaction", "sent",
                  "settle", "refund", "cash", "bill", "recharge", "৳", "টাকা",
                  "পেমেন্ট", "ব্যালেন্স", "লেনদেন", "বিল", "টাকা")


def _score(text: str, keywords: list[tuple[str, float]]) -> float:
    return sum(w for kw, w in keywords if kw in text)


def _has(history, type_=None, status=None) -> bool:
    for t in history:
        if type_ is not None and t.type != type_:
            continue
        if status is not None and t.status != status:
            continue
        return True
    return False


def _has_duplicate_pattern(history) -> bool:
    from .normalizers import normalize_counterparty
    groups: dict[tuple, int] = {}
    for t in history:
        if t.type != TransactionType.PAYMENT:
            continue
        if t.status not in (TransactionStatus.COMPLETED, TransactionStatus.PENDING):
            continue
        key = (t.amount, normalize_counterparty(t.counterparty))
        groups[key] = groups.get(key, 0) + 1
    return any(c >= 2 for c in groups.values())


def _infer_from_history(text: str, history, user_type) -> CaseType | None:
    """Infer a case type from transaction evidence when the text is inconclusive.

    Only fires when there is money context; a vague complaint over an unremarkable
    (all-completed, no-duplicate) history stays None → 'other'.
    """
    if not history or not _any(text, _MONEY_CONTEXT):
        return None
    if _has(history, TransactionType.SETTLEMENT, TransactionStatus.PENDING):
        return CaseType.MERCHANT_SETTLEMENT_DELAY
    if _has(history, TransactionType.CASH_IN, TransactionStatus.PENDING):
        return CaseType.AGENT_CASH_IN_ISSUE
    if _has(history, TransactionType.PAYMENT, TransactionStatus.FAILED):
        return CaseType.PAYMENT_FAILED
    if _has_duplicate_pattern(history):
        return CaseType.DUPLICATE_PAYMENT
    if _any(text, _SEND_HINTS) and _has(history, TransactionType.TRANSFER, TransactionStatus.COMPLETED):
        return CaseType.WRONG_TRANSFER
    return None


def classify(complaint: str, user_type: UserType | None = None, history=None) -> tuple[CaseType, dict[str, float]]:
    """Return the most likely case type and the per-category score map."""
    history = history or []
    text = bengali_to_ascii_digits(complaint).lower()

    scores: dict[CaseType, float] = {c: 0.0 for c in CaseType}
    scores[CaseType.PHISHING_OR_SOCIAL_ENGINEERING] = _phishing_score(text)
    scores[CaseType.DUPLICATE_PAYMENT] = _score(text, _DUPLICATE)
    scores[CaseType.PAYMENT_FAILED] = _score(text, _PAYMENT_FAILED)
    scores[CaseType.WRONG_TRANSFER] = _score(text, _WRONG_TRANSFER)
    scores[CaseType.REFUND_REQUEST] = _score(text, _REFUND)

    # Merchant settlement only counts with merchant context present.
    settlement = _score(text, _MERCHANT_SETTLEMENT)
    if settlement > 0 and (user_type == UserType.MERCHANT or _any(text, _MERCHANT_CONTEXT)):
        scores[CaseType.MERCHANT_SETTLEMENT_DELAY] = settlement + 1.0

    # Agent cash-in requires BOTH an agent token and a cash-in/deposit token.
    agent_score = _score(text, _AGENT_TOKENS)
    cashin_score = _score(text, _AGENT_CASH_IN_TOKENS)
    if agent_score > 0 and cashin_score > 0:
        scores[CaseType.AGENT_CASH_IN_ISSUE] = agent_score + cashin_score + 2.0

    best = max(scores.values())
    if best < 1.0:
        # Text inconclusive → consult the transaction evidence.
        inferred = _infer_from_history(text, history, user_type)
        case_type = inferred if inferred is not None else CaseType.OTHER
    else:
        winners = [c for c, s in scores.items() if s == best]
        winners.sort(key=lambda c: _PRIORITY_INDEX[c])
        case_type = winners[0]

    # Evidence correction: a "want my money back" phrase that scored refund_request
    # is really a wrong-transfer recovery (matching transfer) or a failed payment.
    if case_type == CaseType.REFUND_REQUEST:
        if _has(history, TransactionType.PAYMENT, TransactionStatus.FAILED):
            case_type = CaseType.PAYMENT_FAILED
        elif _any(text, _SEND_HINTS) and _has(history, TransactionType.TRANSFER, TransactionStatus.COMPLETED) \
                and not _has(history, TransactionType.PAYMENT, TransactionStatus.COMPLETED):
            case_type = CaseType.WRONG_TRANSFER

    return case_type, scores
