# Vera Bot - magicpin AI Challenge
<img width="923" height="193" alt="image" src="https://github.com/user-attachments/assets/5714df8a-d25b-4964-8771-2c4ac978a7ad" />


Production-grade message engine. FastAPI server implementing all 5 required endpoints.


## Architecture
**Signal-selection pipeline → LLM writer** (not LLM thinker).
<img width="1280" height="428" alt="image" src="https://github.com/user-attachments/assets/eb0fe177-2512-43a9-970d-388b38bf9a12" />

Decisions happen deterministically in Python before the LLM is called:

1. **Signal selection** — each trigger scored by `urgency × category_match × signal_alignment × kind_priority`. Threshold gate at 0.3.
2. **Decision frame** — trigger kind maps to a strategy (frame, CTA shape, compulsion levers, send_as identity). 26 trigger kinds covered.
3. **Prompt construction** — full category voice profile, peer benchmarks, seasonal beats, trend signals, review themes, conversation history, customer relationship state — all assembled into a structured prompt.
4. **LLM composition** — Claude Sonnet 4 at `temperature=0`. Writer only.
5. **Validation** — taboo words, URLs, multi-CTA, internal jargon, re-introductions, missing specificity anchor → all rejected, fallback fires.
6. **Fallback** — 26 deterministic per-trigger templates that pull real data (peer stats, batch numbers, dates, offer titles, review themes).
                            <img width="350" height="815" alt="image" src="https://github.com/user-attachments/assets/c2a83757-03a5-4369-9e25-498cd14119b3" />


## Reply handling FSM

- **Auto-reply detected** (per-merchant counter across conversations): turn 1 → `wait 4h`, turn 2 → `wait 24h`, turn 3+ → `end`
- **Positive intent** → action mode immediately. Body contains action verbs (`done`, `sending`, `draft`, `confirm`, `proceed`, `next`), no qualifying questions
- **Negative/hostile** → apologetic exit ("Sorry for the bother — I won't message again"), conversation suppressed
- **Off-topic** → polite decline + redirect to original thread
- **Engaged** → LLM-handled with full conversation context

## Production hardening
<img width="1280" height="608" alt="image" src="https://github.com/user-attachments/assets/0536a279-aaac-43b5-b9e6-e2dd8437dce9" />

- Pydantic request validation on all endpoints (400 on bad input, no crashes)
- Async timeouts: 25s on /tick and /reply (judge spec is 30s)
- LLM client: retry with exponential backoff on HTTP 429/5xx and network errors
- Tick idempotency: same `(now, triggers)` returns cached result
- TTL-based GC: conversations expire after 7d, suppression keys after 3d
- Thread-safe state with reentrant locks
- Structured JSON request logging (req_id, path, status, elapsed_ms)
- Container: non-root user, healthcheck, 2 uvicorn workers
- Graceful degradation: every error path returns valid JSON, never 500s

## Deploy

```bash
docker build -t vera-bot .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... vera-bot
```

Or to Railway/Render: connect this repo, set `ANTHROPIC_API_KEY`, deploy. Public URL ready in ~2 minutes.

## Endpoints

| Endpoint | Method | Notes |
|---|---|---|
| /v1/healthz | GET | Returns uptime + context counts + LLM config status |
| /v1/metadata | GET | Team identity + approach |
| /v1/context | POST | Idempotent by (scope, context_id, version). 409 on stale version. |
| /v1/tick | POST | Returns up to 20 ranked actions. Cached by (now, triggers). |
| /v1/reply | POST | Returns send/wait/end action. FSM handles intent transitions. |

## Tradeoffs

- **In-memory store** — fits the challenge (judge runs against single instance for ~3 days). For real prod, swap for Redis/Postgres.
- **temperature=0 LLM** — same input → same output. The judge tests for determinism.
- **Fallback-first** — even when the LLM fails completely, every trigger kind has a template that pulls real data and scores well.
- **Single LLM model** — Sonnet 4 chosen for instruction-following + cost. Could swap via env var if needed.

## What additional context would have helped

- Anonymized real Vera ↔ merchant transcripts (to tune auto-reply phrase library)
- The exact judge LLM and its temperature (to better predict scoring drift)
- A few "ground-truth" human-scored samples per category for calibration
