# RUNBOOK — QueueStorm Investigator

Operational guide for running, deploying, and troubleshooting the service.

## 1. Service overview

- **Stack:** FastAPI + Uvicorn, Python 3.12, packaged as a Docker image.
- **State:** stateless. No database, no external calls on the default path.
- **Endpoints:** `GET /health`, `POST /analyze-ticket`.
- **Port:** binds `0.0.0.0:$PORT` (defaults to `8000`).

## 2. Local run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Smoke test:
```bash
curl -fsS localhost:8000/health         # -> {"status":"ok"}
```

## 3. Docker

```bash
docker build -t queuestorm .
docker run --rm -p 8000:8000 queuestorm
```
The image runs as a non-root user and contains no secrets. Image stays well under
1 GB (python:3.12-slim + three pure-Python deps).

## 4. Deployment (Railway)

The repository is connected to Railway. Deployment is **push-to-deploy**:

1. Push to `main`.
2. Railway builds the `Dockerfile` (configured in `railway.json`).
3. Railway injects `PORT`; the container binds it automatically.
4. Health check hits `/health`; the service is marked live when it returns `200`.

Post-deploy verification:
```bash
curl -fsS https://<your-app>.up.railway.app/health
curl -X POST https://<your-app>.up.railway.app/analyze-ticket \
  -H 'content-type: application/json' \
  -d '{"ticket_id":"T","complaint":"Someone asked for my OTP."}'
```

## 5. Configuration

All optional — the service runs deterministically with nothing set. See
`.env.example`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` | Bind port (Railway sets this) |
| `LLM_ENABLED` | `false` | Enable optional narrative polish |
| `ANTHROPIC_API_KEY` | _unset_ | Required only if `LLM_ENABLED=true` |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Polish model |
| `LLM_TIMEOUT_S` | `6` | LLM call timeout |
| `DUPLICATE_WINDOW_S` | `300` | Duplicate-payment detection window |

## 6. Troubleshooting

| Symptom | Likely cause | Action |
|---------|-------------|--------|
| Health check fails on deploy | App didn't bind `$PORT` | Confirm start command uses `--port ${PORT:-8000}` (it does) |
| `400` on a valid-looking request | Body not valid JSON / wrong content-type | Send `content-type: application/json` and valid JSON |
| `413` | Body > 16 KB | Trim `transaction_history` |
| `422` | Missing `ticket_id`/`complaint`, empty complaint, or bad enum | Inspect the `detail` array in the response |
| `500` | Unexpected internal error | Check logs (`analysis_failed ticket_id=...`); no secrets are logged |
| Reply in wrong language | `language` not set and script detection ambiguous | Set `language` explicitly (`en`/`bn`/`mixed`) |

## 7. Rollback

Railway keeps prior deployments. To roll back, redeploy the previous successful
deployment from the Railway dashboard, or `git revert` the offending commit and
push.

## 8. Pre-submission checklist

- [ ] `GET /health` → `{"status":"ok"}`
- [ ] `POST /analyze-ticket` accepts the sample inputs
- [ ] All required response fields present, enum values exact
- [ ] `customer_reply` never requests PIN/OTP and never promises a refund
- [ ] Ambiguous cases return `insufficient_data` (no guessing)
- [ ] `sample_output.json` committed
- [ ] No secrets in repo, logs, image, or README
- [ ] Public endpoint verified from a clean environment
