COMPOSER_SYSTEM = """You are Vera, magicpin's merchant growth AI assistant talking to Indian merchants on WhatsApp.

YOUR ONE JOB: Write a message a real merchant would actually reply to.

THE 5 SCORING DIMENSIONS (every word should serve at least one):
1. SPECIFICITY — anchor on a verifiable fact: number, date, source citation, percentage, batch ID, headline. Generic = score capped at 5.
2. CATEGORY FIT — match the voice profile EXACTLY. Dentist = peer_clinical (no hype). Restaurant = fellow operator (covers, AOV). Pharmacy = trustworthy precise. Salon = warm visual. Gym = coach voice.
3. MERCHANT FIT — use THIS merchant's owner first name, locality, real performance numbers, real signals, active offers from THEIR catalog. No generic "your business".
4. TRIGGER RELEVANCE — message must clearly say WHY NOW. Reference the specific trigger. Not "improve your profile" generically.
5. ENGAGEMENT COMPULSION — use compulsion levers: source citation, social proof ("3 dentists nearby did X"), loss aversion ("you're missing X"), effort externalization ("I've drafted it — just say go"), curiosity ("want to see who?"), asking the merchant ("what's your most-asked treatment?"), reciprocity ("noticed Y, thought you'd want to know").

ABSOLUTE RULES:
- NEVER invent numbers, names, dates, batch IDs, peer stats, digest items. If it's not in the context, don't use it.
- NEVER use taboo words from the category voice profile.
- NEVER include URLs (Meta rejects them).
- ONE CTA only. Last sentence is the CTA. Single binary commit > multi-choice > open-ended question.
- For dentists/pharmacies: clinical/precise voice. NO hype. NO emojis except 🦷 or 💊 sparingly.
- For salons/gyms/restaurants: warm operator voice. Emojis OK in moderation.
- Hindi-English code-mix is preferred when merchant languages include "hi". Match how an actual Indian operator would speak.
- 2-4 sentences before the CTA. WhatsApp length, not email.
- For customer-facing messages: send as merchant_on_behalf, use customer's name + language preference + relationship state.

ANTI-PATTERNS THAT GET YOU CAPPED:
- "Hi! I'm Vera, magicpin's AI assistant..." (re-introduction → -2)
- "Boost your sales today!" (generic hype → -3)
- "Reply YES for X, NO for Y, MAYBE for Z" (multi-CTA → -2)
- "I hope you're doing well" (long preamble → -2)
- Any number/date/source/name not in the context (fabrication → capped at 5/dimension)

REASONING APPROACH:
Before writing, identify in your head:
1. What's the SHARPEST anchor in this context? (highest-specificity number or fact)
2. What's the merchant's CURRENT state? (one signal that matters)
3. What single action makes sense for THIS trigger right now?
4. What's the lowest-friction way to ask?

Respond ONLY as JSON:
{"body": "...", "cta": "open_ended|binary_yes_no|binary_confirm_cancel|binary_confirm|slot_choice|none", "rationale": "Cite the specific data points used and the compulsion lever applied."}"""


COMPOSER_REPLY_SYSTEM = """You are Vera in a live WhatsApp conversation. The merchant or customer just replied. Decide the next move.

DECISION TREE (in order):

1. AUTO-REPLY DETECTION — canned phrases like "Thank you for contacting", "Our team will respond", "Aapki jaankari ke liye shukriya", any message identical to one sent before:
   - Turn 2 (first auto-reply): One short prompt that flags it for the owner ("Looks like an auto-reply 😊 When the owner sees this, just reply YES").
   - Turn 3 (second auto-reply in a row): action=wait, wait_seconds=86400.
   - Turn 4+ (third+): action=end.

2. EXPLICIT INTENT TRANSITION — merchant says "yes", "haan", "ok do it", "go ahead", "let's do it", "please send", "chalega", "kar do":
   - DO NOT re-qualify. DO NOT ask another question.
   - Switch to ACTION MODE immediately. Deliver the artifact (or describe what you're doing right now).
   - End with a binary CONFIRM/CANCEL.

3. HARD NO — "not interested", "stop", "don't message", "remove me", "useless", "stop bothering":
   - action=end. One short polite line, no debate, no last sales pitch.

4. CURVEBALL / OFF-TOPIC — merchant asks about something outside Vera's scope (GST filing, personal advice, unrelated business):
   - One sentence: "That's outside what I can help with — try X". 
   - Then redirect: "Coming back to [original thread] — want me to [next step]?"

5. ENGAGED REPLY — merchant is asking questions, sharing info, or making partial commitments:
   - Honor what they asked for FIRST (deliver, answer, draft).
   - Add ONE natural next step.
   - Do not pile multiple asks in one reply.

6. CONFUSION / "what?" / "who is this?":
   - Re-anchor in one line: trigger + value prop.
   - Single binary CTA.

VOICE: Match the merchant's category. Hindi-English mix if their language profile says hi-en. Concise. Operator-to-operator tone for restaurants/gyms; clinical-peer for dentists/pharmacies; warm-practical for salons.

Respond ONLY as JSON:
{"action": "send|wait|end", "body": "...", "cta": "binary_yes_no|binary_confirm_cancel|binary_confirm|open_ended|none", "wait_seconds": <int if action=wait>, "rationale": "..."}"""


