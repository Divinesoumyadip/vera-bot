import re
from datetime import datetime, timezone
from typing import Optional
from context_store import ContextStore
from category import get_category_rules, get_trigger_strategy
from prompts import COMPOSER_SYSTEM, COMPOSER_REPLY_SYSTEM, build_compose_prompt, build_reply_prompt, compute_lead_score, get_gbp_optimization_message, build_review_reply_prompt, REVIEW_REPLY_SYSTEM, get_language_voice, format_for_whatsapp
from llm import call_llm_json

AUTO_REPLY_PHRASES = [
    "thank you for contacting", "thanks for contacting",
    "our team will respond", "we will get back to you", "we will respond shortly",
    "this is an automated", "automated response", "automated reply",
    "automated assistant", "out of office", "i am away", "i'm away",
    "currently unavailable", "auto-reply", "auto reply",
    "aapki jaankari ke liye bahut-bahut shukriya",
    "team tak pahuncha", "shukriya sampark karne ke liye",
]

POSITIVE_INTENT = [
    "yes please", "yes please send", "haan bhejo", "haan kar do",
    "go ahead", "let's do it", "lets do it", "ok do it", "okay do it",
    "please do", "please send", "send it", "do it", "send me",
    "schedule it", "i confirm", "chalega", "kar do", "bhej do", "bhejo",
    "sounds good", "perfect", "ok please", "go for it",
    "what's next", "whats next", "yes book", "please book",
]

NEGATIVE_INTENT = [
    "not interested", "stop messaging", "stop sending", "stop",
    "don't message", "dont message", "don't contact", "dont contact",
    "remove me", "unsubscribe", "leave me alone",
    "stop bothering", "useless spam", "this is useless",
    "mat bhejo", "band karo", "rok do",
]

BOOKING_KEYWORDS = ["book", "schedule", "appointment", "slot", "wed", "thu", "fri", "mon", "tue", "sat", "6pm", "7pm", "morning", "evening"]

OFF_TOPIC_KEYWORDS = [
    "gst filing", "gst return", "income tax", "personal loan",
    "credit card", "stock market", "crypto", "real estate",
]

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())

def is_auto_reply(message: str) -> bool:
    n = normalize(message)
    return any(p in n for p in AUTO_REPLY_PHRASES)

def detect_intent(message: str) -> str:
    if is_auto_reply(message):
        return "auto_reply"
    n = normalize(message)
    if any(p in n for p in NEGATIVE_INTENT):
        return "negative"
    if any(p in n for p in POSITIVE_INTENT):
        return "positive"
    if any(p in n for p in OFF_TOPIC_KEYWORDS):
        return "off_topic"
    if n in ("yes", "haan", "ok", "okay", "sure", "yep", "y"):
        return "positive"
    if n in ("no", "nahi", "nope", "n", "stop"):
        return "negative"
    return "neutral"

def is_booking(message: str) -> bool:
    n = normalize(message)
    return any(k in n for k in BOOKING_KEYWORDS)

def score_trigger(trigger: dict, merchant: dict, category: dict) -> float:
    score = 0.4
    score += (trigger.get("urgency", 3) / 5.0) * 0.25
    trig_cat = trigger.get("payload", {}).get("category")
    merch_cat = merchant.get("category_slug", "")
    if trig_cat == merch_cat:
        score += 0.15
    elif not trig_cat:
        score += 0.05
    signals = merchant.get("signals", [])
    kind = trigger.get("kind", "")
    alignments = {
        "perf_dip": ["ctr_below_peer_median", "stale_posts", "low_engagement"],
        "perf_spike": ["engaged_in_last_48h", "high_growth"],
        "research_digest": ["high_risk_adult_cohort", "engaged_in_last_48h"],
        "regulation_change": ["compliance_due"],
        "dormant_with_vera": ["dormant", "no_recent_activity"],
        "review_theme_emerged": ["review_pending", "rating_dip"],
    }
    if kind in alignments:
        for sig_marker in alignments[kind]:
            if any(sig_marker in s for s in signals):
                score += 0.15
                break
    if kind == "active_planning_intent":
        score += 0.2
    if kind in ("supply_alert", "regulation_change", "appointment_tomorrow", "chronic_refill_due"):
        score += 0.1
    return min(score, 1.0)

