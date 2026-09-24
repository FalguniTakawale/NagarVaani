"""
Seed the demo dataset.

    python seed_data.py            # refuses to run twice (checks for ramesh@test.com)
    python seed_data.py --reset    # wipe every table first, then seed

Every complaint goes through the real process_complaint_pipeline() — the
same filter → classify → score → brief path the API uses — so the scores you
see are what Claude + score_complaint() actually produce, not hardcoded numbers.
Expect ~20 Claude calls and ~30 seconds. Without ANTHROPIC_API_KEY the AI
calls fail open (category "other", generic brief) and the seed still completes.
"""

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.models import (
    Comment, Complaint, ComplaintCategory, ComplaintStatus, District,
    EmailVerification, LinkedArea, OfficialLevel, StatusLog, User, UserRole, Vote,
)
from app.services.ai_engine import (
    INDIA_SEASONS, detect_places_in_comment, generate_official_brief,
    process_complaint_pipeline, score_complaint,
)
from app.services.auth import hash_password

settings = get_settings()

PUNE_POPULATION = 3_200_000
VILLAGE_POPULATION = 10_000   # Uruli Kanchan — the low-vote village case

COMPLAINTS = [
    {
        "key": "C1", "label": "drain complaint",
        "text": "Naali bhar gayi hai, paani ghar mein ghus raha hai. Teen din se kitchen use nahi kar pa rahe.",
        "category": "drainage", "is_safety_risk": True, "author": "citizen",
        "lat": 18.5308, "lng": 73.8479, "ward": "12", "area": "Shivaji Nagar", "city": "Pune", "state": "Maharashtra",
        "population": PUNE_POPULATION, "votes": 3,
        "linked_areas": ["Kasba Peth", "Budhwar Peth", "Mangalwar Peth"],
        "comments": [
            "Same problem in Kasba Peth — naali full hai wahan bhi",
            "This has been happening every monsoon for 3 years now",
        ],
    },
    {
        "key": "C2", "label": "pothole",
        "text": "Large pothole on Baner Road near Signal 4. Multiple vehicles damaged.",
        "category": "road", "is_safety_risk": False, "author": "citizen",
        "lat": 18.5590, "lng": 73.7868, "ward": "12", "area": "Baner", "city": "Pune", "state": "Maharashtra",
        "population": PUNE_POPULATION, "votes": 104,
    },
    {
        "key": "C3", "label": "village well",
        "text": "Gavakrya saglyanna panyacha tras ahe. Eka vihiritun pane yetat te ghalke zaale aahe.",
        "category": "water_supply", "is_safety_risk": True, "author": None,
        "lat": 18.2620, "lng": 74.0540, "ward": None, "area": "Uruli Kanchan", "city": "Pune", "state": "Maharashtra",
        "population": VILLAGE_POPULATION, "votes": 1,
    },
    {
        "key": "C4", "label": "power cuts",
        "text": "Power cuts for 6 hours daily in summer heat. Elderly residents suffering. Generator fuel running out.",
        "category": "electricity", "is_safety_risk": False, "author": "citizen",
        "lat": 18.5362, "lng": 73.8079, "ward": "12", "area": "Koregaon Park", "city": "Pune", "state": "Maharashtra",
        "population": PUNE_POPULATION, "votes": 12, "status_after": "in_progress",
    },
    {
        "key": "C5", "label": "bribery",
        "text": "Ward office asking for ₹500 to process my water connection application. This is bribery.",
        "category": "corruption", "is_safety_risk": False, "author": "citizen",
        "lat": 18.5204, "lng": 73.8567, "ward": "12", "area": "Sadashiv Peth", "city": "Pune", "state": "Maharashtra",
        "population": PUNE_POPULATION, "votes": 7,
    },
]

# Enough distinct voters for the largest vote count; a mix of wards so some
# votes register as solidarity (voter outside the complaint's ward).
VOTER_POOL = 110
VOTER_WARDS = ["12", "12", "12", "8", "15", "12", "3", "12", "21", "12"]
VOTER_AREAS = {"12": "Shivaji Nagar", "8": "Koregaon Park", "15": "Baner", "3": "Kothrud", "21": "Hadapsar"}


async def reset(session):
    for model in (Vote, Comment, LinkedArea, StatusLog, EmailVerification, Complaint, District, User):
        await session.execute(delete(model))
    await session.flush()
    print("  reset: all tables emptied")