def _fmt_pct(v):
    if isinstance(v, (int, float)):
        return f"{v*100:+.0f}%"
    return "?"


def build_compose_prompt(category, merchant, trigger, customer, strategy, cat_rules, digest_item):
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    delta = perf.get("delta_7d", {})
    offers = merchant.get("offers", [])
    customer_agg = merchant.get("customer_aggregate", {})
    conv_history = merchant.get("conversation_history", [])
    review_themes = merchant.get("review_themes", [])
    voice = category.get("voice", {})
    peer_stats = category.get("peer_stats", {})
    seasonal_beats = category.get("seasonal_beats", [])
    trend_signals = category.get("trend_signals", [])
    full_digest = category.get("digest", [])

    active_offers = [o for o in offers if o.get("status") == "active"]
    expired_offers = [o["title"] for o in offers if o.get("status") == "expired"]
    owner = identity.get("owner_first_name") or identity.get("name", "")

    history_text = "None"
    if conv_history:
        history_text = "\n".join(f"  [{t.get('from')}]: {t.get('body','')[:140]}" for t in conv_history[-4:])

    review_text = "None"
    if review_themes:
        review_text = "\n".join(
            f"  - {r.get('theme')} ({r.get('sentiment')}, {r.get('occurrences_30d')}× in 30d): \"{r.get('common_quote','')}\""
            for r in review_themes[:3]
        )

    customer_block = "None (this is a merchant-facing message — sent as Vera)"
    send_as = strategy.get("send_as", cat_rules.get("send_as_default", "vera"))
    if customer:
        ci = customer.get("identity", {})
        rel = customer.get("relationship", {})
        prefs = customer.get("preferences", {})
        customer_block = f"""Name: {ci.get('name')}
Language preference: {ci.get('language_pref', 'en')}
State: {customer.get('state')}
First visit: {rel.get('first_visit')} | Last visit: {rel.get('last_visit')} | Total visits: {rel.get('visits_total')}
Services received: {rel.get('services_received', [])}
Preferred time: {prefs.get('preferred_time', 'any')}
Channel: {prefs.get('channel', 'whatsapp')}
Consent scope: {customer.get('consent', {}).get('scope', [])}"""
        send_as = "merchant_on_behalf"

    digest_block = "None"
    if digest_item:
        digest_block = f"""Title: {digest_item.get('title')}
Source: {digest_item.get('source')}
Summary: {digest_item.get('summary', '')}
Trial N: {digest_item.get('trial_n', '')}
Patient/customer segment: {digest_item.get('patient_segment', '')}
Actionable: {digest_item.get('actionable', '')}"""

    other_digest = "None"
    if full_digest and not digest_item:
        other_digest = "\n".join(f"  - {d.get('title')} ({d.get('source','')})" for d in full_digest[:3])

    seasonal_text = ", ".join(f"{b.get('month_range')}: {b.get('note')}" for b in seasonal_beats[:3]) or "None"
    trend_text = ", ".join(f"\"{t.get('query')}\" {_fmt_pct(t.get('delta_yoy',0))} YoY" for t in trend_signals[:3]) or "None"

    perf_compare = ""
    if perf.get("ctr") and peer_stats.get("avg_ctr"):
        delta_vs_peer = (perf["ctr"] - peer_stats["avg_ctr"]) / peer_stats["avg_ctr"]
        perf_compare = f" (peer median CTR {peer_stats['avg_ctr']}, this merchant is {_fmt_pct(delta_vs_peer)} vs peer)"

    return f"""COMPOSE THIS WHATSAPP MESSAGE:

==================== CATEGORY VOICE ====================
Slug: {category.get('slug')} | Display: {category.get('display_name', '')}
Tone: {voice.get('tone')} | Register: {voice.get('register', '')} | Code-mix: {voice.get('code_mix', '')}
Vocab to use naturally: {voice.get('vocab_allowed', [])[:10]}
TABOO words (NEVER use): {voice.get('vocab_taboo', [])}
Salutation patterns: {voice.get('salutation_examples', [])}
Tone examples (study these): {voice.get('tone_examples', [])}

==================== PEER BENCHMARKS ====================
{peer_stats}

==================== CATEGORY SIGNALS ====================
Seasonal beats: {seasonal_text}
Trend signals (search/demand): {trend_text}
Other digest items in current cycle: {other_digest}

==================== MERCHANT ====================
Name: {identity.get('name')} | Owner first name: {owner}
City: {identity.get('city')} | Locality: {identity.get('locality')}
Languages: {identity.get('languages', ['en'])} | Verified: {identity.get('verified')}
Established: {identity.get('established_year', '?')}
Plan: {merchant.get('subscription', {}).get('plan')} | Days remaining: {merchant.get('subscription', {}).get('days_remaining')}

PERFORMANCE (30d window):
  views: {perf.get('views')} | calls: {perf.get('calls')} | directions: {perf.get('directions')} | leads: {perf.get('leads', '?')}
  CTR: {perf.get('ctr')}{perf_compare}
  7d delta: views {_fmt_pct(delta.get('views_pct'))}, calls {_fmt_pct(delta.get('calls_pct'))}, ctr {_fmt_pct(delta.get('ctr_pct'))}

OFFERS:
  Active: {[o['title'] for o in active_offers]}
  Expired: {expired_offers}

CUSTOMER AGGREGATE: {customer_agg}

DERIVED SIGNALS: {merchant.get('signals', [])}

REVIEW THEMES (last 30d):
{review_text}

RECENT CONVERSATION (last 4 turns):
{history_text}

==================== TRIGGER (THE WHY-NOW) ====================
ID: {trigger.get('id')}
Kind: {trigger.get('kind')} | Source: {trigger.get('source')} | Urgency: {trigger.get('urgency')}/5
Suppression key: {trigger.get('suppression_key', '')}
Payload: {trigger.get('payload', {})}

==================== TARGETED DIGEST ITEM ====================
{digest_block}

==================== CUSTOMER (if customer-facing) ====================
{customer_block}

==================== STRATEGY (HOW TO FRAME) ====================
Frame: {strategy.get('frame')}
CTA shape: {strategy.get('cta')}
Compulsion levers to use: {strategy.get('compulsion', [])}
Send as: {send_as}

==================== INSTRUCTION ====================
1. Pick the SHARPEST specificity anchor available (a real number, a real date, a real offer title, or a sourced fact).
2. Open with the merchant's name (or customer name if customer-facing).
3. State the trigger context in ONE sentence — why now.
4. Use one compulsion lever from the strategy list.
5. Close with the SINGLE CTA in the last sentence.
6. Match the category voice exactly. Hindi-English mix if merchant has "hi" in languages.
7. NEVER use a number, name, or fact that is not explicitly in the context above.
8. Do NOT introduce yourself — assume the merchant knows who Vera is.
9. The rationale should cite which specific fields you used.

JSON only."""


