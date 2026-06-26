"""Evidence-based transaction matching. Never guesses."""

from __future__ import annotations

from datetime import datetime, timedelta

from . import config
from .enums import CaseType, EvidenceVerdict, TransactionStatus, TransactionType
from .normalizers import bengali_to_ascii_digits, extract_phones, normalize_counterparty
from .schemas import Transaction

_CASE_TYPES: dict[CaseType, set[TransactionType]] = {
    CaseType.WRONG_TRANSFER: {TransactionType.TRANSFER},
    CaseType.PAYMENT_FAILED: {TransactionType.PAYMENT},
    CaseType.DUPLICATE_PAYMENT: {TransactionType.PAYMENT},
    CaseType.REFUND_REQUEST: {TransactionType.PAYMENT, TransactionType.REFUND},
    CaseType.MERCHANT_SETTLEMENT_DELAY: {TransactionType.SETTLEMENT},
    CaseType.AGENT_CASH_IN_ISSUE: {TransactionType.CASH_IN},
}
_AMOUNT_TOL = 0.5
_CHARGEABLE = (TransactionStatus.COMPLETED, TransactionStatus.PENDING)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _amount_matches(txn: Transaction, amounts: list[float]) -> bool:
    return any(abs(txn.amount - a) < _AMOUNT_TOL for a in amounts)


def _latest(txns: list[Transaction]) -> Transaction:
    dated = [(t, _parse_ts(t.timestamp)) for t in txns]
    if all(ts is not None for _, ts in dated):
        return max(dated, key=lambda x: x[1])[0]  # type: ignore[arg-type]
    return txns[-1]


def _cited_in_complaint(history: list[Transaction], complaint: str) -> list[Transaction]:
    low = complaint.lower()
    return [t for t in history if t.transaction_id and len(t.transaction_id) >= 3
            and t.transaction_id.lower() in low]


def _match_duplicate(amounts: list[float], history: list[Transaction]):
    base = [t for t in history if _amount_matches(t, amounts)] if amounts else list(history)
    payments = [t for t in base if t.type == TransactionType.PAYMENT]
    chargeable = [t for t in payments if t.status in _CHARGEABLE]
    groups: dict[str | None, list[Transaction]] = {}
    for t in chargeable:
        groups.setdefault(normalize_counterparty(t.counterparty), []).append(t)
    dup = [g for g in groups.values() if len(g) >= 2]
    if dup:
        later = _latest(max(dup, key=len))
        return later.transaction_id, later, "duplicate"
    if len(payments) == 1:
        return payments[0].transaction_id, payments[0], "single_payment"
    if len(chargeable) == 1:
        return chargeable[0].transaction_id, chargeable[0], "single_payment"
    return None, None, "none"


def match(case_type, amounts, history, complaint):
    """Return (relevant_transaction_id, relevant_transaction, match_kind)."""
    if case_type in (CaseType.PHISHING_OR_SOCIAL_ENGINEERING, CaseType.OTHER):
        return None, None, "none"

    # 0. Customer cited an exact transaction id present in history → strongest signal.
    cited = _cited_in_complaint(history, complaint)
    if len(cited) == 1:
        return cited[0].transaction_id, cited[0], "single"

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return _match_duplicate(amounts, history)

    allowed = _CASE_TYPES.get(case_type)
    amount_matches = [t for t in history if _amount_matches(t, amounts)] if amounts else []
    typed = [t for t in amount_matches if allowed and t.type in allowed]
    pool = typed if typed else amount_matches

    # A failed/reversed transfer never delivered money → cannot be the live dispute.
    if case_type == CaseType.WRONG_TRANSFER:
        completed = [t for t in pool if t.status == TransactionStatus.COMPLETED]
        if completed:
            pool = completed

    # Disambiguate by a phone number quoted in the complaint.
    phones = extract_phones(complaint)
    if len(pool) > 1 and phones:
        by_cp = [t for t in pool if normalize_counterparty(t.counterparty) in phones]
        if len(by_cp) == 1:
            pool = by_cp

    if len(pool) == 1:
        return pool[0].transaction_id, pool[0], "single"

    if len(pool) == 0:
        # Unique-typed fallback only when the complaint stated NO amount.
        if not amounts and allowed:
            typed_all = [t for t in history if t.type in allowed
                         and t.status != TransactionStatus.FAILED]
            if len(typed_all) == 1:
                return typed_all[0].transaction_id, typed_all[0], "single"
        return None, None, "none"

    # Multiple matches sharing ONE counterparty → no disambiguation needed; take the
    # most recent (established-recipient logic then flags inconsistency).
    if case_type == CaseType.WRONG_TRANSFER:
        cps = {normalize_counterparty(t.counterparty) for t in pool}
        if len(cps) == 1:
            latest = _latest(pool)
            return latest.transaction_id, latest, "single"

    narrowed = _narrow_by_relative_date(pool, complaint, history)
    if len(narrowed) == 1:
        return narrowed[0].transaction_id, narrowed[0], "single"
    return None, None, "ambiguous"


def _narrow_by_relative_date(pool, complaint, history):
    text = bengali_to_ascii_digits(complaint).lower()
    wants_yesterday = "yesterday" in text or "গতকাল" in complaint or "gotokal" in text
    wants_today = "today" in text or "আজ" in complaint
    if not (wants_yesterday or wants_today):
        return pool
    stamps = [ts for ts in (_parse_ts(t.timestamp) for t in history) if ts is not None]
    if not stamps:
        return pool
    anchor = max(stamps).date()
    target = anchor - timedelta(days=1) if wants_yesterday else anchor
    same = [t for t in pool if (_parse_ts(t.timestamp) and _parse_ts(t.timestamp).date() == target)]
    return same if len(same) == 1 else pool


def is_established_recipient(relevant, history):
    if relevant.counterparty is None:
        return False
    target = normalize_counterparty(relevant.counterparty)
    rel_ts = _parse_ts(relevant.timestamp)
    priors = 0
    for t in history:
        if t.transaction_id == relevant.transaction_id:
            continue
        if t.type != TransactionType.TRANSFER:
            continue
        if t.status != TransactionStatus.COMPLETED:  # only successful priors count
            continue
        if normalize_counterparty(t.counterparty) != target:
            continue
        t_ts = _parse_ts(t.timestamp)
        if rel_ts is not None and t_ts is not None and t_ts >= rel_ts:
            continue
        priors += 1
    return priors >= config.ESTABLISHED_RECIPIENT_MIN_PRIORS


def decide_verdict(case_type, relevant, history, match_kind="single"):
    if relevant is None:
        return EvidenceVerdict.INSUFFICIENT_DATA
    if match_kind == "single_payment":
        # Duplicate claim but only one charge exists → data contradicts the claim.
        return EvidenceVerdict.INCONSISTENT
    if case_type == CaseType.WRONG_TRANSFER and is_established_recipient(relevant, history):
        return EvidenceVerdict.INCONSISTENT
    return EvidenceVerdict.CONSISTENT
