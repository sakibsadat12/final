"""FastAPI application and HTTP contract.

Endpoints:
    GET  /health         -> {"status": "ok"}
    POST /analyze-ticket -> AnalyzeResponse

Error contract:
    400  invalid JSON body
    413  payload larger than 16 KB
    422  valid JSON but schema/semantic validation failed
    500  unexpected internal error (generic message, no stack trace or secrets)
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import config
from .pipeline import analyze
from .schemas import AnalyzeRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("queuestorm")

app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0.0",
    description="Deterministic complaint-ticket investigator for a mobile financial service.",
)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "service": "QueueStorm Investigator",
            "version": "1.0.0",
            "endpoints": ["GET /health", "POST /analyze-ticket"],
        },
    )


@app.post("/analyze-ticket")
async def analyze_ticket(request: Request) -> JSONResponse:
    # 1. Enforce payload size on the raw bytes (cheap header check first).
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > config.MAX_BODY_BYTES:
                return _error(413, "payload_too_large", "Request body exceeds 16 KB limit.")
        except ValueError:
            pass

    body = await request.body()
    if len(body) > config.MAX_BODY_BYTES:
        return _error(413, "payload_too_large", "Request body exceeds 16 KB limit.")

    # 2. Parse JSON (malformed -> 400).
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(400, "invalid_json", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        return _error(422, "invalid_payload", "Request body must be a JSON object.")

    # 3. Validate schema (invalid/missing fields, bad enums, empty complaint -> 422).
    try:
        req = AnalyzeRequest.model_validate(data)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "detail": _format_errors(exc)},
        )

    # 4. Run the deterministic analysis (any unexpected failure -> generic 500).
    try:
        response = analyze(req)
    except Exception:  # noqa: BLE001 - last-resort guard; never leak internals
        logger.exception("analysis_failed ticket_id=%s", getattr(req, "ticket_id", "?"))
        return _error(500, "internal_error", "An internal error occurred while processing the ticket.")

    return JSONResponse(status_code=200, content=response.model_dump())


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": message})


def _format_errors(exc: ValidationError) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        out.append({"field": loc, "message": err.get("msg", "invalid")})
    return out
