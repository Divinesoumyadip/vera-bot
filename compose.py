import re
from datetime import datetime, timezone
from typing import Optional
from context_store import ContextStore
from category import get_category_rules, get_trigger_strategy
from prompts import COMPOSER_SYSTEM, COMPOSER_REPLY_SYSTEM, build_compose_prompt, build_reply_prompt
from llm import call_llm_json


AUTO_REPLY_PHRASES = [
    "thank you for contacting", "thanks for contacting",
    "our team will respond", "we will get back to you", "we will respond shortly",
    "this is an automated", "automated response", "automated reply",
    "automated assistant", "out of office", "i am away", "i'm away",
    "currently unavailable", "auto-reply", "auto reply",
    "aapki jaankari ke liye bahut-bahut shukriya",
    "main aapki yeh sabhi baatein", "team tak pahuncha",
    "shukriya sampark karne ke liye",
]

POSITIVE_INTENT = [
    "yes please", "yes please send", "haan bhejo", "haan kar do",
    "go ahead", "let's do it", "lets do it", "let us do it",
    "ok do it", "okay do it", "ok lets do", "ok let's do",
    "please do", "please send", "send it", "do it",
    "send the abstract", "draft it", "draft the", "send me",
    "schedule it", "i confirm", "confirm karo",
    "chalega", "kar do", "bhej do", "bhejo",
    "sounds good", "sounds great", "perfect", "looks good",
    "ok please", "okay please", "go for it",
    "what's next", "whats next", "what next",
]

NEGATIVE_INTENT = [
    "not interested", "stop messaging", "stop sending",
    "don't message", "dont message", "don't contact", "dont contact",
    "remove me", "unsubscribe", "leave me alone",
    "stop bothering", "useless spam", "spam",
    "this is useless", "why are you bothering", "block this",
    "mat bhejo", "band karo", "rok do",
]

OFF_TOPIC_KEYWORDS = [
    "gst filing", "gst return", "income tax", "personal loan",
    "credit card", "stock market", "crypto", "real estate",
]


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def is_auto_reply(message: str) -> bool:
    n = normalize(message)
    return any(p in n for p in AUTO_REPLY_PHRASES)


def is_repeated_text(message: str, history: list, role: str) -> bool:
    n = normalize(message)
    if len(n) < 10:
        return False
    same_role_msgs = [normalize(h.get("message", "")) for h in history if h.get("role") == role]
    return same_role_msgs.count(n) >= 1


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
    if n in ("yes", "haan", "ok", "okay", "sure", "yep", "yup", "y"):
        return "positive"
    if n in ("no", "nahi", "nope", "n"):
        return "negative"
    return "neutral"


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
        "stale_posts": ["stale_posts"],
        "gbp_unverified": ["unverified", "gbp_incomplete"],
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


