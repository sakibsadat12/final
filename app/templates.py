"""Deterministic, safe narrative generation. Null-safe and injection-safe."""

from __future__ import annotations

import re

from .enums import CaseType, EvidenceVerdict, Language
from .normalizers import dominant_script, is_bangla
from .schemas import Transaction

_SAFE_EN = "Please do not share your PIN or OTP with anyone."
_SAFE_BN = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
_TXN_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,39}$")


def reply_language(language: Language | None, complaint: str) -> str:
    if language == Language.BN:
        return "bn"
    if language == Language.EN:
        return "en"
    if language == Language.MIXED:
        return dominant_script(complaint)
    return "bn" if is_bangla(complaint) else "en"


def _safe_id(txn: Transaction | None) -> str | None:
    """Return the transaction id only if it looks like a real id (not injected text)."""
    if txn is None or not txn.transaction_id:
        return None
    tid = txn.transaction_id.strip()
    return tid if _TXN_ID_OK.match(tid) else None


def _amt(txn: Transaction | None) -> str:
    if txn is None:
        return ""
    a = txn.amount
    try:
        return str(int(a)) if a == int(a) else str(a)
    except (ValueError, OverflowError):
        return ""


def build_agent_summary(case_type, verdict, txn, user_type, match_kind="single") -> str:
    tid = _safe_id(txn)
    amt = _amt(txn)
    ref = f"transaction {tid}" if tid else "the reported transaction"

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return ("Customer reports an unsolicited contact requesting credentials (PIN/OTP). "
                "Likely social engineering; credentials reportedly not yet shared.")
    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return (f"Customer claims {ref} was a wrong transfer, but the history shows multiple "
                    f"prior transfers to the same counterparty, suggesting an established recipient.")
        if tid is None:
            return ("Customer reports a transfer not received, but the specific transaction cannot "
                    "be determined from the provided history without more detail.")
        return (f"Customer reports {ref}" + (f" of {amt} BDT" if amt else "") +
                " which they now believe went to the wrong recipient.")
    if case_type == CaseType.PAYMENT_FAILED:
        if tid is None:
            return ("Customer reports a payment that failed while the balance was deducted, but the "
                    "specific transaction is not identifiable from the provided history.")
        return (f"Customer reports a payment ({tid})" + (f" of {amt} BDT" if amt else "") +
                " that failed while the balance was deducted. Needs payments-ops review.")
    if case_type == CaseType.DUPLICATE_PAYMENT:
        if match_kind == "single_payment":
            return (f"Customer reports a duplicate charge, but only one matching payment "
                    f"({tid or 'in history'}) is present; the duplicate claim is not supported by the data.")
        if tid is None:
            return ("Customer reports a duplicate charge, but a second matching payment could not be "
                    "confirmed from the provided history.")
        return (f"Customer reports a duplicate payment; {ref}" + (f" of {amt} BDT" if amt else "") +
                " appears to be the suspected duplicate (later of two identical charges).")
    if case_type == CaseType.REFUND_REQUEST:
        if tid is None:
            return "Customer requests a refund; the specific transaction needs to be confirmed."
        return f"Customer requests a refund for {ref}" + (f" of {amt} BDT" if amt else "") + " (change of mind)."
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        if tid is None:
            return "Merchant reports a delayed settlement; the specific settlement needs confirmation."
        return f"Merchant reports settlement {tid}" + (f" of {amt} BDT" if amt else "") + " delayed beyond the expected window."
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        if tid is None:
            return "Customer reports an agent cash-in not reflected in balance; transaction needs confirmation."
        return f"Customer reports an agent cash-in ({tid})" + (f" of {amt} BDT" if amt else "") + " not reflected in balance."
    return ("Customer reports a vague concern without specifying transaction, amount, or issue. "
            "Insufficient detail to identify a relevant transaction.")