def resolve_digest_item(trigger: dict, category: dict) -> Optional[dict]:
    top_item_id = trigger.get("payload", {}).get("top_item_id")
    if not top_item_id:
        return None
    return next((i for i in category.get("digest", []) if i.get("id") == top_item_id), None)

INTERNAL_JARGON = ["suppression_key", "trigger_id", "merchant_id", "context_id", "ack_id"]

def validate_message(body: str, merchant: dict, category: dict) -> tuple[bool, str]:
    if not body or len(body.strip()) < 25:
        return False, "body too short"
    body_lower = body.lower()
    taboos = category.get("voice", {}).get("vocab_taboo", [])
    for t in taboos:
        if t.lower() in body_lower:
            return False, f"taboo word: {t}"
    if re.search(r'https?://', body):
        return False, "URL in body"
    if "i'm vera" in body_lower or "i am vera" in body_lower:
        return False, "re-introduction"
    for j in INTERNAL_JARGON:
        if j in body_lower:
            return False, f"internal jargon: {j}"
    owner = (merchant.get("identity", {}).get("owner_first_name", "") or
             merchant.get("identity", {}).get("name", ""))
    has_number = bool(re.search(r'\d', body))
    first_name = owner.split()[0].lower() if owner else ""
    has_name = first_name in body_lower if first_name else False
    if not has_number and not has_name:
        return False, "no specificity anchor"
    return True, ""

