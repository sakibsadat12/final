"""Pydantic v2 request/response models.

Input is lenient to unknown top-level fields (robustness) but strict on declared
enums (so invalid enum values return 422 per the contract). Output is strict
(extra="forbid") so the response shape can never drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    CaseType,
    Channel,
    Department,
    EvidenceVerdict,
    Language,
    Severity,
    TransactionStatus,
    TransactionType,
    UserType,
)


class Transaction(BaseModel):
    # Ignore unknown per-transaction fields; validate declared enums strictly.
    model_config = ConfigDict(extra="ignore")

    transaction_id: str
    timestamp: str | None = None
    type: TransactionType
    amount: float = Field(allow_inf_nan=False)
    counterparty: str | None = None
    status: TransactionStatus

    @field_validator("transaction_id")
    @classmethod
    def _non_empty_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("transaction_id must not be empty")
        return v


class AnalyzeRequest(BaseModel):
    # Lenient to unknown top-level fields so a slightly richer payload is not
    # rejected; declared enum fields are still validated strictly.
    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    complaint: str
    language: Language | None = None
    channel: Channel | None = None
    user_type: UserType | None = None
    campaign_context: str | None = None
    transaction_history: list[Transaction] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @field_validator("ticket_id")
    @classmethod
    def _ticket_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("ticket_id must not be empty")
        return v

    @field_validator("complaint")
    @classmethod
    def _complaint_non_empty(cls, v: str) -> str:
        if v is None or not v.strip():
            raise ValueError("complaint must not be empty")
        return v


class AnalyzeResponse(BaseModel):
    # Strict output: the response contract may never gain or lose a field.
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    relevant_transaction_id: str | None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: float
    reason_codes: list[str]


class HealthResponse(BaseModel):
    status: str = "ok"
