"""Severity, routing, review, confidence, and reason-code policy. Deterministic."""

from __future__ import annotations

from .enums import CaseType, Department, EvidenceVerdict, Severity

DEPARTMENT: dict[CaseType, Department] = {
    CaseType.WRONG_TRANSFER: Department.DISPUTE_RESOLUTION,
    CaseType.PAYMENT_FAILED: Department.PAYMENTS_OPS,
    CaseType.DUPLICATE_PAYMENT: Department.PAYMENTS_OPS,
    CaseType.REFUND_REQUEST: Department.CUSTOMER_SUPPORT,
    CaseType.MERCHANT_SETTLEMENT_DELAY: Department.MERCHANT_OPERATIONS,
    CaseType.AGENT_CASH_IN_ISSUE: Department.AGENT_OPERATIONS,
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: Department.FRAUD_RISK,
    CaseType.OTHER: Department.CUSTOMER_SUPPORT,
}

_BASE_SEVERITY: dict[CaseType, Severity] = {
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: Severity.CRITICAL,
    CaseType.DUPLICATE_PAYMENT: Severity.HIGH,
    CaseType.PAYMENT_FAILED: Severity.HIGH,
    CaseType.AGENT_CASH_IN_ISSUE: Severity.HIGH,
    CaseType.MERCHANT_SETTLEMENT_DELAY: Severity.MEDIUM,
    CaseType.REFUND_REQUEST: Severity.LOW,
    CaseType.OTHER: Severity.LOW,
}


def department(case_type: CaseType) -> Department:
    return DEPARTMENT[case_type]


def severity(case_type, verdict, relevant_id) -> Severity:
    if case_type == CaseType.WRONG_TRANSFER:
        if relevant_id is not None and verdict == EvidenceVerdict.CONSISTENT:
            return Severity.HIGH
        return Severity.MEDIUM
    return _BASE_SEVERITY[case_type]


def human_review_required(case_type, relevant_id) -> bool:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return True
    if case_type == CaseType.WRONG_TRANSFER:
        return relevant_id is not None
    if case_type in (CaseType.DUPLICATE_PAYMENT, CaseType.AGENT_CASH_IN_ISSUE):
        return True
    return False


def confidence(case_type, verdict, match_kind) -> float:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return 0.95
    if verdict == EvidenceVerdict.INCONSISTENT:
        return 0.7 if match_kind == "single_payment" else 0.75
    if verdict == EvidenceVerdict.INSUFFICIENT_DATA:
        return 0.65 if match_kind == "ambiguous" else 0.6
    if match_kind == "duplicate":
        return 0.93
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return 0.92
    if case_type == CaseType.REFUND_REQUEST:
        return 0.85
    return 0.9


def reason_codes(case_type, verdict, match_kind, relevant_id) -> list[str]:
    codes: list[str] = [case_type.value]
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return codes + ["credential_protection", "critical_escalation"]
    if match_kind == "duplicate":
        codes += ["duplicate_detected", "biller_verification_required"]
    elif match_kind == "single_payment":
        codes += ["single_charge_found", "claim_not_supported"]
    elif match_kind == "ambiguous":
        codes += ["ambiguous_match", "needs_clarification"]
    elif match_kind == "single" and relevant_id is not None:
        codes.append("transaction_match")
    elif match_kind == "none" and verdict == EvidenceVerdict.INSUFFICIENT_DATA:
        codes.append("needs_clarification")
    if verdict == EvidenceVerdict.INCONSISTENT and "single_charge_found" not in codes:
        codes += ["established_recipient_pattern", "evidence_inconsistent"]
    return codes