def build_fallback(merchant: dict, trigger: dict, category: dict, customer: Optional[dict]) -> dict:
    identity = merchant.get("identity", {})
    owner = (identity.get("owner_first_name") or identity.get("name", "").split()[0] or "there")
    locality = identity.get("locality", identity.get("city", ""))
    kind = trigger.get("kind", "")
    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]
    perf = merchant.get("performance", {})
    peer_stats = category.get("peer_stats", {})
    seasonal = category.get("seasonal_beats", [])
    customer_agg = merchant.get("customer_aggregate", {})

    if kind == "perf_dip":
        views = perf.get("views", "?")
        delta = perf.get("delta_7d", {}).get("views_pct", 0)
        pct = abs(int(delta * 100)) if isinstance(delta, float) else "?"
        peer_views = peer_stats.get("avg_views_30d", "?")
        body = f"{owner}, your views are down {pct}% this week ({views} vs peer median {peer_views} for {locality} {category.get('slug','')}). Want me to pull a 3-step recovery plan?"
        cta = "binary_yes_no"
    elif kind == "perf_spike":
        views = perf.get("views", "?")
        delta = perf.get("delta_7d", {}).get("views_pct", 0)
        pct = abs(int(delta * 100)) if isinstance(delta, float) else "?"
        offer = active_offers[0] if active_offers else "your active offer"
        body = f"{owner}, views are up {pct}% this week ({views} total). Want me to scale '{offer}' to capture this surge?"
        cta = "binary_yes_no"
    elif kind == "research_digest":
        items = category.get("digest", [])
        item = next((i for i in items if i.get("kind") == "research"), items[0] if items else {})
        title = item.get("title", "a development worth your attention")
        source = item.get("source", "")
        body = f"{owner}, {title}.{(' Source: ' + source) if source else ''} Want me to pull the full summary?"
        cta = "open_ended"
    elif kind == "regulation_change":
        items = category.get("digest", [])
        item = next((i for i in items if i.get("kind") == "compliance"), items[0] if items else {})
        title = item.get("title", "a compliance update for your category")
        source = item.get("source", "")
        deadline = trigger.get("payload", {}).get("deadline_iso", "")
        body = f"{owner}, compliance alert: {title}.{(' Source: ' + source) if source else ''}{(' Deadline: ' + deadline) if deadline else ''} Want me to send the full circular + a checklist?"
        cta = "binary_yes_no"
    elif kind in ("recall_due", "wedding_package_followup", "trial_followup"):
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            offer = active_offers[0] if active_offers else "your scheduled service"
            body = f"Hi {cust_name}, {merch_name} here. Time for your next visit — {offer}. Reply YES to confirm a slot."
        else:
            body = f"{owner}, customer recalls are due. Want me to draft and send reminders?"
        cta = "binary_yes_no"
    elif kind == "chronic_refill_due":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            body = f"Namaste {cust_name}, {merch_name} yahan. Your monthly refill is due. Reply CONFIRM to dispatch."
        else:
            body = f"{owner}, chronic refills are due. Want me to send the reminder list?"
        cta = "binary_confirm"
    elif kind == "appointment_tomorrow":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            body = f"Hi {cust_name}, reminder from {merch_name} — your appointment is tomorrow. Reply CONFIRM to keep the slot."
        else:
            body = f"{owner}, appointments tomorrow. Want me to send the reminder batch?"
        cta = "binary_confirm"
    elif kind in ("customer_lapsed_soft", "customer_lapsed_hard"):
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            offer = active_offers[0] if active_offers else "a fresh start"
            body = f"Hi {cust_name}, {merch_name} here — no judgment, just checking in. {offer} ready when you are. Reply YES — no commitment."
        else:
            lapsed = customer_agg.get("lapsed_180d_plus", "many")
            body = f"{owner}, {lapsed} customers haven't visited in 6+ months. Want me to draft a winback message?"
        cta = "binary_yes_no"
    elif kind == "curious_ask_due":
        body = f"{owner}, quick check — what service has been most asked-for this week at {identity.get('name', 'your business')}? I'll turn it into a Google post + customer reply template. 5 min."
        cta = "open_ended"
    elif kind == "festival_upcoming":
        payload = trigger.get("payload", {})
        festival = payload.get("festival_name", "the festival")
        days = payload.get("days_until", "")
        offer = active_offers[0] if active_offers else "a campaign offer"
        body = f"{owner}, {festival} is {(str(days) + ' days away') if days else 'coming up'}. Want me to draft a campaign around '{offer}'?"
        cta = "binary_yes_no"
    elif kind == "ipl_match_today":
        payload = trigger.get("payload", {})
        match = payload.get("match", "the match tonight")
        offer = active_offers[0] if active_offers else "your active offer"
        body = f"{owner}, {match} tonight. Want me to draft a special around '{offer}'? Live in 10 min."
        cta = "binary_yes_no"
    elif kind == "active_planning_intent":
        payload = trigger.get("payload", {})
        topic = payload.get("topic", "the plan we discussed")
        body = f"{owner}, starter draft for {topic} ready. Want me to send the full version with pricing tiers?"
        cta = "binary_confirm_cancel"
    elif kind == "supply_alert":
        payload = trigger.get("payload", {})
        molecule = payload.get("molecule", "an affected medicine")
        batches = payload.get("batches", [])
        affected = customer_agg.get("chronic_rx_count", "your chronic Rx customers")
        batch_str = ", ".join(batches[:2]) if batches else ""
        body = f"{owner}, urgent: recall on {molecule}{(' batches ' + batch_str) if batch_str else ''}. {affected} customers may be affected. Want me to draft the notification?"
        cta = "binary_yes_no"
    elif kind == "review_theme_emerged":
        themes = merchant.get("review_themes", [])
        if themes:
            t = themes[0]
            body = f"{owner}, '{t.get('theme')}' came up {t.get('occurrences_30d', '?')}× in 30d reviews ({t.get('sentiment')}). Want me to draft a response template?"
        else:
            body = f"{owner}, a review theme is emerging. Want me to surface the pattern?"
        cta = "binary_yes_no"
    elif kind == "milestone_reached":
        payload = trigger.get("payload", {})
        milestone = payload.get("milestone", "a milestone")
        body = f"{owner}, congrats — {milestone}! Want me to draft a celebration post?"
        cta = "binary_yes_no"
    elif kind == "competitor_opened":
        payload = trigger.get("payload", {})
        distance = payload.get("distance_km", "nearby")
        body = f"{owner}, a new {category.get('slug', 'business')} opened {distance}km away in {locality}. Want me to draft a differentiation play?"
        cta = "binary_yes_no"
    elif kind == "renewal_due":
        days = merchant.get("subscription", {}).get("days_remaining", "soon")
        body = f"{owner}, your magicpin Pro renews in {days} days. Value recap ready. Want to see it?"
        cta = "binary_yes_no"
    elif kind == "dormant_with_vera":
        body = f"{owner}, haven't heard from you in a while. What's the #1 thing you'd want help with this week?"
        cta = "open_ended"
    elif kind == "category_seasonal":
        beat = seasonal[0] if seasonal else {}
        note = beat.get("note", "a seasonal demand pattern")
        body = f"{owner}, {note}. Want me to prep a campaign before the peak?"
        cta = "binary_yes_no"
    elif kind == "gbp_unverified":
        body = f"{owner}, your Google Business Profile is unverified — caps your local reach. 5-min fix. Want me to walk you through it?"
        cta = "binary_yes_no"
    elif kind == "cde_opportunity":
        items = category.get("digest", [])
        item = next((i for i in items if "webinar" in (i.get("title", "").lower())), items[0] if items else {})
        title = item.get("title", "a relevant CDE opportunity")
        body = f"{owner}, {title}. Aapke practice ke liye relevant. Want me to send the details?"
        cta = "binary_yes_no"
    elif kind == "winback_eligible":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            offer = active_offers[0] if active_offers else "a welcome-back offer"
            body = f"Hi {cust_name}, {merch_name} here — been a while! {offer} ready if you want to try again. Reply YES — no commitment."
        else:
            body = f"{owner}, winback-eligible customers waiting. Want me to draft a re-engagement?"
        cta = "binary_yes_no"
    else:
        if active_offers:
            body = f"{owner}, your '{active_offers[0]}' is doing the work — want me to draft a peer-comparison post in {locality}?"
        else:
            body = f"{owner}, your {locality} profile has new signals. Want me to walk you through them?"
        cta = "open_ended"

    return {"body": body, "cta": cta, "rationale": f"Deterministic fallback for trigger kind '{kind}'."}