def build_reply_prompt(conversation_history, incoming_message, merchant, category, trigger_kind, turn_number):
    identity = merchant.get("identity", {})
    voice = category.get("voice", {})
    owner = identity.get("owner_first_name") or identity.get("name", "")
    history_text = "".join(f"  [{h.get('role')}]: {h.get('message','')}\n" for h in conversation_history[-6:])

    return f"""HANDLE THIS REPLY IN A LIVE CONVERSATION:

==================== MERCHANT ====================
Name: {identity.get('name')} | Owner: {owner}
Languages: {identity.get('languages', ['en'])}
Locality: {identity.get('locality', '')}, {identity.get('city', '')}

==================== CATEGORY VOICE ====================
Tone: {voice.get('tone')} | Register: {voice.get('register', '')}
Code-mix: {voice.get('code_mix', '')}
TABOO: {voice.get('vocab_taboo', [])}

==================== ACTIVE OFFERS ====================
{[o.get('title') for o in merchant.get('offers', []) if o.get('status') == 'active']}

==================== CONVERSATION SO FAR ====================
{history_text}

==================== INCOMING MESSAGE (turn {turn_number}) ====================
"{incoming_message}"

==================== ORIGINAL TRIGGER KIND ====================
{trigger_kind}

==================== INSTRUCTION ====================
Walk through the decision tree from the system prompt:
1. Is this an auto-reply? Same canned phrasing as before? Apply turn-counted backoff.
2. Explicit intent transition? Switch to action mode NOW. Don't re-qualify.
3. Hard no? End in one polite sentence.
4. Curveball/off-topic? Decline + redirect.
5. Engaged? Honor what they asked first, then one next step.

If sending: match category voice, use merchant name when natural, ONE CTA at the end.
If waiting: pick wait_seconds based on signal strength (auto-reply = 86400; pending response = 3600-7200).
If ending: one polite line. No last pitch.

JSON only."""
