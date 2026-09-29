from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Complaint, ComplaintStatus
from app.services.ai_engine import answer_faq_question
from app.services.rate_limit import check_rate_limit, client_ip, seconds_until_reset

router = APIRouter(tags=["chatbot"])

CHAT_LIMIT = 20
CHAT_WINDOW = 60 * 60


class ChatRequest(BaseModel):
    message: str
    language: str = "en"


async def _live_stats_summary(db: AsyncSession) -> str:
    """A one-line real-numbers snapshot so the bot can answer "what are the
    statistics" with the platform's actual current counts instead of
    guessing — same "no invented numbers" rule the rest of the app follows."""
    async def count(*conds):
        q = select(func.count(Complaint.id)).where(Complaint.is_ai_filtered == True, *conds)
        return (await db.execute(q)).scalar() or 0

    total = await count()
    resolved = await count(Complaint.status == ComplaintStatus.resolved)
    critical = await count(Complaint.priority_score >= 80, Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.disputed]))
    states = (await db.execute(
        select(func.count(func.distinct(Complaint.state))).where(Complaint.state.isnot(None), Complaint.is_ai_filtered == True)
    )).scalar() or 0
    return f"{total} complaints reported so far, {resolved} resolved, {critical} currently critical/open, across {states} state(s)."


@router.post("/chatbot")
async def chatbot(payload: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Home-page help chatbot — grounded only in what NagarVaani actually
    does (see _CHATBOT_GROUNDING in ai_engine.py), answers in the caller's
    selected language. Rate-limited per IP since each call costs a real LLM
    request, same pattern as OTP resend."""
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Nothing to ask")
    if len(message) > 1000:
        raise HTTPException(status_code=400, detail="Question too long (max 1000 characters)")

    key = client_ip(request)
    if not check_rate_limit("chatbot", key, CHAT_LIMIT, CHAT_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many questions — try again later",
            headers={"Retry-After": str(seconds_until_reset("chatbot", key, CHAT_WINDOW))},
        )

    live_stats = await _live_stats_summary(db)
    reply = await answer_faq_question(message, payload.language or "en", live_stats)
    return {"reply": reply}