def build_next_action(case_type, verdict, txn, match_kind="single") -> str:
    tid = _safe_id(txn)
    ref = tid if tid else "the reported transaction"

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return ("Escalate to the fraud_risk team. Reassure the customer the company never asks for "
                "OTP or PIN. Log the reported contact for fraud pattern analysis.")
    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return ("Flag for human review. Verify whether this was genuinely a wrong transfer given "
                    "the established transaction pattern with this recipient.")
        if tid is None:
            return ("Ask the customer for the recipient's number or transaction id to identify the "
                    "correct transaction before initiating a dispute.")
        return f"Verify {ref} details with the customer and initiate the wrong-transfer dispute workflow per policy."
    if case_type == CaseType.PAYMENT_FAILED:
        if tid is None:
            return "Ask the customer for the transaction id/time, then check the ledger for a deducted-but-failed payment."
        return f"Investigate the {ref} ledger status; if balance was deducted on a failed payment, initiate the reversal flow within SLA."
    if case_type == CaseType.DUPLICATE_PAYMENT:
        if match_kind == "single_payment":
            return "Confirm with the customer; the history shows a single charge, so verify before any action."
        if tid is None:
            return "Ask the customer for details of the second charge to confirm the duplicate."
        return f"Verify the duplicate with payments_ops; if the biller confirms a single receipt, initiate reversal of {ref}."
    if case_type == CaseType.REFUND_REQUEST:
        return ("Inform the customer that refund eligibility depends on the merchant's own policy and "
                "guide them to contact the merchant through official channels.")
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return f"Route to merchant_operations to verify the settlement batch status for {ref}; communicate a revised ETA if delayed."
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return f"Investigate the {ref} status with agent operations and resolve within the standard cash-in SLA."
    return "Reply to the customer asking for specifics: which transaction, what amount, what went wrong, and approximate time."


def _reply_en(case_type, verdict, tid, match_kind) -> str:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return ("Thank you for reaching out before sharing any information. We never ask for your PIN, "
                "OTP, or password under any circumstances. Please do not share these with anyone, even "
                "if they claim to be from us. Our fraud team has been notified of this incident.")
    if case_type == CaseType.WRONG_TRANSFER:
        if tid is None:
            return ("Thank you for reaching out. Could you share the recipient's number or the transaction "
                    f"id so we can identify the right transaction? {_SAFE_EN}")
        return (f"We have received your request regarding transaction {tid}. {_SAFE_EN} Our dispute team "
                "will review the case carefully and contact you through official support channels.")
    if case_type == CaseType.PAYMENT_FAILED:
        if tid is None:
            return ("Thank you for reaching out. Please share the transaction id or time of the failed "
                    f"payment so our payments team can review it. {_SAFE_EN}")
        return (f"We have noted that transaction {tid} may have caused an unexpected balance deduction. "
                "Our payments team will review the case and any eligible amount will be returned through "
                f"official channels. {_SAFE_EN}")
    if case_type == CaseType.DUPLICATE_PAYMENT:
        if tid is None:
            return ("Thank you for reaching out. Could you share the details of the second charge so our "
                    f"payments team can verify the possible duplicate? {_SAFE_EN}")
        return (f"We have noted the possible duplicate payment for transaction {tid}. Our payments team "
                "will verify with the biller and any eligible amount will be returned through official "
                f"channels. {_SAFE_EN}")
    if case_type == CaseType.REFUND_REQUEST:
        return ("Thank you for reaching out. Refunds for completed merchant payments depend on the "
                "merchant's own policy. We recommend contacting the merchant directly. If you need help "
                f"reaching them, please reply and we will guide you. {_SAFE_EN}")
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        ref = f"settlement {tid}" if tid else "your settlement"
        return (f"We have noted your concern about {ref}. Our merchant operations team will check the "
                "batch status and update you on the expected settlement time through official channels.")
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        ref = f"transaction {tid}" if tid else "your cash-in"
        return (f"We have noted your concern about {ref}. Our agent operations team will verify it "
                f"promptly and update you through official channels. {_SAFE_EN}")
    return ("Thank you for reaching out. To help you faster, please share the transaction id, the amount "
            f"involved, and a short description of what went wrong. {_SAFE_EN}")


