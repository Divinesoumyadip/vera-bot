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

REVIEW_REPLY_SYSTEM = """You are Vera, generating a Google review reply on behalf of an Indian merchant.

RULES:
- Address the reviewer by name if visible, otherwise "Hi"
- Thank them specifically for what they mentioned
- Address any negative point directly and professionally
- End with an invitation to return
- Max 3 sentences
- Match category voice: dentist=clinical, restaurant=warm, salon=friendly, gym=motivational, pharmacy=trustworthy
- Hindi-English mix OK if merchant prefers Hindi
- NEVER mention Vera or magicpin
- Sound like the business owner wrote it personally

Respond ONLY as JSON:
{"reply_text": "...", "sentiment_handled": "positive|negative|neutral", "rationale": "..."}"""

def build_review_reply_prompt(review: dict, merchant: dict, category: dict) -> str:
    reviewer = review.get("reviewer_name", "the customer")
    rating = review.get("rating", 5)
    text = review.get("text", "")
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    biz_name = merchant.get("identity", {}).get("name", "")
    locality = merchant.get("identity", {}).get("locality", "")

    return f"""Generate a Google review reply for this merchant:

Business: {biz_name} ({locality})
Owner: {owner}
Category: {category.get('slug', 'restaurant')}
Review Rating: {rating}/5
Reviewer: {reviewer}
Review Text: "{text}"

Write a personal, warm reply that sounds like {owner or 'the owner'} wrote it."""

GBP_SIGNALS = {
    "no_description": {
        "message": "No business description — missing out on 40% more profile views",
        "action": "Want me to write a 150-word SEO description right now? Takes 60 seconds."
    },
    "no_photos": {
        "message": "No photos on your Google profile — customers skip listings without images",
        "action": "Send me any photo on WhatsApp and I'll enhance + post it with an SEO caption."
    },
    "low_reply_rate": {
        "message": "5+ unanswered reviews — hurts your ranking by ~15%",
        "action": "Want me to draft replies to all of them right now?"
    },
    "unverified_gbp": {
        "message": "Google Business Profile unverified — you're invisible in Maps for nearby searches",
        "action": "5-min fix. Want me to walk you through it?"
    },
    "missing_hours": {
        "message": "Business hours missing — customers can't tell if you're open",
        "action": "Want me to update your hours on Google?"
    },
    "no_offers": {
        "message": "No active offers on your profile — competitors with offers get 2x more clicks",
        "action": "Want me to create a Google offer from your existing menu/services?"
    }
}

def get_gbp_optimization_message(merchant: dict, category: dict) -> dict:
    """Generate a profile optimization message based on merchant signals."""
    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", "") or identity.get("name", "").split()[0]
    signals = merchant.get("signals", [])
    offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    reviews = merchant.get("reviews", [])
    unanswered = [r for r in reviews if not r.get("reply")]

    if "gbp_incomplete" in str(signals) or "unverified" in str(signals):
        signal = GBP_SIGNALS["unverified_gbp"]
    elif not identity.get("description"):
        signal = GBP_SIGNALS["no_description"]
    elif len(unanswered) >= 3:
        signal = GBP_SIGNALS["low_reply_rate"]
    elif not offers:
        signal = GBP_SIGNALS["no_offers"]
    else:
        signal = GBP_SIGNALS["no_photos"]

    body = f"{owner}, {signal['message']}. {signal['action']}"
    return {
        "body": body,
        "cta": "binary_yes_no",
        "rationale": f"GBP optimization signal detected. {signal['message']}"
    }

def compute_lead_score(message: str, turn_number: int, history: list) -> dict:
    """Score a customer message for lead qualification."""
    msg_lower = message.lower()

    booking_signals = ["book", "appointment", "slot", "when", "available", "schedule", "reserve"]
    pricing_signals = ["price", "cost", "how much", "rate", "charges", "fees", "kitna"]
    intent_signals = ["interested", "want", "need", "looking for", "please", "yes", "confirm"]
    time_signals = ["today", "tomorrow", "this week", "monday", "tuesday", "wednesday", "thursday", "friday"]

    booking_score = sum(1 for s in booking_signals if s in msg_lower) * 25
    pricing_score = sum(1 for s in pricing_signals if s in msg_lower) * 20
    intent_score = sum(1 for s in intent_signals if s in msg_lower) * 15
    time_score = sum(1 for s in time_signals if s in msg_lower) * 20
    turn_score = min(turn_number * 10, 30)

    total = min(booking_score + pricing_score + intent_score + time_score + turn_score, 100)

    if total >= 70:
        stage = "high_intent"
        label = "Hot Lead"
    elif total >= 40:
        stage = "qualified"
        label = "Warm Lead"
    elif total >= 20:
        stage = "interested"
        label = "Interested"
    else:
        stage = "cold"
        label = "Cold"

    return {
        "score": total,
        "stage": stage,
        "label": label,
        "signals_detected": {
            "booking": booking_score > 0,
            "pricing": pricing_score > 0,
            "intent": intent_score > 0,
            "time_preference": time_score > 0
        }
    }