async def create_users(session):
    citizen = User(
        name="Ramesh Kumar", email="ramesh@test.com", hashed_password=hash_password("Test@1234"),
        role=UserRole.citizen, city="Pune", ward="12", area="Shivaji Nagar", state="Maharashtra",
        latitude=18.5308, longitude=73.8479, is_email_verified=True,
    )
    official = User(
        name="Ward Officer Desai", email="official@test.com", hashed_password=hash_password("Official@1234"),
        role=UserRole.official, official_level=OfficialLevel.ward_officer,
        ward="12", city="Pune", state="Maharashtra", area="Shivaji Nagar", is_email_verified=True,
    )
    session.add_all([citizen, official])

    shared_hash = hash_password("Voter@1234")  # bcrypt once — 110 hashes would take ~30s on their own
    voters = []
    for i in range(1, VOTER_POOL + 1):
        ward = VOTER_WARDS[i % len(VOTER_WARDS)]
        voters.append(User(
            name=f"Voter {i}", email=f"voter{i}@seed.nagarvaani", hashed_password=shared_hash,
            role=UserRole.citizen, city="Pune", state="Maharashtra",
            ward=ward, area=VOTER_AREAS[ward], is_email_verified=True,
        ))
    session.add_all(voters)
    await session.flush()
    print(f"  users: citizen, official, {VOTER_POOL} voters")
    return citizen, official, voters


async def create_district(session):
    session.add(District(
        name="Pune", city="Pune", state="Maharashtra", population=PUNE_POPULATION,
        latitude=18.5204, longitude=73.8567,
        seasonal_data={str(m): season for m, season in INDIA_SEASONS.items()},
    ))
    await session.flush()
    print("  district: Pune (population 3,200,000, 12-month seasonal map)")


