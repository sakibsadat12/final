# QueueStorm Investigator

A deterministic, production-grade complaint-ticket investigator for a mobile
financial service (bKash-style). It classifies a support ticket, matches it
against the customer's transaction history using evidence, decides routing and
severity, and produces a **safe** customer reply — with no refund promises and no
credential requests.

> **Design principle:** the scored decision fields are produced by deterministic
> rules only. The optional LLM layer (off by default) may *rewrite narrative
> text* but can never change `case_type`, `department`, `severity`,
> `relevant_transaction_id`, `evidence_verdict`, or `human_review_required`.

## API

### `GET /health`
```json
{ "status": "ok" }
```

### `POST /analyze-ticket`

**Request** (required: `ticket_id`, `complaint`; everything else optional):
```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

**Response** (`200`):
```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT via TXN-9101 ...",
  "recommended_next_action": "Verify TXN-9101 details with the customer ...",
  "customer_reply": "We have received your request regarding transaction TXN-9101. Please do not share your PIN or OTP with anyone. ...",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match"]
}
```

**HTTP error contract**

| Status | Condition |
|--------|-----------|
| `400`  | Body is not valid JSON |
| `413`  | Body larger than 16 KB |
| `422`  | Valid JSON but schema/semantic validation failed (missing required field, empty complaint, invalid enum) |
| `500`  | Unexpected internal error (generic message, never a stack trace or secret) |

## Setup & run

### Local (Python 3.12)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Then:
```bash
curl localhost:8000/health
curl -X POST localhost:8000/analyze-ticket \
  -H 'content-type: application/json' \
  -d '{"ticket_id":"T","complaint":"I sent 5000 taka to the wrong number.","transaction_history":[{"transaction_id":"TXN-1","timestamp":"2026-04-14T14:00:00Z","type":"transfer","amount":5000,"counterparty":"+8801711111111","status":"completed"}]}'
```

### Docker
```bash
docker build -t queuestorm .
docker run -p 8000:8000 queuestorm
# honours $PORT if provided: docker run -e PORT=9000 -p 9000:9000 queuestorm
```

### Tests
```bash
pip install pytest httpx
pytest tests/ -q
```

## Models / AI usage

**Primary path: rule-based, no model.** All scored fields come from deterministic
code (`classifier.py`, `matcher.py`, `policy.py`). This is intentional —
determinism gives reproducible scoring, sub-millisecond latency, and zero risk of
a model inventing an unsafe reply.

**Optional polish:** if `LLM_ENABLED=true` and `ANTHROPIC_API_KEY` is set, an LLM
may rewrite only the narrative strings (`customer_reply`,
`recommended_next_action`, `agent_summary`) at temperature 0, behind a 6 s
timeout, a circuit breaker, and a safety post-filter. Any failure falls back to
the deterministic text. The default deployment runs with **no model**.

## Safety logic

`safety.py` post-filters every customer-facing and agent-facing string and is the
final gate before the response is returned:

- **Credential requests** — blocks "share/send/provide your PIN/OTP/password/card"
  but allows the negated safe warning "do **not** share your PIN or OTP".
- **Unauthorised promises** — blocks "we will refund/reverse/unblock/recover" and
  "refund approved"; the only allowed money phrasing is "any eligible amount will
  be returned through official channels".
- **Third-party redirection** — blocks phone numbers in customer replies.
- **Prompt injection** — instructions embedded in a complaint are ignored; any
  echoed injection ("ignore previous instructions", "refund approved") is stripped
  and replaced with a safe fallback.

## Evidence-reasoning approach

1. **Classify** the case with weighted keyword rules across English, Bangla, and
   Banglish; ties broken by a fixed priority order.
2. **Parse amounts** from the complaint, ignoring transaction IDs, phone numbers,
   and time tokens; Bengali numerals are converted first.
3. **Match** the relevant transaction by amount + aligned transaction type.
   - One match → that transaction.
   - Several plausible matches → **no guess**: `relevant_transaction_id = null`,
     `insufficient_data` (date phrases may narrow, but only to a unique match).
   - Duplicate pattern (two completed payments to the same counterparty within
     5 minutes) → the **later** transaction is the suspected duplicate.
4. **Verdict**: `consistent` when evidence supports the claim; `inconsistent` when
   a wrong-transfer claim contradicts an established-recipient pattern (≥2 prior
   transfers to the same counterparty); `insufficient_data` otherwise.
5. **Policy** maps case + verdict to severity, department, and human-review.

Relative dates ("today"/"yesterday") are anchored to the **newest timestamp in
the supplied history**, never the server clock, because judge data is synthetic.

## Assumptions

- Amounts in complaints are in BDT.
- A wrong-transfer claim with ≥2 prior transfers to the same counterparty is
  treated as an established recipient (inconsistent), pending human review.
- Duplicate window is 5 minutes (configurable via `DUPLICATE_WINDOW_S`).
- `agent_summary` / `recommended_next_action` are always English (internal); only
  `customer_reply` is localised to Bangla for Bangla complaints.

## Known limitations

- Classification is keyword-driven; highly unusual phrasings may fall through to
  `other` (deliberately conservative — it asks for clarification rather than
  guessing).
- Amount parsing targets BDT-style integers/decimals; exotic formats may be
  missed, which safely degrades to `insufficient_data`.
- The optional LLM path is best-effort and never trusted for scored fields.
