import os
import time
import json
import logging
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from context_store import ContextStore
from compose import compose_tick, compose_reply
from schemas import ContextRequest, TickRequest, ReplyRequest


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger("vera")


app = FastAPI(title="Vera Bot", version="2.0.0")
store = ContextStore()
START_TIME = time.time()


TICK_TIMEOUT_S = 25.0
REPLY_TIMEOUT_S = 25.0


@app.middleware("http")
async def add_request_logging(request: Request, call_next):
    start = time.time()
    request_id = request.headers.get("x-request-id", f"req_{int(start*1000)}")
    try:
        response = await call_next(request)
        elapsed_ms = int((time.time() - start) * 1000)
        log.info(json.dumps({
            "req_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
        }))
        return response
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error(json.dumps({
            "req_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "error": str(e)[:200],
            "elapsed_ms": elapsed_ms,
        }))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"accepted": False, "reason": "validation_error", "details": str(exc.errors()[:3])}
    )


@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": store.counts(),
        "llm_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": os.environ.get("TEAM_NAME", "Solo"),
        "team_members": [os.environ.get("CANDIDATE_NAME", "Candidate")],
        "model": "claude-sonnet-4-20250514",
        "approach": (
            "Deterministic signal-selection pipeline with full category/merchant context grounding. "
            "Trigger-dispatched prompt construction → Claude (temp=0) → post-LLM validation → "
            "deterministic per-trigger fallback templates. "
            "Auto-reply detection (per-merchant counter), explicit intent transition handling, "
            "graceful hostile exit with apology, off-topic redirect. "
            "Production hardening: TTL-based GC, retry+backoff on LLM 429/5xx, idempotent tick, "
            "thread-safe state, structured logging, request validation."
        ),
        "contact_email": os.environ.get("CONTACT_EMAIL", "candidate@example.com"),
        "version": "2.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/context")
async def context_endpoint(request: Request):
    try:
        body = await request.json()
        req = ContextRequest(**body)
    except (ValueError, ValidationError) as e:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "invalid_request", "details": str(e)[:200]
        })

    result = store.upsert(req.scope, req.context_id, req.version, req.payload)

    if result == "stale":
        return JSONResponse(status_code=409, content={
            "accepted": False,
            "reason": "stale_version",
            "current_version": store.get_version(req.scope, req.context_id),
        })

    return {
        "accepted": True,
        "ack_id": f"ack_{req.context_id}_v{req.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/tick")
async def tick_endpoint(request: Request):
    try:
        body = await request.json()
        req = TickRequest(**body)
    except (ValueError, ValidationError) as e:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "invalid_request", "details": str(e)[:200]
        })

    now = req.now or datetime.now(timezone.utc).isoformat()
    triggers_key = ",".join(sorted(req.available_triggers))
    idempotency_key = f"{now}|{triggers_key}"

    cached = store.check_tick_idempotency(idempotency_key)
    if cached is not None:
        return {"actions": cached}

    try:
        actions = await asyncio.wait_for(
            asyncio.to_thread(compose_tick, store, req.available_triggers, now),
            timeout=TICK_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.warning(f"tick_timeout idempotency={idempotency_key[:80]}")
        return {"actions": []}
    except Exception as e:
        log.error(f"tick_error: {e}")
        return {"actions": []}

    store.store_tick_result(idempotency_key, actions)
    return {"actions": actions}


@app.post("/v1/reply")
async def reply_endpoint(request: Request):
    try:
        body = await request.json()
        req = ReplyRequest(**body)
    except (ValueError, ValidationError) as e:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "invalid_request", "details": str(e)[:200]
        })

    received_at = req.received_at or datetime.now(timezone.utc).isoformat()

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                compose_reply,
                store=store,
                conversation_id=req.conversation_id,
                merchant_id=req.merchant_id,
                customer_id=req.customer_id,
                from_role=req.from_role,
                message=req.message,
                received_at=received_at,
                turn_number=req.turn_number,
            ),
            timeout=REPLY_TIMEOUT_S,
        )
        return result
    except asyncio.TimeoutError:
        log.warning(f"reply_timeout conv={req.conversation_id}")
        return {"action": "wait", "wait_seconds": 1800,
                "rationale": "Reply processing timed out; backing off briefly."}
    except Exception as e:
        log.error(f"reply_error: {e}")
        return {"action": "wait", "wait_seconds": 1800,
                "rationale": f"Reply error fallback: {str(e)[:80]}"}