async def seed_complaint(session, spec, citizen, official, voters):
    linked = spec.get("linked_areas", [])

    # ── real AI pipeline: filter → classify → score → brief ──
    ai = await process_complaint_pipeline(
        text=spec["text"],
        location=f"{spec['area']}, {spec['city']}",
        population=spec["population"],
        vote_count=0,
        linked_area_count=len(linked),
    )
    if not ai.get("passed"):
        print(f"  ✗ {spec['key']} rejected by the AI filter: {ai.get('filter_reason')} — seeding anyway with expected values")
        ai = {"passed": True, "category": None, "is_safety_risk": None,
              "detected_language": None, "text_translated": spec["text"], "location_hint": None}

    # The demo narrative depends on the intended category / safety flag. If the
    # classifier disagrees we keep the intended classification and re-run the
    # (pure-math) scorer with it — still a real score, and we say so out loud.
    category = ai.get("category")
    is_safety_risk = ai.get("is_safety_risk")
    overridden = []
    if category != spec["category"]:
        overridden.append(f"category {category!r}→{spec['category']!r}")
        category = spec["category"]
    if bool(is_safety_risk) != spec["is_safety_risk"]:
        overridden.append(f"is_safety_risk {is_safety_risk!r}→{spec['is_safety_risk']!r}")
        is_safety_risk = spec["is_safety_risk"]

    if overridden:
        rescored = await score_complaint(
            text=spec["text"], category=category, is_safety_risk=is_safety_risk,
            population=spec["population"], linked_area_count=len(linked), vote_count=0,
        )
        ai["priority_score"] = rescored["score"]
        ai["score_breakdown"] = rescored["breakdown"]
        ai["seasonal_multiplier"] = rescored["breakdown"]["l2_seasonal_multiplier"]
        # The brief was written for the pre-override category/score — redo it so
        # the official dashboard doesn't show "complaint about other, score 48".
        brief = await generate_official_brief(
            text_original=spec["text"], text_translated=ai.get("text_translated") or spec["text"],
            category=category, score=rescored["score"], score_breakdown=rescored["breakdown"],
            location=f"{spec['area']}, {spec['city']}", linked_area_count=len(linked),
        )
        ai["official_brief"] = brief.get("brief")
        ai["recommended_action"] = brief.get("recommended_action")
        print(f"  ! {spec['key']} classifier disagreed ({'; '.join(overridden)}) — kept intended values, re-scored")

    complaint = Complaint(
        author_id=citizen.id if spec["author"] == "citizen" else None,
        text_original=spec["text"],
        text_translated=ai.get("text_translated") or spec["text"],
        detected_language=ai.get("detected_language"),
        category=ComplaintCategory(category),
        location_text=f"{spec['area']}, {spec['city']}",
        ward=spec["ward"], area=spec["area"], city=spec["city"], state=spec["state"],
        latitude=spec["lat"], longitude=spec["lng"],
        priority_score=ai.get("priority_score", 0),
        score_breakdown=ai.get("score_breakdown", {}),
        is_safety_risk=is_safety_risk,
        seasonal_multiplier=ai.get("seasonal_multiplier", 1.0),
        image_urls=[],
        source_channel="web",
        status=ComplaintStatus.open,
        is_ai_filtered=True,
        linked_area_count=len(linked),
        official_brief=ai.get("official_brief"),
        recommended_action=ai.get("recommended_action"),
    )
    session.add(complaint)
    await session.flush()

    for name in linked:
        session.add(LinkedArea(complaint_id=complaint.id, area_name=name, link_type="button", complaint_count=1))

    # ── votes, then re-score exactly like POST /complaints/{id}/vote does (only L6 moves) ──
    for voter in voters[: spec["votes"]]:
        session.add(Vote(
            complaint_id=complaint.id, user_id=voter.id,
            is_solidarity=bool(complaint.ward) and voter.ward != complaint.ward,
            voter_area=voter.area,
        ))
    if spec["votes"]:
        rescored = await score_complaint(
            text=complaint.text_original, category=category, is_safety_risk=is_safety_risk,
            population=spec["population"], linked_area_count=len(linked), vote_count=spec["votes"],
        )
        complaint.priority_score = rescored["score"]
        complaint.score_breakdown = rescored["breakdown"]

    # ── comments, with the same NLP place scan the API runs ──
    for text in spec.get("comments", []):
        places = await detect_places_in_comment(comment_text=text, complaint_city=complaint.city or "")
        session.add(Comment(
            complaint_id=complaint.id, author_id=citizen.id, author_name=citizen.name,
            author_area=citizen.area, text=text, detected_places=places,
        ))
        for place in places:
            existing = (await session.execute(select(LinkedArea).where(
                LinkedArea.complaint_id == complaint.id, LinkedArea.area_name == place))).scalar_one_or_none()
            if existing:
                existing.complaint_count += 1
            else:
                session.add(LinkedArea(complaint_id=complaint.id, area_name=place, link_type="nlp", complaint_count=1))
                complaint.linked_area_count += 1

    # ── official status change ──
    if spec.get("status_after"):
        new_status = ComplaintStatus(spec["status_after"])
        session.add(StatusLog(
            complaint_id=complaint.id, old_status=complaint.status, new_status=new_status,
            updated_by_id=official.id, note="Repair team assigned — expected within 2 days.",
        ))
        complaint.status = new_status

    await session.flush()
    print(f"  {spec['key']} {spec['label']:<16} score {complaint.priority_score:>5}  "
          f"({category}, {spec['votes']} votes, safety={is_safety_risk}, status={complaint.status.value})")
    return complaint


async def main() -> int:
    do_reset = "--reset" in sys.argv
    if not settings.anthropic_api_key:
        print("! ANTHROPIC_API_KEY is not set — AI calls will fail open. Scores will use the intended\n"
              "  categories, but briefs will be generic and language detection empty.")

    async with AsyncSessionLocal() as session:
        exists = (await session.execute(select(User).where(User.email == "ramesh@test.com"))).scalar_one_or_none()
        if exists and not do_reset:
            print("✗ Already seeded (ramesh@test.com exists). Re-run with --reset to wipe and reseed.")
            return 1
        if do_reset:
            await reset(session)

        print("Seeding…")
        citizen, official, voters = await create_users(session)
        await create_district(session)

        results = {}
        for spec in COMPLAINTS:
            results[spec["key"]] = await seed_complaint(session, spec, citizen, official, voters)

        await session.commit()

    await engine.dispose()

    print(
        "\n✓ Seed complete\n"
        "  Users: ramesh@test.com / Test@1234 (citizen)\n"
        "         official@test.com / Official@1234 (official)\n"
        "  Complaints: 5 with real AI scores\n"
        f"  Demo moment: drain complaint scored {results['C1'].priority_score}, "
        f"pothole scored {results['C2'].priority_score}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
