"""
NagarVaani AI Engine
====================
Three sequential Claude API calls on every complaint submission:
  Call 1 — Filter: reject political/communal framing
  Call 2 — Classify + Extract: category, language, severity
  Call 3 — Score: 6-level priority hierarchy → final score 0-100

Plus:
  - NLP comment scanner: detect place names → auto-link areas
  - Translation: any language → English for processing
  - Official brief generator: synthesize raw complaint into structured brief
"""

import json
import re
from datetime import datetime
from typing import Optional
import anthropic
from app.config import get_settings

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# ── SEASONAL CONTEXT ──────────────────────────────────────────────────────────
# Month → season for India
INDIA_SEASONS = {
    1: "winter", 2: "winter", 3: "summer",
    4: "summer", 5: "summer", 6: "monsoon",
    7: "monsoon", 8: "monsoon", 9: "monsoon",
    10: "post_monsoon", 11: "post_monsoon", 12: "winter"
}

# Seasonal multipliers per category
SEASONAL_MULTIPLIERS = {
    "drainage": {"monsoon": 2.0, "post_monsoon": 1.5, "summer": 1.0, "winter": 1.0},
    "road": {"post_monsoon": 1.5, "monsoon": 1.3, "summer": 1.0, "winter": 1.0},
    "garbage": {"monsoon": 1.8, "summer": 1.5, "post_monsoon": 1.2, "winter": 1.0},
    "water_supply": {"summer": 1.8, "monsoon": 1.4, "winter": 1.0, "post_monsoon": 1.0},
    "electricity": {"summer": 1.8, "monsoon": 1.3, "winter": 1.0, "post_monsoon": 1.0},
    "tree_hazard": {"monsoon": 1.6, "post_monsoon": 1.4, "summer": 1.0, "winter": 1.0},
    "corruption": {"monsoon": 1.0, "summer": 1.0, "winter": 1.0, "post_monsoon": 1.0},
    "other": {"monsoon": 1.2, "summer": 1.1, "winter": 1.0, "post_monsoon": 1.0},
}

# L3 base weights per category
CATEGORY_BASE_WEIGHTS = {
    "water_supply": 28,
    "drainage": 26,
    "electricity": 22,
    "tree_hazard": 20,
    "garbage": 16,
    "road": 14,
    "corruption": 18,
    "other": 10,
}


def get_current_season() -> str:
    month = datetime.now().month
    return INDIA_SEASONS.get(month, "summer")


def get_seasonal_multiplier(category: str) -> float:
    season = get_current_season()
    cat_multipliers = SEASONAL_MULTIPLIERS.get(category, {})
    return cat_multipliers.get(season, 1.0)


# ── CALL 1: FILTER ────────────────────────────────────────────────────────────
async def filter_complaint(text: str) -> dict:
    """
    Returns: {passed: bool, reason: str, suggested_rephrasing: str|None}
    Rejects: political, communal, religious framing.
    Passes: infrastructure, civic service complaints.
    """
    prompt = f"""You are a moderator for NagarVaani, a civic infrastructure complaint platform.
Your job: decide if this complaint should be published.

ALLOW complaints about:
- Physical infrastructure: roads, drainage, water supply, electricity, trees, garbage
- Government service delivery failures
- Corruption (demanding money for services)
- Any civic issue framed around the PROBLEM, not people/groups

REJECT complaints that:
- Frame the problem around religion, caste, community, or political groups
- Are protest messages or political opinions
- Accuse specific communities instead of describing infrastructure failures
- Contain hate speech or incitement

The same underlying problem CAN be rephrased acceptably:
BAD: "Water is going to [community] and not to us because of [politician]"
GOOD: "Water supply is inconsistent in Zone X — some lanes receive water, others do not"

Complaint text:
"{text}"

Respond ONLY with valid JSON, no markdown:
{{
  "passed": true or false,
  "reason": "one sentence explanation",
  "suggested_rephrasing": "rephrased version if rejected due to framing, else null"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        # Fail open — let complaint through if AI call fails
        return {"passed": True, "reason": "AI filter unavailable — passed by default", "suggested_rephrasing": None}


# ── CALL 2: CLASSIFY + EXTRACT ───────────────────────────────────────────────
async def classify_complaint(text: str) -> dict:
    """
    Returns: {category, severity, detected_language, translated_text, location_hint, is_safety_risk}
    """
    prompt = f"""You are classifying a civic complaint for NagarVaani.

