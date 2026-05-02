# Vera Bot — magicpin AI Challenge

My submission for the magicpin Vera AI Challenge. Live at [vera-bot-yuqy.onrender.com](https://vera-bot-yuqy.onrender.com).

<img width="923" height="193" alt="image" src="https://github.com/user-attachments/assets/5714df8a-d25b-4964-8771-2c4ac978a7ad" />

## Score progression

- v1: **40/100** — LLM API key wasn't set on Render. Tick returned empty actions. Painful debug.
- v2: **85/100** — fixed env vars, bundled dataset in Docker, added customer-aware FSM. Judge said: *"Compose anchors on concrete facts across all 6 trigger kinds. Hindi-English code-mix is fluent."*
- v3 (current): patched the one miss — customer-side replies were addressing the merchant by name. Resubmitted, awaiting score.

## Why this approach

The naive way is to dump everything into the LLM and pray. That gives generic output.

I split it: Python decides *what* to send and *when*, LLM only writes the words. Means I get determinism + good copy. The judge cares more about *why* a message is sent than how flowery it is.

## Architecture

**Signal-selection pipeline → LLM writer** (not LLM thinker).

<img width="1280" height="428" alt="image" src="https://github.com/user-attachments/assets/eb0fe177-2512-43a9-970d-388b38bf9a12" />

Decisions happen deterministically in Python before the LLM is called:

1. **Signal selection** — each trigger scored by `urgency × category_match × signal_alignment × kind_priority`. Threshold gate at 0.3.
2. **Decision frame** — trigger kind maps to a strategy (frame, CTA shape, compulsion levers, send_as identity). 26 trigger kinds covered.
3. **Prompt construction** — full category voice profile, peer benchmarks, seasonal beats, trend signals, review themes, conversation history, customer relationship state — all assembled into a structured prompt.
4. **LLM composition** — Claude Sonnet at `temperature=0`. Writer only.
5. **Validation** — taboo words, URLs, multi-CTA, internal jargon, re-introductions, missing specificity anchor → all rejected, fallback fires.
6. **Fallback** — 26 deterministic per-trigger templates that pull real data (peer stats, batch numbers, dates, offer titles, review themes).

<img width="350" height="815" alt="image" src="https://github.com/user-attachments/assets/c2a83757-03a5-4369-9e25-498cd14119b3" />

## Reply handling FSM

- **Auto-reply detected** (per-merchant counter across conversations): turn 1 → `wait 4h`, turn 2 → `wait 24h`, turn 3+ → `end`
- **Positive intent** → action mode immediately. Body contains action verbs (`done`, `sending`, `draft`, `confirm`, `proceed`, `next`), no qualifying questions
- **Negative/hostile** → apologetic exit ("Sorry for the bother — I won't message again"), conversation suppressed
- **Off-topic** → polite decline + redirect to original thread
- **Engaged** → LLM-handled with full conversation context

## v5 add-ons (after the 85/100 baseline)

Built these after studying what real Vera does on magicpin's product page:

- **Multi-language voices** — 10 Indian languages (Tamil, Telugu, Kannada, Marathi, Bengali, Gujarati, Punjabi, Malayalam, Odia, Hindi). Picks the merchant's regional language over English.
- **WhatsApp-native formatting** — line breaks between hook → detail → CTA. Real WhatsApp shape, not flat email prose.
- **Lead qualification scoring** — booking + pricing + intent + time signals → Hot/Warm/Cold label per customer message.
- **GBP optimization hints** — embedded in tick output for relevant triggers (unverified GBP, missing description, low reply rate).
- **Review reply drafts** — auto-generated for `review_theme_emerged` triggers.

## Tradeoffs I'm aware of

- **In-memory store** loses state on restart. Fine for the challenge (judge runs ~3 days against single instance), would use Redis in prod.
- **Customer reply path took 3 iterations.** First version branched on `customer_id`, second on customer object, finally just on `from_role`. The judge sends `customer_id: null` sometimes — that broke v1.
- **Fallback templates are verbose.** Could compress with a template DSL but didn't have time.
- **Spent way too long debugging Render path issues** before realizing the dataset folder wasn't being COPY'd into Docker.

## Production hardening

<img width="1280" height="608" alt="image" src="https://github.com/user-attachments/assets/0536a279-aaac-43b5-b9e6-e2dd8437dce9" />

- Pydantic request validation on all endpoints (400 on bad input, no crashes)
- Async timeouts: 25s on `/tick` and `/reply` (judge spec is 30s — gives buffer for LLM latency)
- LLM client: retry with exponential backoff on HTTP 429/5xx and network errors
- Tick idempotency: same `(now, triggers)` returns cached result
- TTL-based GC: conversations expire after 7d, suppression keys after 3d
- Thread-safe state with reentrant locks
- Structured JSON request logging (req_id, path, status, elapsed_ms)
- Container: non-root user, healthcheck, 2 uvicorn workers
- Graceful degradation: every error path returns valid JSON, never 500s

## Stuff I'd add with more time

- Per-merchant trigger affinity learning (track which triggers each merchant engages with, weight scoring by history)
- Better Hindi-English code-mix tuning (current version sometimes sounds robotic)
- Real metrics endpoint, not just logs
- Distributed store (Redis/Postgres) for multi-instance deploys

## Endpoints

| Endpoint | Method | Notes |
|---|---|---|
| `/v1/healthz` | GET | Returns uptime + context counts + LLM config status |
| `/v1/metadata` | GET | Team identity + approach |
| `/v1/context` | POST | Idempotent by `(scope, context_id, version)`. 409 on stale version. |
| `/v1/tick` | POST | Returns up to 20 ranked actions. Cached by `(now, triggers)`. |
| `/v1/reply` | POST | Returns send/wait/end action. FSM handles intent transitions. |

## Deploy

```bash
docker build -t vera-bot .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... vera-bot
```

Or to Railway/Render: connect this repo, set `ANTHROPIC_API_KEY`, deploy. Public URL ready in ~2 minutes.

## What I wish they'd given us

- Anonymized real Vera ↔ merchant transcripts (would have helped tune the auto-reply phrase library)
- The exact judge LLM and its temperature (to better predict scoring drift)
- A few human-scored "ground-truth" samples per category for calibration

---

Built by [@Divinesoumyadip](https://github.com/Divinesoumyadip) for the magicpin AI Challenge.