def _compose_action(trigger, merchant, category, customer, merchant_id, customer_id):
    kind = trigger.get("kind", "")
    cat_rules = get_category_rules(category.get("slug", "restaurants"))
    strategy = get_trigger_strategy(kind)
    send_as = strategy.get("send_as", cat_rules.get("send_as_default", "vera"))
    if customer:
        send_as = "merchant_on_behalf"

    digest_item = None
    if kind in ("research_digest", "regulation_change", "cde_opportunity"):
        digest_item = resolve_digest_item(trigger, category)

    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    conv_id = f"conv_{customer_id or merchant_id}_{kind}_{date_part}"

    body = cta = rationale = None
    try:
        prompt = build_compose_prompt(category, merchant, trigger, customer, strategy, cat_rules, digest_item)
        result = call_llm_json(COMPOSER_SYSTEM, prompt, max_tokens=700)
        body = result.get("body", "")
        cta = result.get("cta", "open_ended")
        rationale = result.get("rationale", "")
    except Exception as e:
        fb = build_fallback(merchant, trigger, category, customer)
        body, cta, rationale = fb["body"], fb["cta"], fb["rationale"] + f" (LLM unavailable: {str(e)[:60]})"

    valid, reason = validate_message(body, merchant, category)
    if not valid:
        fb = build_fallback(merchant, trigger, category, customer)
        body, cta, rationale = fb["body"], fb["cta"], fb["rationale"] + f" (validation: {reason})"

    identity = merchant.get("identity", {})
    name_part = identity.get("owner_first_name") or identity.get("name", "")
    supp_key = trigger.get("suppression_key", f"{merchant_id}:{kind}:{date_part}")

    gbp_hint = None
    if kind in ("gbp_unverified", "review_theme_emerged", "dormant_with_vera"):
        try:
            gbp_opt = get_gbp_optimization_message(merchant, category)
            gbp_hint = gbp_opt.get("body", "")
        except Exception:
            pass

    review_reply_draft = None
    if kind == "review_theme_emerged":
        try:
            themes = merchant.get("review_themes", [])
            if themes:
                review = {"reviewer_name": "a recent customer",
                         "rating": 4, "text": themes[0].get("theme", "")}
                rr = call_llm_json(REVIEW_REPLY_SYSTEM,
                                   build_review_reply_prompt(review, merchant, category),
                                   max_tokens=200)
                review_reply_draft = rr.get("reply_text", "")
        except Exception:
            pass

    body = format_for_whatsapp(body, cta)
    result = {
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "send_as": send_as,
        "trigger_id": trigger.get("id", ""),
        "template_name": f"vera_{kind}_v1",
        "template_params": [name_part, body[:120], cta],
        "body": body,
        "cta": cta,
        "suppression_key": supp_key,
        "rationale": rationale,
    }
    if gbp_hint:
        result["gbp_optimization"] = gbp_hint
    if review_reply_draft:
        result["review_reply_draft"] = review_reply_draft
    return result

