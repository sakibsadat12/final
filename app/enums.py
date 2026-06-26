"""Runtime enums.

Use StrEnum (Python 3.11+) so values both validate in Pydantic and serialise as
plain strings in JSON. Do NOT use typing.Literal as a runtime enum.
"""

from __future__ import annotations

from enum import StrEnum


# ── Input enums ──────────────────────────────────────────────────────────────
class Language(StrEnum):
    EN = "en"
    BN = "bn"
    MIXED = "mixed"


class Channel(StrEnum):
    IN_APP_CHAT = "in_app_chat"
    CALL_CENTER = "call_center"
    EMAIL = "email"
    MERCHANT_PORTAL = "merchant_portal"
    FIELD_AGENT = "field_agent"


class UserType(StrEnum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    AGENT = "agent"
    UNKNOWN = "unknown"


class TransactionType(StrEnum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    SETTLEMENT = "settlement"
    REFUND = "refund"


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    REVERSED = "reversed"


# ── Output enums ─────────────────────────────────────────────────────────────
class EvidenceVerdict(StrEnum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


class CaseType(StrEnum):
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    DUPLICATE_PAYMENT = "duplicate_payment"
    MERCHANT_SETTLEMENT_DELAY = "merchant_settlement_delay"
    AGENT_CASH_IN_ISSUE = "agent_cash_in_issue"
    PHISHING_OR_SOCIAL_ENGINEERING = "phishing_or_social_engineering"
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Department(StrEnum):
    CUSTOMER_SUPPORT = "customer_support"
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENTS_OPS = "payments_ops"
    MERCHANT_OPERATIONS = "merchant_operations"
    AGENT_OPERATIONS = "agent_operations"
    FRAUD_RISK = "fraud_risk"
