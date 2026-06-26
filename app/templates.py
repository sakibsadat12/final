"""Deterministic, safe narrative generation.

`agent_summary` and `recommended_next_action` are always English (internal,
agent-facing). `customer_reply` is localised: Bangla for Bangla complaints,
English/Banglish otherwise.

Templates never promise refunds/reversals/unblocks and never request PIN/OTP.
Raw values are passed in directly; templates own all surrounding phrasing.
"""

from __future__ import annotations

from .enums import CaseType, EvidenceVerdict, Language, UserType
from .normalizers import is_bangla
from .schemas import Transaction

# Standard safety line appended to English replies.
_SAFE_EN = "Please do not share your PIN or OTP with anyone."
# Standard safety line for Bangla replies.
_SAFE_BN = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"


def reply_language(language: Language | None, complaint: str) -> str:
    """Decide the customer_reply language: 'bn' or 'en'."""
    if language == Language.BN:
        return "bn"
    if language in (Language.EN, Language.MIXED):
        return "en"
    return "bn" if is_bangla(complaint) else "en"


def _amt(txn: Transaction | None) -> str:
    if txn is None:
        return ""
    a = txn.amount
    return str(int(a)) if a == int(a) else str(a)


def build_agent_summary(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    txn: Transaction | None,
    user_type: UserType | None,
) -> str:
    tid = txn.transaction_id if txn else None
    amt = _amt(txn)
    cp = txn.counterparty if txn else None

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "Customer reports an unsolicited contact requesting credentials (PIN/OTP). "
            "Likely social engineering attempt. Credentials reportedly not yet shared."
        )
    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return (
                f"Customer claims {tid} ({amt} BDT to {cp}) was a wrong transfer, but the "
                f"transaction history shows multiple prior transfers to the same counterparty, "
                f"suggesting an established recipient."
            )
        if tid is None:
            return (
                "Customer reports a transfer that was not received, but multiple transactions "
                "of the stated amount exist for two or more recipients. The specific transaction "
                "cannot be determined without further input."
            )
        return (
            f"Customer reports sending {amt} BDT via {tid} to {cp}, which they now believe was "
            f"the wrong recipient. Recipient is reportedly unresponsive."
        )
    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"Customer attempted a {amt} BDT payment ({tid}) which failed, but reports the "
            f"balance was deducted. Requires payments operations investigation."
        )
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"Customer reports a duplicate payment. Two identical {amt} BDT payments to the same "
            f"counterparty were completed close together; {tid} is the suspected duplicate."
        )
    if case_type == CaseType.REFUND_REQUEST:
        return (
            f"Customer requests a refund of {amt} BDT for {tid} (merchant payment) due to change "
            f"of mind. Not a service failure."
        )
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"Merchant reports a {amt} BDT settlement ({tid}) delayed beyond the standard next-day "
            f"window. Settlement status is pending."
        )
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"Customer reports a {amt} BDT cash-in via agent ({tid}) not reflected in balance. "
            f"Agent claims funds were sent; transaction requires agent operations review."
        )
    # other
    return (
        "Customer reports a vague concern without specifying transaction, amount, or issue. "
        "Insufficient detail to identify any relevant transaction."
    )


def build_next_action(
    case_type: CaseType, verdict: EvidenceVerdict, txn: Transaction | None
) -> str:
    tid = txn.transaction_id if txn else None

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "Escalate to the fraud_risk team immediately. Reassure the customer that the company "
            "never asks for OTP or PIN. Log the reported contact for fraud pattern analysis."
        )
    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return (
                "Flag for human review. Verify with the customer whether this was genuinely a wrong "
                "transfer given the established transaction pattern with this recipient."
            )
        if tid is None:
            return (
                "Reply to the customer asking for the recipient's number to identify the correct "
                "transaction. Do not initiate a dispute until the transaction is confirmed."
            )
        return (
            f"Verify {tid} details with the customer and initiate the wrong-transfer dispute "
            f"workflow per policy."
        )
    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"Investigate the {tid} ledger status. If the balance was deducted on a failed payment, "
            f"initiate the automatic reversal flow within standard SLA."
        )
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"Verify the duplicate with payments_ops. If the biller confirms only one payment was "
            f"received, initiate reversal of {tid}."
        )
    if case_type == CaseType.REFUND_REQUEST:
        return (
            "Inform the customer that refund eligibility depends on the merchant's own policy. "
            "Provide guidance on contacting the merchant directly for a refund."
        )
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"Route to merchant_operations to verify the settlement batch status for {tid}. If the "
            f"batch is delayed, communicate a revised ETA to the merchant."
        )
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"Investigate the {tid} pending status with agent operations. Confirm the settlement "
            f"state and resolve within the standard cash-in SLA."
        )
    return (
        "Reply to the customer asking for specific details: which transaction, what amount, what "
        "went wrong, and the approximate time."
    )