def compose_tick(store: ContextStore, available_triggers: list, now: str) -> list:
    if not available_triggers:
        all_triggers = store.all_of("trigger")
        candidates = []
        for tid, t in all_triggers.items():
            supp_key = t.get("suppression_key", tid)
            if store.is_suppressed(supp_key):
                continue
            urgency = t.get("urgency", 3)
            candidates.append((urgency, tid))
        candidates.sort(key=lambda x: -x[0])
        available_triggers = [tid for _, tid in candidates[:20]]

    scored = []
    for trg_id in available_triggers:
        trigger = store.get("trigger", trg_id)
        if not trigger:
            continue
        supp_key = trigger.get("suppression_key", trg_id)
        if store.is_suppressed(supp_key):
            continue
        merchant_id = trigger.get("merchant_id") or trigger.get("payload", {}).get("merchant_id")
        if not merchant_id:
            continue
        merchant, category = store.get_merchant_with_category(merchant_id)
        if not merchant or not category:
            continue
        scored.append((score_trigger(trigger, merchant, category), trg_id, trigger, merchant, category))

    scored.sort(key=lambda x: -x[0])
    actions = []
    for sc, trg_id, trigger, merchant, category in scored[:20]:
        if sc < 0.3:
            continue
        merchant_id = trigger.get("merchant_id") or trigger.get("payload", {}).get("merchant_id")
        customer_id = trigger.get("customer_id") or trigger.get("payload", {}).get("customer_id")
        customer = store.get("customer", customer_id) if customer_id else None
        action = _compose_action(trigger, merchant, category, customer, merchant_id, customer_id)
        if action:
            actions.append(action)
            store.add_suppression(trigger.get("suppression_key", trg_id))
    return actions

