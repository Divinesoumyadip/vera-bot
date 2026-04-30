CATEGORY_RULES = {
    "dentists": {
        "tone": "peer_clinical",
        "salutation": "Dr. {owner_first_name}",
        "domain_vocab": ["fluoride varnish", "scaling", "caries", "bruxism", "aligner", "RCT", "IOPA", "periodontal"],
        "taboos": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city"],
        "code_mix": "hindi_english_natural",
        "cta_style": "open_ended_or_binary",
        "compulsion_priority": ["specificity", "source_citation", "merchant_fit", "curiosity"],
        "no_hype": True,
        "send_as_default": "vera",
    },
    "salons": {
        "tone": "warm_practical_visual",
        "salutation": "{owner_first_name}",
        "domain_vocab": ["keratin", "balayage", "bridal", "skin-prep", "blow-dry", "waxing", "threading", "nail art"],
        "taboos": ["guaranteed results", "miracle treatment", "100% effective"],
        "code_mix": "hindi_english_natural",
        "cta_style": "binary_or_slot_choice",
        "compulsion_priority": ["social_proof", "urgency", "curiosity", "loss_aversion"],
        "no_hype": False,
        "send_as_default": "vera",
    },
    "restaurants": {
        "tone": "warm_busy_practical",
        "salutation": "{owner_first_name}",
        "domain_vocab": ["footfall", "covers", "AOV", "table turnover", "happy hour", "thali", "biryani", "GRO"],
        "taboos": ["best food in city", "guaranteed packed house", "miracle marketing"],
        "code_mix": "hindi_english_natural",
        "cta_style": "binary_or_effort_externalize",
        "compulsion_priority": ["loss_aversion", "specificity", "effort_externalization", "social_proof"],
        "no_hype": False,
        "send_as_default": "vera",
    },
    "gyms": {
        "tone": "coach_practical_motivational",
        "salutation": "{owner_first_name}",
        "domain_vocab": ["HIIT", "strength", "cardio", "retention", "member churn", "renewal", "batch", "PT sessions"],
        "taboos": ["guaranteed weight loss", "miracle results", "100% transformation"],
        "code_mix": "hindi_english_natural",
        "cta_style": "binary_or_slot_choice",
        "compulsion_priority": ["social_proof", "loss_aversion", "specificity", "effort_externalization"],
        "no_hype": False,
        "send_as_default": "vera",
    },
    "pharmacies": {
        "tone": "trustworthy_precise_utility",
        "salutation": "{owner_first_name}",
        "domain_vocab": ["chronic Rx", "refill", "batch", "dispense", "compliance", "generic", "sub-potency"],
        "taboos": ["best pharmacy", "guaranteed cure", "miracle medicine"],
        "code_mix": "hindi_english_formal_mix",
        "cta_style": "binary_confirm",
        "compulsion_priority": ["urgency", "specificity", "effort_externalization", "loss_aversion"],
        "no_hype": True,
        "send_as_default": "vera",
    },
}