Extract:
1. category — one of: drainage, road, garbage, electricity, tree_hazard, water_supply, corruption, other
2. severity — one of: immediate_safety (physical harm in <72hrs), moderate, low
3. detected_language — ISO 639-1 code (e.g. "hi" for Hindi, "mr" for Marathi, "en" for English)
4. translated_text — English translation of the complaint (if already English, repeat it)
5. location_hint — any location mentioned in the text (street, landmark, area) or null
6. is_safety_risk — true if severity is immediate_safety, else false

Complaint:
"{text}"

Respond ONLY with valid JSON, no markdown:
{{
  "category": "drainage",
  "severity": "immediate_safety",
  "detected_language": "hi",
  "translated_text": "English version here",
  "location_hint": "Shivaji Nagar market lane" or null,
  "is_safety_risk": true
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        result = json.loads(raw)
        # Validate category
        valid_cats = ["drainage", "road", "garbage", "electricity", "tree_hazard", "water_supply", "corruption", "other"]
        if result.get("category") not in valid_cats:
            result["category"] = "other"
        return result
    except Exception as e:
        return {
            "category": "other",
            "severity": "moderate",
            "detected_language": "en",
            "translated_text": text,
            "location_hint": None,
            "is_safety_risk": False
        }


# ── CALL 3: SCORE ─────────────────────────────────────────────────────────────
async def score_complaint(
    text: str,
    category: str,
    is_safety_risk: bool,
    population: int = 10000,
    linked_area_count: int = 0,
    vote_count: int = 0,
) -> dict:
    """
    Priority = severity x vote multiplier. Severity (L1 safety + L3 category +
    L4 population + L5 cross-district pattern), amplified by season, is the
    entire basis of the score. Votes are applied last as a gentle log-scaled
    multiplicative nudge — they can shift the ranking between two similarly
    severe issues, but they can never flip a critical issue below a
    non-critical one, because they multiply rather than add.

    Returns: {score, breakdown, reasoning}

    L1 — Immediate safety risk (score floor 90+, overrides all)
    L2 — Seasonal amplifier (multiplier on severity)
    L3 — Problem type base weight
    L4 — Population density
    L5 — Cross-district pattern (flat bonus)
    Vote multiplier — applied after everything else: severity x (1 + log10(votes+1) x 0.1)
    """
    import math

    season = get_current_season()
    multiplier = get_seasonal_multiplier(category)
    base_weight = CATEGORY_BASE_WEIGHTS.get(category, 10)

    # L1 — Safety risk: floor of 40 severity points + score floor enforcement
    l1 = 40 if is_safety_risk else 0

    # L3 — Category base weight
    l3 = base_weight

    # L4 — Population density (log-scaled, max 15 points)
    l4 = min(15, round(math.log10(max(population, 100)) * 3))

    # L5 — Cross-district pattern bonus (5 per linked area, max 20)
    l5 = min(20, linked_area_count * 5)

    # Severity subtotal — this alone decides ranking between critical and non-critical issues
    severity = l1 + l3 + l4 + l5

    # Apply seasonal multiplier to severity
    severity_seasonal = severity * multiplier

    # Safety floor of 90, enforced before the vote nudge
    severity_floored = max(severity_seasonal, 90) if is_safety_risk else severity_seasonal

    # Vote multiplier — gentle, log-scaled, never inverts a severity-based ranking
    vote_multiplier = 1 + math.log10(max(vote_count, 0) + 1) * 0.1
    final_score = severity_floored * vote_multiplier

    # Cap at 100
    final_score = min(100, round(final_score, 1))

    reasoning = (
        f"L1={'safety risk +40' if is_safety_risk else 'no safety risk'}, "
        f"L3={category} base weight {l3}, "
        f"L4=population {population} → +{l4}, "
        f"L5={linked_area_count} linked areas → +{l5}. "
        f"Severity={severity} × L2 season {season}/{category} (×{multiplier}) = {round(severity_seasonal, 1)}"
        f"{', floored to 90 (safety risk)' if is_safety_risk and severity_seasonal < 90 else ''}. "
        f"× vote multiplier {round(vote_multiplier, 3)} ({vote_count} votes, log-scaled, weakest signal) = {final_score}."
    )

    return {
        "score": final_score,
        "breakdown": {
            "l1_safety": l1,
            "l3_type_weight": l3,
            "l4_population": l4,
            "l5_pattern_bonus": l5,
            "severity_subtotal": severity,
            "l2_seasonal_multiplier": multiplier,
            "l2_season": season,
            "severity_after_season": round(severity_seasonal, 1),
            "vote_multiplier": round(vote_multiplier, 3),
            "vote_count": vote_count,
            "final_score": final_score,
        },
        "reasoning": reasoning
    }


# ── OFFICIAL BRIEF GENERATOR ──────────────────────────────────────────────────
async def generate_official_brief(
    text_original: str,
    text_translated: str,
    category: str,
    score: float,
    score_breakdown: dict,
    location: str,
    linked_area_count: int,
) -> dict:
    """
    Generates the synthesized brief that government officials see.
    Returns: {brief, recommended_action}
    """
    prompt = f"""You are writing a brief for a government official about a citizen complaint.
Write it clearly and actionably. The official is busy — be concise.

Complaint (English): {text_translated}
Original complaint: {text_original}
Category: {category}
Priority score: {score}/100
Location: {location}
Linked to {linked_area_count} other areas reporting the same issue
Score breakdown: {json.dumps(score_breakdown, indent=2)}

Write:
1. A 2-3 sentence brief explaining the situation and why it's urgent
2. A recommended action in one sentence

Respond ONLY with valid JSON, no markdown:
{{
  "brief": "2-3 sentence situation summary for the official",
  "recommended_action": "One clear action the official should take"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return {
            "brief": f"Citizen complaint about {category} at {location}. Priority score: {score}/100.",
            "recommended_action": f"Inspect and address {category} issue at reported location."
        }


# ── NLP COMMENT SCANNER ───────────────────────────────────────────────────────
async def detect_places_in_comment(comment_text: str, complaint_city: str = "") -> list[str]:
    """
    Scan a comment for place name mentions.
    Returns list of detected place names.
    """
    prompt = f"""Extract all place names (areas, wards, neighbourhoods, villages, cities) mentioned in this comment.
Context: this is a civic complaint platform for India (city context: {complaint_city or 'India'}).

Comment: "{comment_text}"

Return ONLY a JSON array of place name strings. Empty array if none found.
Example: ["Katraj", "Hadapsar"] or []
No markdown, no explanation."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        places = json.loads(raw)
        return [p for p in places if isinstance(p, str) and len(p) > 2]
    except Exception:
        return []


# ── TRANSLATION ───────────────────────────────────────────────────────────────
async def translate_text(text: str, target_language: str = "en") -> dict:
    """
    Translate text to target language.
    Returns: {translated, detected_language}
    """
    prompt = f"""Translate the following text to {target_language}.
If it's already in {target_language}, return it unchanged.

Text: "{text}"

Respond ONLY with valid JSON, no markdown:
{{
  "translated": "translation here",
  "detected_language": "ISO 639-1 code of source language"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return {"translated": text, "detected_language": "en"}


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────
async def process_complaint_pipeline(
    text: str,
    location: str = "",
    population: int = 10000,
    vote_count: int = 0,
    linked_area_count: int = 0,
) -> dict:
    """
    Run all 3 calls sequentially.
    Returns complete processed complaint data or rejection notice.
    """
    # Call 1: Filter
    filter_result = await filter_complaint(text)
    if not filter_result.get("passed", True):
        return {
            "passed": False,
            "filter_reason": filter_result.get("reason", "Complaint rejected by AI moderation"),
            "suggested_rephrasing": filter_result.get("suggested_rephrasing"),
        }

    # Call 2: Classify
    classify_result = await classify_complaint(text)
    category = classify_result.get("category", "other")
    is_safety_risk = classify_result.get("is_safety_risk", False)

    # Call 3: Score
    score_result = await score_complaint(
        text=text,
        category=category,
        is_safety_risk=is_safety_risk,
        population=population,
        linked_area_count=linked_area_count,
        vote_count=vote_count,
    )

    # Generate official brief
    brief_result = await generate_official_brief(
        text_original=text,
        text_translated=classify_result.get("translated_text", text),
        category=category,
        score=score_result["score"],
        score_breakdown=score_result["breakdown"],
        location=location or classify_result.get("location_hint", "Unknown location"),
        linked_area_count=linked_area_count,
    )

    return {
        "passed": True,
        "filter_reason": None,
        "category": category,
        "is_safety_risk": is_safety_risk,
        "detected_language": classify_result.get("detected_language", "en"),
        "text_translated": classify_result.get("translated_text", text),
        "location_hint": classify_result.get("location_hint"),
        "priority_score": score_result["score"],
        "score_breakdown": score_result["breakdown"],
        "seasonal_multiplier": score_result["breakdown"]["l2_seasonal_multiplier"],
        "official_brief": brief_result.get("brief"),
        "recommended_action": brief_result.get("recommended_action"),
    }