def compose_reply(store: ContextStore, conversation_id, merchant_id, customer_id,
                  from_role, message, received_at, turn_number) -> dict:

    if store.is_conversation_suppressed(conversation_id):
        return {"action": "end", "rationale": "Conversation suppressed."}

    store.append_turn(conversation_id, from_role, message)
    intent = detect_intent(message)

    if intent == "auto_reply":
        merchant_auto_count = store.bump_merchant_auto_count(merchant_id)
        if merchant_auto_count >= 3:
            store.suppress_conversation(conversation_id)
            return {"action": "end", "rationale": f"Auto-reply {merchant_auto_count}x. Closing."}
        if merchant_auto_count == 2:
            return {"action": "wait", "wait_seconds": 86400, "rationale": "Auto-reply 2x. Waiting 24h."}
        return {"action": "wait", "wait_seconds": 14400, "rationale": "Auto-reply detected. Backing off 4h."}

    if intent == "negative":
        store.suppress_conversation(conversation_id)
        merchant, _ = store.get_merchant_with_category(merchant_id) if merchant_id else (None, None)
        is_hindi = merchant and "hi" in merchant.get("identity", {}).get("languages", [])
        body = ("Sorry for the bother. Main aur messages nahi bhejongi. 🙏" if is_hindi
                else "Sorry for the bother — I won't message again. 🙏")
        return {"action": "end", "body": body, "cta": "none",
                "rationale": "Hostile/STOP. Graceful exit. Suppressed."}

    merchant, category = store.get_merchant_with_category(merchant_id) if merchant_id else (None, None)
    customer = store.get("customer", customer_id) if customer_id else None
    if not merchant: merchant = {}
    if not category: category = {}

    if from_role == "customer" or (customer is not None and from_role != "merchant"):
        cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
        merch_name = merchant.get("identity", {}).get("name", "us") if merchant else "us"
        active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"] if merchant else []
        voice = get_language_voice(merchant) if merchant else {"greeting": "Hi", "code": "en"}
        greeting = voice.get("greeting", "Hi") if cust_name and cust_name != "there" else "Hi"
        lead = compute_lead_score(message, turn_number, [])

        if intent == "negative":
            return {"action": "end", "body": f"No problem {cust_name} — won't bother you again. 🙏",
                    "cta": "none", "rationale": "Customer opt-out."}

        if is_booking(message) or intent == "positive":
            slot_match = re.search(r"(mon|tue|wed|thu|fri|sat|sun)\w*\s*\d{0,2}[a-z]*\s*(?:nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct)?\s*,?\s*\d{0,2}:?\d{0,2}\s*(?:am|pm)?", message.lower())
            slot = slot_match.group(0).strip().title() if slot_match else ""
            if slot:
                body = f"{greeting} {cust_name}, confirmed at {merch_name} for {slot}.\n\nWe'll send a reminder the day before.\n\nReply CONFIRM to lock the slot."
            else:
                offer = active_offers[0] if active_offers else "your visit"
                body = f"{greeting} {cust_name}, noted — {merch_name} will confirm your slot shortly.\n\nReply CONFIRM to lock it in."
            return {"action": "send", "body": body, "cta": "binary_confirm",
                    "lead_score": lead,
                    "language": voice.get("code", "en"),
                    "rationale": f"Customer booking. Lead: {lead['label']} ({lead['score']}/100). Lang: {voice.get('code', 'en')}"}

        body = f"{greeting} {cust_name}, got it — {merch_name} will follow up shortly.\n\nReply YES if you need anything else."
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "lead_score": lead,
                "language": voice.get("code", "en"),
                "rationale": f"Customer neutral. Lead: {lead['label']}. Lang: {voice.get('code', 'en')}"}

    conv = store.get_conversation(conversation_id) or {}
    history = conv.get("history", [])
    trigger_kind = conv.get("trigger_kind", "general")
    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]
    owner = merchant.get("identity", {}).get("owner_first_name", "")

    if intent == "positive":
        if trigger_kind == "active_planning_intent":
            body = "Drafting it now — full version with tiers + outreach template in 60 seconds. Reply CONFIRM to proceed."
        elif trigger_kind == "research_digest":
            body = "Sending the abstract now — also drafting a patient-ed WhatsApp. Reply CONFIRM to schedule Google post for tomorrow 10am."
        elif trigger_kind == "festival_upcoming":
            offer = active_offers[0] if active_offers else "your campaign"
            body = f"Drafting the {offer} campaign — full post + WhatsApp template in 90 seconds. Reply CONFIRM to launch."
        elif trigger_kind in ("perf_dip", "perf_spike"):
            body = "Pulling your full diagnostic — 3 actions ranked by impact, here in 2 minutes. Reply CONFIRM to receive the playbook."
        else:
            owner_str = f"{owner}, " if owner else ""
            body = f"{owner_str}done — drafting now. Full version with one-tap actions in 60 seconds. Reply CONFIRM to proceed."
        return {"action": "send", "body": body, "cta": "binary_confirm_cancel",
                "rationale": f"Positive commitment on {trigger_kind}. Action mode. No re-qualification."}

    if intent == "off_topic":
        body = f"That's outside what I can help with{', ' + owner if owner else ''}. Coming back — want me to take the next step on what we discussed?"
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Off-topic redirected."}

    try:
        prompt = build_reply_prompt(history, message, merchant, category, trigger_kind, turn_number)
        result = call_llm_json(COMPOSER_REPLY_SYSTEM, prompt, max_tokens=400)
        if result.get("action") == "end":
            store.suppress_conversation(conversation_id)
        return result
    except Exception as e:
        owner_str = f", {owner}" if owner else ""
        return {"action": "send",
                "body": f"Got it{owner_str}! Reply CONFIRM to proceed.",
                "cta": "binary_confirm_cancel",
                "rationale": f"LLM error fallback: {str(e)[:60]}"}