def _reply_bn(case_type, verdict, tid, match_kind) -> str:
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return ("কোনো তথ্য শেয়ার করার আগে আমাদের জানানোর জন্য ধন্যবাদ। আমরা কখনোই আপনার পিন, ওটিপি বা "
                "পাসওয়ার্ড চাই না। কেউ নিজেকে আমাদের প্রতিনিধি দাবি করলেও এগুলো কারো সাথে শেয়ার করবেন না। "
                "আমাদের ফ্রড টিমকে বিষয়টি জানানো হয়েছে।")
    if case_type == CaseType.WRONG_TRANSFER:
        if tid is None:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। সঠিক লেনদেনটি শনাক্ত করতে অনুগ্রহ করে প্রাপকের নম্বর বা "
                    "লেনদেন আইডি জানান। " + _SAFE_BN)
        return (f"আপনার লেনদেন {tid} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের ডিসপিউট টিম বিষয়টি যত্নসহকারে "
                "পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনার সাথে যোগাযোগ করবে। " + _SAFE_BN)
    if case_type == CaseType.PAYMENT_FAILED:
        if tid is None:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। ব্যর্থ পেমেন্টের লেনদেন আইডি বা সময় জানালে আমাদের পেমেন্টস "
                    "টিম এটি যাচাই করতে পারবে। " + _SAFE_BN)
        return (f"আপনার লেনদেন {tid} এর কারণে ব্যালেন্স কেটে যাওয়ার বিষয়টি আমরা নোট করেছি। আমাদের পেমেন্টস "
                "টিম যাচাই করবে এবং প্রযোজ্য কোনো অর্থ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে। " + _SAFE_BN)
    if case_type == CaseType.DUPLICATE_PAYMENT:
        if tid is None:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। সম্ভাব্য ডাবল পেমেন্ট যাচাই করতে দ্বিতীয় চার্জের বিবরণ জানান। "
                    + _SAFE_BN)
        return (f"লেনদেন {tid} এর সম্ভাব্য ডাবল পেমেন্টের বিষয়টি আমরা নোট করেছি। আমাদের পেমেন্টস টিম যাচাই "
                "করবে এবং প্রযোজ্য কোনো অর্থ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে। " + _SAFE_BN)
    if case_type == CaseType.REFUND_REQUEST:
        return ("যোগাযোগ করার জন্য ধন্যবাদ। সম্পন্ন হওয়া মার্চেন্ট পেমেন্টের রিফান্ড মার্চেন্টের নিজস্ব নীতির "
                "উপর নির্ভর করে। আমরা সরাসরি মার্চেন্টের সাথে যোগাযোগ করার পরামর্শ দিচ্ছি। " + _SAFE_BN)
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        ref = f"সেটেলমেন্ট {tid}" if tid else "আপনার সেটেলমেন্ট"
        return (f"{ref} এর বিষয়ে আপনার উদ্বেগ আমরা নোট করেছি। আমাদের মার্চেন্ট অপারেশন্স টিম ব্যাচের অবস্থা "
                "যাচাই করবে এবং প্রত্যাশিত সেটেলমেন্ট সময় অফিসিয়াল চ্যানেলে জানাবে।")
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        ref = f"লেনদেন {tid}" if tid else "আপনার ক্যাশ ইন"
        return (f"{ref} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই করবে এবং "
                f"অফিসিয়াল চ্যানেলে আপনাকে জানাবে। " + _SAFE_BN)
    return ("যোগাযোগ করার জন্য ধন্যবাদ। দ্রুত সহায়তার জন্য অনুগ্রহ করে লেনদেন আইডি, সংশ্লিষ্ট পরিমাণ এবং কী "
            "সমস্যা হয়েছে তা সংক্ষেপে জানান। " + _SAFE_BN)


def build_customer_reply(case_type, verdict, txn, lang, match_kind="single") -> str:
    tid = _safe_id(txn)
    if lang == "bn":
        return _reply_bn(case_type, verdict, tid, match_kind)
    return _reply_en(case_type, verdict, tid, match_kind)
