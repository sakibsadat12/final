"""End-to-end deterministic analysis pipeline.

Order of operations (the LLM, if ever enabled, only rewrites narrative text at
the very end and can never change a scored field):

    classify -> parse amounts -> match transaction -> verdict
             -> severity / routing / review -> deterministic templates
             -> optional LLM rewrite (safe) -> safety post-filter -> validate
"""

from __future__ import annotations

from . import config, policy
from .classifier import classify
from .enums import CaseType
from .matcher import decide_verdict, match
from .normalizers import parse_amounts
from .safety import ensure_safe_internal, ensure_safe_reply
from .schemas import AnalyzeRequest, AnalyzeResponse
from .templates import (
    build_agent_summary,
    build_customer_reply,
    build_next_action,
    reply_language,
)


def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    complaint = req.complaint
    history = req.transaction_history

    # 1. Classification (pure rules).
    case_type, _scores = classify(complaint, req.user_type)

    # 2. Evidence: parse amounts, find the relevant transaction, decide verdict.
    amounts = parse_amounts(complaint)
    relevant_id, relevant_txn, match_kind = match(case_type, amounts, history, complaint)
    verdict = decide_verdict(case_type, relevant_txn, history)

    # 3. Policy: severity, routing, review, confidence, reason codes.
    severity = policy.severity(case_type, verdict, relevant_id)
    department = policy.department(case_type)
    review = policy.human_review_required(case_type, relevant_id)
    conf = policy.confidence(case_type, verdict, match_kind)
    codes = policy.reason_codes(case_type, verdict, match_kind, relevant_id)

    # 4. Deterministic narratives.
    lang = reply_language(req.language, complaint)
    agent_summary = build_agent_summary(case_type, verdict, relevant_txn, req.user_type)
    next_action = build_next_action(case_type, verdict, relevant_txn)
    customer_reply = build_customer_reply(case_type, verdict, relevant_txn, lang)

    # 5. Optional LLM rewrite (off by default; safe fallback always available).
    if config.llm_active():
        from .llm import polish  # imported lazily so the dep is optional

        customer_reply = polish(
            field="customer_reply",
            deterministic=customer_reply,
            case_type=case_type.value,
            language=lang,
        )

    # 6. Safety post-filter (guards LLM output; deterministic text already safe).
    customer_reply = ensure_safe_reply(customer_reply, lang)
    agent_summary = ensure_safe_internal(agent_summary)
    next_action = ensure_safe_internal(next_action)

    # 7. Validated response (extra="forbid" guarantees the exact shape).
    return AnalyzeResponse(
        ticket_id=req.ticket_id,
        relevant_transaction_id=relevant_id,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=review,
        confidence=conf,
        reason_codes=codes,
    )
