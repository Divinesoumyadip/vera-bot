import os
import time
import json
import logging
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from context_store import ContextStore
from compose import compose_tick, compose_reply
from schemas import ContextRequest, TickRequest, ReplyRequest
from bootstrap import bootstrap_dataset


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger("vera")


app = FastAPI(title="Vera Bot", version="3.0.0")
store = ContextStore()
START_TIME = time.time()


TICK_TIMEOUT_S = 28.0
REPLY_TIMEOUT_S = 28.0


@app.on_event("startup")
async def on_startup():
    import os
    log.info(f"CWD: {os.getcwd()} | FILE: {os.path.abspath(__file__)}")
    bootstrap_dataset(store)
    counts = store.counts()
    log.info(f"Vera bot ready. Loaded contexts: {counts}")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.time()
    rid = request.headers.get("x-request-id", f"req_{int(start*1000)}")
    try:
        response = await call_next(request)
        log.info(json.dumps({
            "rid": rid, "method": request.method, "path": request.url.path,
            "status": response.status_code, "ms": int((time.time() - start) * 1000),
        }))
        return response
    except Exception as e:
        log.error(json.dumps({
            "rid": rid, "method": request.method, "path": request.url.path,
            "error": str(e)[:200], "ms": int((time.time() - start) * 1000),
        }))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


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
        "team_members": [os.environ.get("CANDIDATE_NAME", "Soumyadip Das Mahapatra")],
        "model": "claude-sonnet-4-5-20250929",
        "approach": (
            "Deterministic signal-selection pipeline with full category/merchant grounding. "
            "Bundled base dataset for cold-start tick autonomy. "
            "Trigger-dispatched prompt → Claude (temp=0) → post-LLM validation → "
            "26 deterministic per-trigger fallback templates. "
            "Customer-aware reply mode (uses customer name when from_role=customer or customer_id present). "
            "Auto-reply detection (per-merchant counter), explicit intent transition, hostile/STOP handling, "
            "off-topic redirect. Production hardening: TTL-based GC, retry+backoff on LLM 429/5xx, "
            "idempotent tick, thread-safe state, structured logging."
        ),
        "contact_email": os.environ.get("CONTACT_EMAIL", "soumyagle@gmail.com"),
        "version": "3.0.0",
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
            "accepted": False, "reason": "stale_version",
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
    available = req.available_triggers

    if not available:
        all_triggers = store.all_of("trigger")
        candidates = []
        for tid, t in all_triggers.items():
            supp_key = t.get("suppression_key", tid)
            if store.is_suppressed(supp_key):
                continue
            urgency = t.get("urgency", 3)
            candidates.append((urgency, tid))
        candidates.sort(key=lambda x: -x[0])
        available = [tid for _, tid in candidates[:20]]

    triggers_key = ",".join(sorted(available))
    idempotency_key = f"{now}|{triggers_key}"
    cached = store.check_tick_idempotency(idempotency_key)
    if cached is not None:
        return {"actions": cached}

    try:
        actions = await asyncio.wait_for(
            asyncio.to_thread(compose_tick, store, available, now),
            timeout=TICK_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.warning(f"tick_timeout key={idempotency_key[:80]}")
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
                "rationale": "Reply processing timed out; brief backoff."}
    except Exception as e:
        log.error(f"reply_error: {e}")
        return {"action": "wait", "wait_seconds": 1800,
                "rationale": f"Reply error: {str(e)[:80]}"}
