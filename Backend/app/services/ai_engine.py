"""
NagarVaani AI Engine
====================
Three sequential LLM calls on every complaint submission (Gemini by default,
free tier — see _PROVIDER below to switch to Claude):
  Call 1 — Filter: reject political/communal framing
  Call 2 — Classify + Extract: category, language, severity
  Call 3 — Score: 6-level priority hierarchy → final score 0-100 (pure math, no LLM call)

Plus:
  - NLP comment scanner: detect place names → auto-link areas
  - Translation: any language → English for processing
  - Official brief generator: synthesize raw complaint into structured brief
"""

import json
import re
from datetime import datetime
from typing import Optional
from google import genai
from app.config import get_settings

settings = get_settings()

# Free-tier Gemini by default. If you have Anthropic credits and want Claude's
# (generally stronger) classification instead, set ANTHROPIC_API_KEY and flip
# _PROVIDER below back to "anthropic" — every call in this file goes through
# the single _call_llm() helper, so that's the only place to change.
_PROVIDER = "gemini"
GEMINI_MODEL = "gemini-3.8-flash"
CLAUDE_MODEL = "claude-sonnet-4-6"

_gemini_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

if _PROVIDER == "anthropic":
    import anthropic
    _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _call_llm(prompt: str, max_tokens: int = 500) -> str:
    """Single entry point for every LLM call below — returns raw response
    text. Raises on failure; every caller already wraps this in its own
    try/except with a fail-open fallback, so an exception here just means
    that particular call degrades gracefully rather than crashing."""
    if _PROVIDER == "anthropic":
        response = _anthropic_client.messages.create(
            model=CLAUDE_MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    if _gemini_client is None:
        raise RuntimeError("GEMINI_API_KEY not configured")
    response = _gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        # thinking_budget: 0 — these are quick classification/JSON calls, not
        # reasoning tasks. Without this, the model's hidden "thinking" tokens
        # eat into max_output_tokens and can silently truncate the real
        # answer before it's written (finish_reason MAX_TOKENS, .text empty).
        config={"max_output_tokens": max_tokens, "thinking_config": {"thinking_budget": 0}},
    )
    if not response.text:
        raise RuntimeError(f"Gemini returned no text (finish_reason={response.candidates[0].finish_reason})")
    return response.text.strip()

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
        raw = _call_llm(prompt, max_tokens=300)
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
        raw = _call_llm(prompt, max_tokens=400)
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
        raw = _call_llm(prompt, max_tokens=300)
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
        raw = _call_llm(prompt, max_tokens=100)
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
        raw = _call_llm(prompt, max_tokens=500)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return {"translated": text, "detected_language": "en"}


# ── HOME-PAGE CHATBOT ──────────────────────────────────────────────────────────
# Grounded strictly in what the platform actually does — no invented features,
# no promises about things NagarVaani can't do (payments, legal advice, etc.).
_CHATBOT_GROUNDING = """You are the NagarVaani help assistant. Answer ONLY using the facts below —
never invent a feature, price, timeline, or government process that isn't listed here.

What NagarVaani actually does:
- Citizens report civic issues (drainage, garbage, road, electricity, tree hazards, water supply)
  by web form, voice note, or the Telegram bot @NagarVaaniBot — in Hindi, Marathi, Tamil, or English.
- Reporting works anonymously (you get a tracking ID) or signed in (saved to "My complaints").
- An AI ranks complaints by real severity, monsoon-season risk, and how many areas report the
  same problem — NOT by vote count. A 3-vote monsoon drain can outrank a 100-vote pothole.
- Anyone can vote in solidarity on any complaint nationwide via the Trending page, not just their own ward.
- Complaint status moves open → in progress → resolved; if marked resolved but not actually
  fixed, the reporter can dispute it from "My complaints".
- Corruption reports go through a separate, careful review channel and are never made public by default.
- The Government News & Schemes page lists real central schemes (Swachh Bharat Mission, AMRUT 2.0,
  Jal Jeevan Mission, Saubhagya, Smart Cities Mission) and a Ministry Directory with real links to
  the responsible ministry for each issue type.
- Officials get a dashboard scoped to their ward/city/state, a hotspot map, and an investment-flag
  queue. Official accounts require a work email (personal email providers are rejected) and admin approval.
- The Organizations, Volunteers & NGOs page lets individuals volunteer or organizations partner —
  both are real email forms to nagarvaani.gdg@gmail.com; no real corporate partners exist yet
  (labeled as examples on that page).
- The Our Impact page shows real resolved-complaint counts; tree-planting and recycling tracking
  are listed there as "coming soon", not implemented yet.
- The notification bell shows real status changes on complaints you personally filed.
- Any complaint or comment can be translated on demand into your selected language.
- Contact: nagarvaani.gdg@gmail.com.

Rules:
- Reply in {language} only.
- Keep it to 1-4 short sentences — this is a chat widget, not an essay.
- If asked something outside this list (pricing, legal advice, unrelated topics), say you don't
  have that information and suggest emailing nagarvaani.gdg@gmail.com or checking Help (the "?" icon).
- Never claim NagarVaani guarantees a fix, a timeline, or contacts a government body on the user's behalf.
"""