TRIGGER_STRATEGY = {
    "research_digest":         {"frame": "Relevant research item for the category.", "cta": "open_ended",              "compulsion": ["source_citation", "specificity", "curiosity"]},
    "regulation_change":       {"frame": "Compliance alert with a hard deadline.",   "cta": "binary_yes_no",           "compulsion": ["urgency", "specificity", "loss_aversion"]},
    "recall_due":              {"frame": "Patient recall — personal, specific.",      "cta": "slot_choice_or_binary",   "compulsion": ["personalization", "specificity", "effort_externalization"], "send_as": "merchant_on_behalf"},
    "perf_spike":              {"frame": "Good news + suggest capitalizing.",         "cta": "open_ended",              "compulsion": ["specificity", "curiosity", "reciprocity"]},
    "perf_dip":                {"frame": "Performance drop — data, diagnosis, fix.",  "cta": "binary_yes_no",           "compulsion": ["loss_aversion", "specificity", "effort_externalization"]},
    "seasonal_perf_dip":       {"frame": "Expected seasonal dip — reframe + retain.", "cta": "binary_yes_no",          "compulsion": ["anxiety_preemption", "specificity", "social_proof"]},
    "milestone_reached":       {"frame": "Celebrate + suggest next goal.",            "cta": "open_ended",              "compulsion": ["reciprocity", "social_proof", "curiosity"]},
    "dormant_with_vera":       {"frame": "Re-engage after silence — low friction.",   "cta": "binary_yes_no",           "compulsion": ["curiosity", "asking_the_merchant", "effort_externalization"]},
    "customer_lapsed_soft":    {"frame": "Gentle recall — no shame, specific offer.", "cta": "slot_choice_or_binary",   "compulsion": ["personalization", "specificity", "no_shame"], "send_as": "merchant_on_behalf"},
    "customer_lapsed_hard":    {"frame": "Winback — warm, no guilt, new offering.",   "cta": "binary_no_commitment",    "compulsion": ["no_shame", "new_offering", "specificity"], "send_as": "merchant_on_behalf"},
    "ipl_match_today":         {"frame": "IPL day — contrarian data, use existing offer.", "cta": "binary_yes_no",     "compulsion": ["loss_aversion", "specificity", "effort_externalization"]},
    "festival_upcoming":       {"frame": "Festival in X days — draft campaign now.",  "cta": "binary_yes_no",           "compulsion": ["urgency", "effort_externalization", "social_proof"]},
    "active_planning_intent":  {"frame": "Merchant said yes — deliver artifact, do not re-qualify.", "cta": "binary_confirm_cancel", "compulsion": ["effort_externalization", "specificity", "reciprocity"]},
    "supply_alert":            {"frame": "Compliance alert — batch numbers, affected count.", "cta": "binary_yes_no",  "compulsion": ["urgency", "specificity", "effort_externalization"]},
    "chronic_refill_due":      {"frame": "Refill — precise molecules, savings, one-tap confirm.", "cta": "binary_confirm", "compulsion": ["specificity", "effort_externalization", "loss_aversion"], "send_as": "merchant_on_behalf"},
    "curious_ask_due":         {"frame": "Weekly check-in — one question, concrete deliverable.", "cta": "open_ended", "compulsion": ["asking_the_merchant", "reciprocity", "effort_externalization"]},
    "review_theme_emerged":    {"frame": "Review pattern — insight + suggested fix.",  "cta": "binary_yes_no",          "compulsion": ["specificity", "loss_aversion", "effort_externalization"]},
    "competitor_opened":       {"frame": "New competitor — inform + differentiation play.", "cta": "open_ended",        "compulsion": ["loss_aversion", "specificity", "curiosity"]},
    "appointment_tomorrow":    {"frame": "Appointment tomorrow — confirm slot.",        "cta": "binary_confirm",         "compulsion": ["specificity", "effort_externalization"], "send_as": "merchant_on_behalf"},
    "renewal_due":             {"frame": "Subscription renewal — show value, single confirm.", "cta": "binary_yes_no", "compulsion": ["reciprocity", "loss_aversion", "specificity"]},
    "gbp_unverified":          {"frame": "GBP unverified — explain impact + start verification.", "cta": "binary_yes_no", "compulsion": ["loss_aversion", "specificity", "effort_externalization"]},
    "cde_opportunity":         {"frame": "Continuing education relevant to category.", "cta": "binary_yes_no",           "compulsion": ["specificity", "curiosity", "social_proof"]},
    "category_seasonal":       {"frame": "Seasonal demand — prepare campaign before peak.", "cta": "binary_yes_no",     "compulsion": ["specificity", "urgency", "social_proof"]},
    "trial_followup":          {"frame": "Post-trial followup — next booking window open.", "cta": "slot_choice_or_binary", "compulsion": ["urgency", "personalization", "specificity"], "send_as": "merchant_on_behalf"},
    "wedding_package_followup":{"frame": "Wedding approaching — book final session.",  "cta": "slot_choice_or_binary",   "compulsion": ["urgency", "specificity", "personalization"], "send_as": "merchant_on_behalf"},
    "winback_eligible":        {"frame": "Lapsed customer winback — warm, no guilt.", "cta": "binary_no_commitment",    "compulsion": ["no_shame", "new_offering", "specificity"], "send_as": "merchant_on_behalf"},
}


def get_category_rules(slug: str) -> dict:
    return CATEGORY_RULES.get(slug, CATEGORY_RULES["restaurants"])


def get_trigger_strategy(kind: str) -> dict:
    return TRIGGER_STRATEGY.get(kind, {
        "frame": "Engage the merchant with relevant context.",
        "cta": "open_ended",
        "compulsion": ["specificity", "curiosity"],
    })