LANGUAGE_VOICES = {
    "hi": {
        "greeting": "Namaste",
        "yes_word": "haan",
        "thanks": "shukriya",
        "code_mix_phrases": ["aapke", "kar do", "bhej do", "chalega", "bilkul"],
        "voice_note": "Hindi-English code-mix. Use 'aap' (formal) for owners, devanagari OK if natural."
    },
    "ta": {
        "greeting": "Vanakkam",
        "yes_word": "aamaa",
        "thanks": "nandri",
        "code_mix_phrases": ["ungaluku", "panrom", "seyalaam", "irukku", "vendiyathu"],
        "voice_note": "Tamil-English mix. Use 'neenga' (formal) for owners. Tanglish (Tamil written in English) is standard for WhatsApp."
    },
    "te": {
        "greeting": "Namaskaram",
        "yes_word": "avunu",
        "thanks": "dhanyavadalu",
        "code_mix_phrases": ["meeku", "cheddam", "untundi", "kavali", "chesthunnam"],
        "voice_note": "Telugu-English mix. Use 'meeru' (formal). Tenglish is normal for WhatsApp."
    },
    "kn": {
        "greeting": "Namaskara",
        "yes_word": "howdu",
        "thanks": "dhanyavadagalu",
        "code_mix_phrases": ["nimage", "madona", "ide", "beku", "agatte"],
        "voice_note": "Kannada-English mix. Use 'neevu' (formal). Kanglish for WhatsApp."
    },
    "mr": {
        "greeting": "Namaskar",
        "yes_word": "ho",
        "thanks": "dhanyavad",
        "code_mix_phrases": ["tumhala", "karuya", "ahe", "havya", "karto"],
        "voice_note": "Marathi-English mix. Use 'tumhi' (formal). Marathi-English is standard."
    },
    "ml": {
        "greeting": "Namaskaram",
        "yes_word": "athe",
        "thanks": "nanni",
        "code_mix_phrases": ["ningalkku", "cheyyam", "undu", "venam", "cheyunnu"],
        "voice_note": "Malayalam-English mix. Use 'ningal' (formal)."
    },
    "bn": {
        "greeting": "Namaskar",
        "yes_word": "ha",
        "thanks": "dhonnobad",
        "code_mix_phrases": ["apnar", "kore debo", "ache", "lagbe", "korchi"],
        "voice_note": "Bengali-English mix. Use 'apni' (formal). Banglish for WhatsApp."
    },
    "gu": {
        "greeting": "Namaste",
        "yes_word": "haa",
        "thanks": "aabhar",
        "code_mix_phrases": ["tamne", "karishu", "che", "joiye", "karu chu"],
        "voice_note": "Gujarati-English mix. Use 'tame' (formal)."
    },
    "pa": {
        "greeting": "Sat Sri Akal",
        "yes_word": "haanji",
        "thanks": "shukriya",
        "code_mix_phrases": ["tuhanu", "kar diyange", "hai", "chahida", "karde haan"],
        "voice_note": "Punjabi-English mix. Use 'tusi' (formal). Romanized Punjabi for WhatsApp."
    },
    "or": {
        "greeting": "Namaskar",
        "yes_word": "han",
        "thanks": "dhanyabad",
        "code_mix_phrases": ["apananku", "karibu", "achi", "darkar", "karuchu"],
        "voice_note": "Odia-English mix. Use 'apana' (formal)."
    },
    "en": {
        "greeting": "Hi",
        "yes_word": "yes",
        "thanks": "thanks",
        "code_mix_phrases": [],
        "voice_note": "Pure English. Casual professional tone for WhatsApp."
    }
}

def get_language_voice(merchant: dict) -> dict:
    """Pick the dominant language voice for this merchant."""
    languages = merchant.get("identity", {}).get("languages", [])
    priority = ["ta", "te", "kn", "mr", "ml", "bn", "gu", "pa", "or", "hi", "en"]
    for lang in priority:
        if lang in languages:
            return {**LANGUAGE_VOICES[lang], "code": lang}
    return {**LANGUAGE_VOICES["en"], "code": "en"}

def format_for_whatsapp(body: str, cta: str = "") -> str:
    """Format message in WhatsApp-native style: short paragraphs, line breaks."""
    if not body:
        return body

    parts = body.split(" — ")
    if len(parts) >= 2:
        hook = parts[0].strip()
        rest = " — ".join(parts[1:]).strip()
        import re
        cta_match = re.search(r'(Reply [A-Z]+|Want me to [^?]+\?|.+\?)$', rest)
        if cta_match:
            cta_text = cta_match.group(0)
            detail = rest[:cta_match.start()].strip().rstrip('.')
            if detail:
                return f"{hook}.\n\n{detail}.\n\n{cta_text}"
            return f"{hook}.\n\n{cta_text}"
        return f"{hook}.\n\n{rest}"

    if len(body) > 120:
        sentences = body.split('. ')
        if len(sentences) >= 3:
            return f"{sentences[0]}.\n\n{'. '.join(sentences[1:])}"

    return body