_LANG_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil"}

# A handful of instant, canned answers to the most common questions — no LLM
# call needed, so these always work even when the model's daily free-tier
# quota runs out (a real, recurring issue during demo/testing), and cost
# nothing. Matched by keyword against the user's own message; anything that
# doesn't match falls through to the real grounded LLM call below, same as
# before. Written by hand (not LLM-translated at request time) to match how
# every other fixed UI string in this app is done — see js/i18n.js.
_LOCAL_FAQ = [
    {
        "keywords": {
            "en": ["what is nagarvaani", "what does nagarvaani", "about this app", "about nagarvaani", "what is this app", "what is this platform", "what is this website"],
            "hi": ["नगरवाणी क्या है", "यह ऐप क्या है", "यह प्लेटफ़ॉर्म क्या है"],
            "mr": ["नगरवाणी म्हणजे काय", "हे अ‍ॅप काय आहे", "हे प्लॅटफॉर्म काय आहे"],
            "ta": ["நகர்வாணி என்றால் என்ன", "இந்த ஆப் என்ன", "இந்த தளம் என்ன"],
        },
        "answer": {
            "en": "NagarVaani is a civic complaint platform for India. Citizens report infrastructure issues (drainage, garbage, roads, electricity, water, corruption) by text, voice note, or Telegram, in Hindi, Marathi, Tamil, or English. AI ranks every complaint by real severity and season — not by vote count — and officials get a dashboard scoped to their ward, city, or state.",
            "hi": "नगरवाणी भारत के लिए एक नागरिक शिकायत प्लेटफ़ॉर्म है। नागरिक टेक्स्ट, वॉइस नोट या टेलीग्राम से — हिंदी, मराठी, तमिल या अंग्रेज़ी में — जल निकासी, कचरा, सड़क, बिजली, पानी या भ्रष्टाचार जैसी समस्याएँ दर्ज करते हैं। AI हर शिकायत को असली गंभीरता और मौसम के आधार पर रैंक करता है — वोट की संख्या से नहीं — और अधिकारियों को उनके वार्ड/शहर/राज्य तक सीमित डैशबोर्ड मिलता है।",
            "mr": "नगरवाणी हे भारतासाठी एक नागरी तक्रार व्यासपीठ आहे. नागरिक मजकूर, ध्वनी-नोंद किंवा टेलिग्रामद्वारे — हिंदी, मराठी, तमिळ किंवा इंग्रजीत — गटार, कचरा, रस्ते, वीज, पाणी किंवा भ्रष्टाचाराच्या समस्या नोंदवतात. AI प्रत्येक तक्रारीला खऱ्या गंभीरतेनुसार आणि हंगामानुसार क्रमवारी देते — मतांच्या संख्येनुसार नाही — आणि अधिकाऱ्यांना त्यांच्या प्रभाग/शहर/राज्यापुरता डॅशबोर्ड मिळतो.",
            "ta": "நகர்வாணி இந்தியாவுக்கான ஒரு குடிமக்கள் புகார் தளம். குடிமக்கள் உரை, குரல் குறிப்பு அல்லது டெலிகிராம் மூலம் — இந்தி, மராத்தி, தமிழ் அல்லது ஆங்கிலத்தில் — வடிகால், குப்பை, சாலை, மின்சாரம், நீர் அல்லது ஊழல் பிரச்சினைகளைப் புகாரளிக்கிறார்கள். AI ஒவ்வொரு புகாரையும் உண்மையான தீவிரத்தன்மை மற்றும் பருவகாலத்தின் அடிப்படையில் தரவரிசைப்படுத்துகிறது — வாக்குகளின் எண்ணிக்கையால் அல்ல — அதிகாரிகளுக்கு அவர்களது வார்டு/நகரம்/மாநிலத்திற்கு உட்பட்ட டாஷ்போர்டு கிடைக்கிறது.",
        },
    },
    {
        "keywords": {
            "en": ["statistic", "how many complaint", "how many report", "numbers so far", "total complaints"],
            "hi": ["आँकड़े", "आंकड़े", "कितनी शिकायतें", "कुल शिकायतें"],
            "mr": ["आकडेवारी", "किती तक्रारी", "एकूण तक्रारी"],
            "ta": ["புள்ளிவிவரங்கள்", "எத்தனை புகார்கள்", "மொத்த புகார்கள்"],
        },
        "stats_prefix": {
            "en": "Right now on NagarVaani: {stats}",
            "hi": "अभी नगरवाणी पर: {stats}",
            "mr": "सध्या नगरवाणीवर: {stats}",
            "ta": "இப்போது நகர்வாணியில்: {stats}",
        },
        "fallback": {
            "en": "Live statistics aren't available right now — check the Impact page.",
            "hi": "अभी लाइव आँकड़े उपलब्ध नहीं हैं — Impact पेज देखें।",
            "mr": "सध्या थेट आकडेवारी उपलब्ध नाही — Impact पेज पहा.",
            "ta": "நேரடி புள்ளிவிவரங்கள் இப்போது கிடைக்கவில்லை — Impact பக்கத்தைப் பாருங்கள்.",
        },
    },
    {
        "keywords": {
            "en": ["govt dashboard", "government dashboard", "official dashboard", "official portal"],
            "hi": ["सरकारी डैशबोर्ड", "अधिकारी डैशबोर्ड", "अधिकारी पोर्टल"],
            "mr": ["सरकारी डॅशबोर्ड", "अधिकारी डॅशबोर्ड", "अधिकारी पोर्टल"],
            "ta": ["அரசு டாஷ்போர்டு", "அதிகாரி டாஷ்போர்டு", "அதிகாரி போர்டல்"],
        },
        "answer": {
            "en": "The Govt dashboard is where verified officials manage complaints in their jurisdiction (ward, city, or state) — a priority queue, a hotspot map, and an Investment Flags list for issues worth coordinated funding. It requires a work email and admin approval to access.",
            "hi": "सरकारी डैशबोर्ड वह जगह है जहाँ सत्यापित अधिकारी अपने क्षेत्राधिकार (वार्ड/शहर/राज्य) की शिकायतें संभालते हैं — एक प्राथमिकता कतार, एक हॉटस्पॉट मैप, और निवेश योग्य मुद्दों की एक सूची। इसे इस्तेमाल करने के लिए वर्क ईमेल और एडमिन की मंज़ूरी ज़रूरी है।",
            "mr": "सरकारी डॅशबोर्ड म्हणजे जिथे पडताळणी झालेले अधिकारी त्यांच्या अधिकारक्षेत्रातील (प्रभाग/शहर/राज्य) तक्रारी हाताळतात — प्राधान्य रांग, हॉटस्पॉट नकाशा, आणि गुंतवणुकीयोग्य समस्यांची यादी. यासाठी वर्क ईमेल आणि अ‍ॅडमिनची मंजुरी आवश्यक आहे.",
            "ta": "அரசு டாஷ்போர்டு என்பது சரிபார்க்கப்பட்ட அதிகாரிகள் தங்கள் அதிகார எல்லையில் (வார்டு/நகரம்/மாநிலம்) புகார்களை நிர்வகிக்கும் இடம் — முன்னுரிமை வரிசை, ஹாட்ஸ்பாட் வரைபடம், மற்றும் முதலீடு தேவைப்படும் பிரச்சினைகளின் பட்டியல். இதற்கு பணி மின்னஞ்சலும் நிர்வாக ஒப்புதலும் தேவை.",
        },
    },
    {
        "keywords": {
            "en": ["priority", "how is it ranked", "how are complaints ranked", "score"],
            "hi": ["प्राथमिकता", "स्कोर", "रैंक कैसे"],
            "mr": ["प्राधान्य", "स्कोअर", "क्रमवारी कशी"],
            "ta": ["முன்னுரிமை", "மதிப்பெண்", "தரவரிசை எப்படி"],
        },
        "answer": {
            "en": "Priority is decided by AI, not votes: safety risk, the season (drainage ranks higher in monsoon), the type of problem, and how many areas report the same issue. Votes only add a small nudge at the end — a 3-vote monsoon drain can still outrank a 100-vote pothole.",
            "hi": "प्राथमिकता AI तय करता है, वोट नहीं: सुरक्षा जोखिम, मौसम (मानसून में जल निकासी की प्राथमिकता बढ़ जाती है), समस्या का प्रकार, और कितने इलाकों ने वही समस्या बताई है। वोट सिर्फ आख़िर में एक छोटा-सा असर डालते हैं — 3 वोट वाली मानसून नाली फिर भी 100 वोट वाले गड्ढे से ऊपर रह सकती है।",
            "mr": "प्राधान्य AI ठरवते, मते नाही: सुरक्षा धोका, हंगाम (पावसाळ्यात गटार समस्यांना जास्त प्राधान्य), समस्येचा प्रकार, आणि किती भागांनी तीच समस्या नोंदवली आहे. मतांचा परिणाम शेवटी फक्त थोडासा असतो — 3 मतांची पावसाळी गटार तक्रार 100 मतांच्या खड्ड्यापेक्षाही वरचढ राहू शकते.",
            "ta": "முன்னுரிமையை AI முடிவு செய்கிறது, வாக்குகள் அல்ல: பாதுகாப்பு அபாயம், பருவகாலம் (பருவமழையில் வடிகால் புகார்களுக்கு அதிக முன்னுரிமை), பிரச்சினையின் வகை, மற்றும் எத்தனை பகுதிகள் அதே பிரச்சினையைப் புகாரளிக்கின்றன. வாக்குகள் இறுதியில் ஒரு சிறிய தாக்கத்தை மட்டுமே ஏற்படுத்தும் — 3 வாக்குகள் கொண்ட பருவமழை வடிகால் புகார் 100 வாக்குகள் கொண்ட குழி புகாரை விட முன்னிலையில் இருக்க முடியும்.",
        },
    },
    {
        "keywords": {
            "en": ["how do i report", "how to report", "report an issue", "submit a complaint", "file a complaint"],
            "hi": ["शिकायत कैसे दर्ज", "रिपोर्ट कैसे करें", "शिकायत कैसे करें"],
            "mr": ["तक्रार कशी नोंदवायची", "तक्रार कशी करावी"],
            "ta": ["புகார் எப்படி அளிப்பது", "எப்படி புகார் செய்வது"],
        },
        "answer": {
            "en": 'Tap "Report an issue", describe the problem in any language (typing or a voice note), add a photo and your location, and submit — no account needed. You can also message the Telegram bot @NagarVaaniBot directly.',
            "hi": '"शिकायत दर्ज करें" पर टैप करें, समस्या को किसी भी भाषा में लिखें या वॉइस नोट भेजें, फोटो और लोकेशन जोड़ें, और सबमिट करें — खाता ज़रूरी नहीं। आप सीधे Telegram बॉट @NagarVaaniBot को भी मैसेज कर सकते हैं।',
            "mr": '"तक्रार नोंदवा" वर टॅप करा, समस्या कोणत्याही भाषेत टाइप करा किंवा ध्वनी-नोंद पाठवा, फोटो आणि ठिकाण जोडा, आणि सबमिट करा — खाते आवश्यक नाही. तुम्ही थेट Telegram बॉट @NagarVaaniBot लाही मेसेज करू शकता.',
            "ta": '"புகார் அளிக்க" என்பதைத் தட்டவும், பிரச்சினையை எந்த மொழியிலும் தட்டச்சு செய்யவும் அல்லது குரல் குறிப்பு அனுப்பவும், புகைப்படமும் இருப்பிடத்தையும் சேர்த்து சமர்ப்பிக்கவும் — கணக்கு தேவையில்லை. நீங்கள் நேரடியாக Telegram bot @NagarVaaniBot-க்கும் செய்தி அனுப்பலாம்.',
        },
    },
    {
        "keywords": {
            "en": ["corruption"],
            "hi": ["भ्रष्टाचार"],
            "mr": ["भ्रष्टाचार"],
            "ta": ["ஊழல்"],
        },
        "answer": {
            "en": 'Use the dedicated "Report corruption" option from the left menu — it goes through a separate review channel, and viewing corruption reports requires signing in (they\'re never shown in the public feeds).',
            "hi": 'बाएँ मेनू में दिए "भ्रष्टाचार की शिकायत करें" विकल्प का उपयोग करें — यह एक अलग समीक्षा प्रक्रिया से गुज़रता है, और इसे देखने के लिए साइन इन ज़रूरी है (यह सार्वजनिक फ़ीड में कभी नहीं दिखता)।',
            "mr": 'डाव्या मेनूमधील "भ्रष्टाचाराची तक्रार करा" हा पर्याय वापरा — ही तक्रार वेगळ्या पुनरावलोकन प्रक्रियेतून जाते, आणि ती पाहण्यासाठी साइन इन करणे आवश्यक आहे (ती सार्वजनिक फीडमध्ये कधीच दिसत नाही).',
            "ta": 'இடது மெனுவில் உள்ள "ஊழலைப் புகாரளி" விருப்பத்தைப் பயன்படுத்தவும் — இது தனி மதிப்பாய்வு செயல்முறையின் வழியாகச் செல்கிறது, அதைப் பார்க்க உள்நுழைவு தேவை (இது பொது ஊட்டங்களில் ஒருபோதும் காட்டப்படாது).',
        },
    },
    {
        "keywords": {
            "en": ["contact", "support", "phone number", "email address", "reach you"],
            "hi": ["संपर्क", "सहायता", "फ़ोन नंबर", "ईमेल पता"],
            "mr": ["संपर्क", "मदत", "फोन नंबर", "ईमेल पत्ता"],
            "ta": ["தொடர்பு", "ஆதரவு", "தொலைபேசி எண்", "மின்னஞ்சல் முகவரி"],
        },
        "answer": {
            "en": "You can reach NagarVaani at nagarvaani.gdg@gmail.com, or use the Help (?) icon in the top bar for quick answers.",
            "hi": "आप नगरवाणी से nagarvaani.gdg@gmail.com पर संपर्क कर सकते हैं, या ऊपर टॉपबार में Help (?) आइकन देखें।",
            "mr": "तुम्ही नगरवाणीशी nagarvaani.gdg@gmail.com वर संपर्क साधू शकता, किंवा वरील टॉपबारमधील Help (?) आयकॉन पहा.",
            "ta": "நீங்கள் நகர்வாணியை nagarvaani.gdg@gmail.com-ல் தொடர்பு கொள்ளலாம், அல்லது மேலே உள்ள Help (?) ஐகானைப் பாருங்கள்.",
        },
    },
    {
        "keywords": {
            "en": ["anonymous", "anonymously", "without an account", "without account"],
            "hi": ["गुमनाम", "बिना खाते", "बिना अकाउंट"],
            "mr": ["निनावी", "खात्याशिवाय"],
            "ta": ["அநாமதேயம்", "கணக்கு இல்லாமல்"],
        },
        "answer": {
            "en": "Yes — reporting anonymously is an option on the submit form. You still get a tracking ID to check on it later, but no name or email is attached to the report.",
            "hi": "हाँ — शिकायत फ़ॉर्म में गुमनाम रिपोर्ट करने का विकल्प है। आपको बाद में ट्रैक करने के लिए एक ID मिलती है, लेकिन शिकायत से कोई नाम या ईमेल नहीं जुड़ता।",
            "mr": "होय — तक्रार फॉर्ममध्ये निनावी नोंदवण्याचा पर्याय आहे. तुम्हाला नंतर ट्रॅक करण्यासाठी एक ID मिळते, पण तक्रारीशी कोणतेही नाव किंवा ईमेल जोडले जात नाही.",
            "ta": "ஆம் — சமர்ப்பிப்பு படிவத்தில் அநாமதேயமாகப் புகாரளிக்கும் விருப்பம் உள்ளது. பின்னர் கண்காணிக்க ஒரு ID கிடைக்கும், ஆனால் பெயரோ மின்னஞ்சலோ புகாருடன் இணைக்கப்படாது.",
        },
    },
    {
        "keywords": {
            "en": ["telegram"],
            "hi": ["टेलीग्राम"],
            "mr": ["टेलिग्राम"],
            "ta": ["டெலிகிராம்"],
        },
        "answer": {
            "en": "Message @NagarVaaniBot on Telegram to report issues by text or voice note. Link it to your account from your profile panel to get status updates there too.",
            "hi": "टेक्स्ट या वॉइस नोट से शिकायत दर्ज करने के लिए Telegram पर @NagarVaaniBot को मैसेज करें। स्टेटस अपडेट पाने के लिए इसे अपने प्रोफ़ाइल पैनल से अपने खाते से लिंक करें।",
            "mr": "मजकूर किंवा ध्वनी-नोंदीद्वारे तक्रार नोंदवण्यासाठी Telegram वर @NagarVaaniBot ला मेसेज करा. स्टेटस अपडेट्स मिळवण्यासाठी ते तुमच्या प्रोफाइल पॅनेलमधून खात्याशी लिंक करा.",
            "ta": "உரை அல்லது குரல் குறிப்பு மூலம் புகாரளிக்க Telegram-இல் @NagarVaaniBot-க்கு செய்தி அனுப்பவும். நிலை புதுப்பிப்புகளைப் பெற உங்கள் சுயவிவரப் பலகத்திலிருந்து அதை உங்கள் கணக்குடன் இணைக்கவும்.",
        },
    },
    {
        "keywords": {
            "en": ["official account", "become an official", "verify official", "official signup", "official sign up"],
            "hi": ["अधिकारी खाता", "अधिकारी कैसे बनें", "अधिकारी सत्यापन"],
            "mr": ["अधिकारी खाते", "अधिकारी कसे व्हावे", "अधिकारी पडताळणी"],
            "ta": ["அதிகாரி கணக்கு", "அதிகாரி எப்படி ஆவது", "அதிகாரி சரிபார்ப்பு"],
        },
        "answer": {
            "en": "Officials sign up with a work email (personal providers like Gmail are rejected) and an admin reviews and approves the account before it gets dashboard access — there's no self-service official signup.",
            "hi": "अधिकारी वर्क ईमेल से साइन अप करते हैं (Gmail जैसे व्यक्तिगत ईमेल स्वीकार नहीं होते) और डैशबोर्ड एक्सेस मिलने से पहले एक एडमिन खाते की समीक्षा और मंज़ूरी देता है — कोई सेल्फ़-सर्विस अधिकारी साइनअप नहीं है।",
            "mr": "अधिकारी वर्क ईमेलने साइन अप करतात (Gmail सारखे वैयक्तिक ईमेल स्वीकारले जात नाहीत) आणि डॅशबोर्ड अ‍ॅक्सेस मिळण्यापूर्वी अ‍ॅडमिन खात्याचे पुनरावलोकन करून मंजुरी देतो — कोणतेही सेल्फ-सर्व्हिस अधिकारी साइनअप नाही.",
            "ta": "அதிகாரிகள் பணி மின்னஞ்சலுடன் பதிவு செய்கிறார்கள் (Gmail போன்ற தனிப்பட்ட மின்னஞ்சல்கள் ஏற்கப்படாது), டாஷ்போர்டு அணுகல் கிடைப்பதற்கு முன் நிர்வாகி கணக்கை மதிப்பாய்வு செய்து ஒப்புதல் அளிக்கிறார் — சுய-சேவை அதிகாரி பதிவு இல்லை.",
        },
    },
    {
        "keywords": {
            "en": ["data safe", "is my data", "privacy", "data protection"],
            "hi": ["डेटा सुरक्षित", "प्राइवेसी", "गोपनीयता"],
            "mr": ["डेटा सुरक्षित", "गोपनीयता", "प्रायव्हसी"],
            "ta": ["தரவு பாதுகாப்பு", "தனியுரிமை"],
        },
        "answer": {
            "en": "Passwords are never stored in plain text, anonymous reports carry no name or email, and complaint text/photos are only sent to the AI/storage services actually needed to classify, score, or translate them. See PRIVACY.md in the repo for the full picture.",
            "hi": "पासवर्ड कभी भी सादे टेक्स्ट में स्टोर नहीं होते, गुमनाम रिपोर्ट में कोई नाम या ईमेल नहीं होता, और शिकायत का टेक्स्ट/फ़ोटो केवल उन्हीं AI/स्टोरेज सेवाओं को भेजा जाता है जो उन्हें वर्गीकृत, स्कोर या अनुवाद करने के लिए ज़रूरी हैं। पूरी जानकारी के लिए रिपॉज़िटरी में PRIVACY.md देखें।",
            "mr": "पासवर्ड कधीही साध्या मजकुरात साठवले जात नाहीत, निनावी तक्रारींमध्ये कोणतेही नाव किंवा ईमेल नसते, आणि तक्रारीचा मजकूर/फोटो फक्त वर्गीकरण, स्कोअरिंग किंवा भाषांतरासाठी आवश्यक असलेल्या AI/स्टोरेज सेवांनाच पाठवले जातात. संपूर्ण माहितीसाठी रिपॉझिटरीमधील PRIVACY.md पहा.",
            "ta": "கடவுச்சொற்கள் ஒருபோதும் எளிய உரையாக சேமிக்கப்படாது, அநாமதேய புகார்களில் பெயரோ மின்னஞ்சலோ இருக்காது, புகார் உரை/புகைப்படங்கள் வகைப்படுத்த, மதிப்பெண் இட அல்லது மொழிபெயர்க்க தேவைப்படும் AI/சேமிப்பக சேவைகளுக்கு மட்டுமே அனுப்பப்படும். முழு விவரங்களுக்கு repo-வில் உள்ள PRIVACY.md-ஐப் பாருங்கள்.",
        },
    },
]