INTERNAL_JARGON = [
    "suppression_key", "trigger_id", "merchant_id", "context_id",
    "rationale", "send_as", "ack_id", "version=", "v1",
]


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

    if "i'm vera" in body_lower or "i am vera" in body_lower or "this is vera" in body_lower:
        return False, "re-introduction"

    for j in INTERNAL_JARGON:
        if j in body_lower:
            return False, f"internal jargon exposed: {j}"

    cta_count = body.count("Reply YES") + body.count("Reply NO") + body.count("reply 1") + body.count("reply 2")
    if cta_count > 2:
        return False, "multi-CTA"

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
        body = f"{owner}, views are up {pct}% this week ({views} total). Want me to scale your '{offer}' to capture this surge?"
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
            last = customer.get("relationship", {}).get("last_visit", "")
            body = f"Hi {cust_name}, {merch_name} here. {('It has been since ' + last) if last else 'Time for your next visit'} — {offer}. Reply YES to confirm a slot or share a preferred time."
        else:
            body = f"{owner}, customer recalls are due. Want me to draft and send reminders to the eligible list?"
        cta = "binary_yes_no"

    elif kind == "chronic_refill_due":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            body = f"Namaste {cust_name}, {merch_name} yahan. Your monthly refill is due. Same dose, ready for delivery to your saved address. Reply CONFIRM to dispatch."
        else:
            body = f"{owner}, chronic refills are due for your customers. Want me to send the reminder list?"
        cta = "binary_confirm"

    elif kind == "appointment_tomorrow":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            body = f"Hi {cust_name}, this is a reminder from {merch_name} — your appointment is tomorrow. Reply CONFIRM to keep the slot or RESCHEDULE if needed."
        else:
            body = f"{owner}, you have customer appointments tomorrow. Want me to send the reminder batch?"
        cta = "binary_confirm"

    elif kind in ("customer_lapsed_soft", "customer_lapsed_hard"):
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            offer = active_offers[0] if active_offers else "a fresh start"
            body = f"Hi {cust_name}, {merch_name} here — no judgment, just checking in. We have {offer} ready when you are. Reply YES to book — no commitment."
        else:
            lapsed = customer_agg.get("lapsed_180d_plus", "many")
            body = f"{owner}, {lapsed} customers haven't visited in 6+ months. Want me to draft a no-guilt winback message?"
        cta = "binary_yes_no"

    elif kind == "curious_ask_due":
        body = f"{owner}, quick check — what service has been most asked-for this week at {identity.get('name', 'your business')}? I'll turn the answer into a Google post + a customer reply template. 5 min."
        cta = "open_ended"

    elif kind == "festival_upcoming":
        payload = trigger.get("payload", {})
        festival = payload.get("festival_name", "the festival")
        days = payload.get("days_until", "")
        offer = active_offers[0] if active_offers else "a campaign offer"
        body = f"{owner}, {festival} is {(str(days) + ' days away') if days else 'coming up'}. Want me to draft a campaign around your '{offer}'?"
        cta = "binary_yes_no"

    elif kind == "ipl_match_today":
        payload = trigger.get("payload", {})
        match = payload.get("match", "the match tonight")
        offer = active_offers[0] if active_offers else "your active offer"
        body = f"{owner}, {match} tonight. Want me to draft a delivery-only special around '{offer}' + an Insta story? Live in 10 min."
        cta = "binary_yes_no"

    elif kind == "active_planning_intent":
        payload = trigger.get("payload", {})
        topic = payload.get("topic", "the plan we discussed")
        body = f"{owner}, here's a starter draft for {topic} — you can edit. Want me to send the full version with pricing tiers?"
        cta = "binary_confirm_cancel"

    elif kind == "supply_alert":
        payload = trigger.get("payload", {})
        molecule = payload.get("molecule", "an affected medicine")
        batches = payload.get("batches", [])
        affected = customer_agg.get("chronic_rx_count", "your chronic Rx customers")
        batch_str = ", ".join(batches[:2]) if batches else ""
        body = f"{owner}, urgent: voluntary recall on {molecule}{(' batches ' + batch_str) if batch_str else ''}. {affected} of your customers may be affected. Want me to draft the customer notification + replacement workflow?"
        cta = "binary_yes_no"

    elif kind == "review_theme_emerged":
        themes = merchant.get("review_themes", [])
        if themes:
            t = themes[0]
            body = f"{owner}, '{t.get('theme')}' has come up {t.get('occurrences_30d', '?')}× in your last 30d reviews ({t.get('sentiment')}). Want me to draft a public response template?"
        else:
            body = f"{owner}, a review theme is emerging in your recent feedback. Want me to surface the pattern + suggest a response?"
        cta = "binary_yes_no"

    elif kind == "milestone_reached":
        payload = trigger.get("payload", {})
        milestone = payload.get("milestone", "a milestone")
        body = f"{owner}, congrats — {milestone}! Want me to draft a celebration post for your Google profile + WhatsApp customers?"
        cta = "binary_yes_no"

    elif kind == "competitor_opened":
        payload = trigger.get("payload", {})
        distance = payload.get("distance_km", "nearby")
        body = f"{owner}, a new {category.get('slug', 'business')} opened {distance}km from you in {locality}. Want me to draft a differentiation play based on your strongest review themes?"
        cta = "binary_yes_no"

    elif kind == "renewal_due":
        days = merchant.get("subscription", {}).get("days_remaining", "soon")
        body = f"{owner}, your magicpin Pro renews in {days} days. Quick recap of value delivered last cycle is ready. Want to see it before deciding?"
        cta = "binary_yes_no"

    elif kind == "dormant_with_vera":
        body = f"{owner}, haven't heard from you in a while. Quick one — what's the #1 thing you'd want my help with this week? I can draft posts, reply templates, or pull peer benchmarks."
        cta = "open_ended"

    elif kind == "category_seasonal":
        beat = seasonal[0] if seasonal else {}
        note = beat.get("note", "a seasonal demand pattern")
        body = f"{owner}, {note}. Want me to prep a campaign before the peak window?"
        cta = "binary_yes_no"

    elif kind == "gbp_unverified":
        body = f"{owner}, your Google Business Profile is unverified — that caps your local search reach. 5-min verification. Want me to walk you through it now?"
        cta = "binary_yes_no"

    elif kind == "cde_opportunity":
        items = category.get("digest", [])
        item = next((i for i in items if "webinar" in (i.get("title", "").lower())), items[0] if items else {})
        title = item.get("title", "a relevant CDE opportunity")
        body = f"{owner}, {title}. Aapke practice ke liye relevant. Want me to send the registration details?"
        cta = "binary_yes_no"

    elif kind == "winback_eligible":
        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merch_name = identity.get("name", "us")
            offer = active_offers[0] if active_offers else "a welcome-back offer"
            body = f"Hi {cust_name}, {merch_name} here — been a while! No commitment, but {offer} is ready if you want to give us another try. Reply YES — that's it."
        else:
            body = f"{owner}, you have winback-eligible customers. Want me to draft a no-guilt re-engagement?"
        cta = "binary_yes_no"

    else:
        if active_offers:
            body = f"{owner}, your '{active_offers[0]}' is doing the work — want me to draft a peer-comparison post showing how it stacks up in {locality}?"
        else:
            body = f"{owner}, quick one. Your {locality} profile has new signals worth a look. Want me to walk you through them?"
        cta = "open_ended"

    return {"body": body, "cta": cta, "rationale": f"Deterministic fallback for trigger kind '{kind}', anchored on real merchant + category fields."}


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

    return {
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
        return {"action": "end", "rationale": "Conversation previously suppressed; no further messages."}

    store.append_turn(conversation_id, from_role, message)
    intent = detect_intent(message)

    if intent == "auto_reply":
        merchant_auto_count = store.bump_merchant_auto_count(merchant_id)

        if merchant_auto_count >= 3:
            store.suppress_conversation(conversation_id)
            return {
                "action": "end",
                "rationale": f"Auto-reply detected {merchant_auto_count}× from this merchant. No engagement signal. Closing.",
            }

        if merchant_auto_count == 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Second auto-reply from this merchant. Owner not at phone. Waiting 24h.",
            }

        return {
            "action": "wait",
            "wait_seconds": 14400,
            "rationale": "Auto-reply pattern detected (canned 'Thank you for contacting' phrasing). Backing off 4h to wait for the owner.",
        }

    if intent == "negative":
        store.suppress_conversation(conversation_id)
        merchant, _ = store.get_merchant_with_category(merchant_id)
        is_hindi = merchant and "hi" in merchant.get("identity", {}).get("languages", [])
        if is_hindi:
            body = "Sorry for the bother. Main aur messages nahi bhejongi. Agar kabhi zaroorat ho, reply 'Hi Vera'. 🙏"
        else:
            body = "Sorry for the bother — I won't message again. Reply 'Hi Vera' anytime if anything changes. 🙏"
        return {
            "action": "send",
            "body": body,
            "cta": "none",
            "rationale": "Hostile / opt-out detected. Apologetic single-line exit. Conversation suppressed.",
        }

    merchant, category = store.get_merchant_with_category(merchant_id)
    if not merchant: merchant = {}
    if not category: category = {}
    conv = store.get_conversation(conversation_id) or {}
    history = conv.get("history", [])

    trigger_kind = conv.get("trigger_kind", "general")
    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]
    owner = merchant.get("identity", {}).get("owner_first_name", "")

    if intent == "positive":
        if trigger_kind == "active_planning_intent":
            body = f"Drafting it now — sending the full version with tiers + an outreach template in 60 seconds. Reply CONFIRM to proceed."
        elif trigger_kind == "research_digest":
            body = f"Sending the abstract now — also drafting a patient-ed WhatsApp you can share. Reply CONFIRM to schedule the Google post for tomorrow 10am."
        elif trigger_kind == "festival_upcoming":
            offer = active_offers[0] if active_offers else "your campaign"
            body = f"Drafting the {offer} campaign now — full post + WhatsApp template ready in 90 seconds. Reply CONFIRM to launch."
        elif trigger_kind in ("perf_dip", "perf_spike"):
            body = f"Pulling your full diagnostic now — 3 specific actions ranked by impact, here in 2 minutes. Reply CONFIRM to receive the playbook."
        else:
            offer = active_offers[0] if active_offers else "the next step"
            owner_str = f"{owner}, " if owner else ""
            body = f"{owner_str}done — drafting now. Sending the full version with one-tap actions in 60 seconds. Reply CONFIRM to proceed to the next step."

        return {
            "action": "send",
            "body": body,
            "cta": "binary_confirm_cancel",
            "rationale": f"Explicit positive commitment on {trigger_kind}. Switching from qualification to action mode. Action verbs only — no qualifying questions.",
        }

    if intent == "off_topic":
        body = f"That one's outside what I can help with directly{', ' + owner if owner else ''} — best to check with your CA or specialist on that. Coming back to our thread — want me to take the next step on what we were discussing?"
        return {
            "action": "send",
            "body": body,
            "cta": "binary_yes_no",
            "rationale": "Off-topic ask politely declined; redirecting back to original thread.",
        }

    try:
        prompt = build_reply_prompt(history, message, merchant, category, trigger_kind, turn_number)
        result = call_llm_json(COMPOSER_REPLY_SYSTEM, prompt, max_tokens=400)
        if result.get("action") == "end":
            store.suppress_conversation(conversation_id)
        return result
    except Exception as e:
        is_hindi = merchant and "hi" in merchant.get("identity", {}).get("languages", [])
        owner_str = f", {owner}" if owner else ""
        body = (f"Got it{owner_str}! Aage badhne ke liye reply YES." if is_hindi
                else f"Got it{owner_str}! Reply YES to continue.")
        return {
            "action": "send",
            "body": body,
            "cta": "binary_yes_no",
            "rationale": f"LLM error fallback ({str(e)[:60]}); using neutral continuation prompt.",
        }