def _reply_en(case_type: CaseType, verdict: EvidenceVerdict, tid: str | None) -> str:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "Thank you for reaching out before sharing any information. We never ask for your PIN, "
            "OTP, or password under any circumstances. Please do not share these with anyone, even "
            "if they claim to be from us. Our fraud team has been notified of this incident."
        )
    if case_type == CaseType.WRONG_TRANSFER:
        if tid is None:
            return (
                "Thank you for reaching out. We see more than one transaction of that amount on the "
                "date in question. Could you share the recipient's number so we can identify the "
                f"right transaction? {_SAFE_EN}"
            )
        return (
            f"We have received your request regarding transaction {tid}. {_SAFE_EN} Our dispute team "
            f"will review the case carefully and contact you through official support channels."
        )
    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"We have noted that transaction {tid} may have caused an unexpected balance deduction. "
            f"Our payments team will review the case and any eligible amount will be returned through "
            f"official channels. {_SAFE_EN}"
        )
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"We have noted the possible duplicate payment for transaction {tid}. Our payments team "
            f"will verify with the biller and any eligible amount will be returned through official "
            f"channels. {_SAFE_EN}"
        )
    if case_type == CaseType.REFUND_REQUEST:
        return (
            "Thank you for reaching out. Refunds for completed merchant payments depend on the "
            "merchant's own policy. We recommend contacting the merchant directly. If you need help "
            f"reaching them, please reply and we will guide you. {_SAFE_EN}"
        )
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"We have noted your concern about settlement {tid}. Our merchant operations team will "
            f"check the batch status and update you on the expected settlement time through official "
            f"channels."
        )
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"We have noted your concern about transaction {tid}. Our agent operations team will "
            f"verify it promptly and update you through official channels. {_SAFE_EN}"
        )
    return (
        "Thank you for reaching out. To help you faster, please share the transaction ID, the amount "
        f"involved, and a short description of what went wrong. {_SAFE_EN}"
    )


def _reply_bn(case_type: CaseType, verdict: EvidenceVerdict, tid: str | None) -> str:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "কোনো তথ্য শেয়ার করার আগে আমাদের জানানোর জন্য ধন্যবাদ। আমরা কখনোই আপনার পিন, ওটিপি বা "
            "পাসওয়ার্ড চাই না। কেউ নিজেকে আমাদের প্রতিনিধি দাবি করলেও এগুলো কারো সাথে শেয়ার করবেন না। "
            "আমাদের ফ্রড টিমকে বিষয়টি জানানো হয়েছে।"
        )
    if case_type == CaseType.WRONG_TRANSFER:
        if tid is None:
            return (
                "যোগাযোগ করার জন্য ধন্যবাদ। ওই তারিখে একই পরিমাণের একাধিক লেনদেন দেখা যাচ্ছে। সঠিক "
                "লেনদেনটি শনাক্ত করতে অনুগ্রহ করে প্রাপকের নম্বরটি জানান। " + _SAFE_BN
            )
        return (
            f"আপনার লেনদেন {tid} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের ডিসপিউট টিম বিষয়টি যত্নসহকারে "
            f"পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনার সাথে যোগাযোগ করবে। " + _SAFE_BN
        )
    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"আপনার লেনদেন {tid} এর কারণে ব্যালেন্স কেটে যাওয়ার বিষয়টি আমরা নোট করেছি। আমাদের পেমেন্টস "
            f"টিম বিষয়টি যাচাই করবে এবং প্রযোজ্য কোনো অর্থ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে। "
            + _SAFE_BN
        )
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"লেনদেন {tid} এর সম্ভাব্য ডাবল পেমেন্টের বিষয়টি আমরা নোট করেছি। আমাদের পেমেন্টস টিম "
            f"বিলারের সাথে যাচাই করবে এবং প্রযোজ্য কোনো অর্থ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে। "
            + _SAFE_BN
        )
    if case_type == CaseType.REFUND_REQUEST:
        return (
            "যোগাযোগ করার জন্য ধন্যবাদ। সম্পন্ন হওয়া মার্চেন্ট পেমেন্টের রিফান্ড মার্চেন্টের নিজস্ব "
            "নীতির উপর নির্ভর করে। আমরা সরাসরি মার্চেন্টের সাথে যোগাযোগ করার পরামর্শ দিচ্ছি। " + _SAFE_BN
        )
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"সেটেলমেন্ট {tid} এর বিষয়ে আপনার উদ্বেগ আমরা নোট করেছি। আমাদের মার্চেন্ট অপারেশন্স টিম "
            f"ব্যাচের অবস্থা যাচাই করবে এবং প্রত্যাশিত সেটেলমেন্ট সময় সম্পর্কে অফিসিয়াল চ্যানেলে জানাবে।"
        )
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"আপনার লেনদেন {tid} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই "
            f"করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। " + _SAFE_BN
        )
    return (
        "যোগাযোগ করার জন্য ধন্যবাদ। দ্রুত সহায়তার জন্য অনুগ্রহ করে লেনদেন আইডি, সংশ্লিষ্ট পরিমাণ এবং "
        "কী সমস্যা হয়েছে তা সংক্ষেপে জানান। " + _SAFE_BN
    )


def build_customer_reply(
    case_type: CaseType, verdict: EvidenceVerdict, txn: Transaction | None, lang: str
) -> str:
    tid = txn.transaction_id if txn else None
    if lang == "bn":
        return _reply_bn(case_type, verdict, tid)
    return _reply_en(case_type, verdict, tid)