def _local_faq_answer(message: str, language: str, live_stats: Optional[str]) -> Optional[str]:
    """Instant keyword-matched answer, or None to fall through to the LLM."""
    q = (message or "").lower()
    for topic in _LOCAL_FAQ:
        keywords = topic["keywords"].get(language, topic["keywords"]["en"])
        if not any(k.lower() in q for k in keywords):
            continue
        if "stats_prefix" in topic:
            if live_stats:
                template = topic["stats_prefix"].get(language, topic["stats_prefix"]["en"])
                return template.format(stats=live_stats)
            return topic["fallback"].get(language, topic["fallback"]["en"])
        return topic["answer"].get(language, topic["answer"]["en"])
    return None


async def answer_faq_question(message: str, language: str = "en", live_stats: Optional[str] = None) -> str:
    local = _local_faq_answer(message, language, live_stats)
    if local:
        return local

    lang_name = _LANG_NAMES.get(language, "English")
    stats_block = (
        f"\n\nCurrent real platform numbers (only use these if the question is actually about "
        f"statistics/numbers — otherwise ignore them entirely): {live_stats}"
        if live_stats else ""
    )
    prompt = (
        _CHATBOT_GROUNDING.format(language=lang_name) + stats_block
        + f'\n\nUser question: "{message}"\n\nYour reply (in {lang_name}, plain text, no markdown):'
    )
    try:
        reply = _call_llm(prompt, max_tokens=320)  # Indic scripts use more tokens per word than English
        return re.sub(r"```(?:\w+)?|```", "", reply).strip()
    except Exception:
        fallback = {
            "en": "Sorry, I can't answer that right now — try the Help (?) icon, or email nagarvaani.gdg@gmail.com.",
            "hi": "क्षमा करें, अभी जवाब नहीं दे पा रहा — Help (?) आइकन देखें, या nagarvaani.gdg@gmail.com पर ईमेल करें।",
            "mr": "क्षमस्व, सध्या उत्तर देऊ शकत नाही — Help (?) आयकॉन पहा, किंवा nagarvaani.gdg@gmail.com वर ईमेल करा.",
            "ta": "மன்னிக்கவும், இப்போது பதிலளிக்க முடியவில்லை — Help (?) ஐகானைப் பாருங்கள், அல்லது nagarvaani.gdg@gmail.com க்கு மின்னஞ்சல் அனுப்புங்கள்.",
        }
        return fallback.get(language, fallback["en"])


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
