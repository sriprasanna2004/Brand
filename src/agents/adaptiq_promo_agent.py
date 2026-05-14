import os
import json
from typing import Optional
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

# All 7 stages with rich context for better messages
DAY_CONTEXT = {
    1: {
        "focus": "warm welcome + personalised onboarding + show exactly how to start weak area analysis",
        "tone": "warm, excited, like a friend who just handed you a superpower",
        "cta": "https://adaptiq.app/start",
        "urgency": "low",
    },
    3: {
        "focus": "personalised weak area report — name specific subjects, show AI has been watching their progress, give 3 concrete tips",
        "tone": "data-driven but encouraging, like a mentor who sees your potential",
        "cta": "https://adaptiq.app/weak-areas",
        "urgency": "low",
    },
    5: {
        "focus": "progress update — show 15-25% improvement, celebrate wins, show what's still to master",
        "tone": "celebratory and motivating, build momentum",
        "cta": "https://adaptiq.app/progress",
        "urgency": "medium",
    },
    7: {
        "focus": "trial ends tomorrow — show what they'll lose, offer special discount, make upgrading feel urgent but not desperate",
        "tone": "urgent but caring, FOMO without being pushy",
        "cta": "https://adaptiq.app/upgrade?discount=TOPPER30",
        "urgency": "high",
    },
    # Extended stages
    2: {
        "focus": "check-in — are they using the app? share a quick win tip for their weakest subject",
        "tone": "casual check-in, like a study buddy",
        "cta": "https://adaptiq.app/daily-quiz",
        "urgency": "low",
    },
    4: {
        "focus": "webinar invite — free live session on their weak subject this weekend",
        "tone": "exclusive invite, make them feel special",
        "cta": "https://adaptiq.app/webinar",
        "urgency": "medium",
    },
    6: {
        "focus": "demo of premium features — show what they're missing: full mock tests, mentor access, rank predictor",
        "tone": "aspirational, show the gap between free and premium",
        "cta": "https://adaptiq.app/premium-demo",
        "urgency": "high",
    },
}


class AdaptiqMessage(BaseModel):
    message: str
    cta_link: str
    subject_tips: Optional[list[str]] = None
    urgency_level: str = "low"
    push_notification: Optional[str] = None   # short push notif text
    email_subject: Optional[str] = None       # email subject line


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.7,
    )


def run_adaptiq_promo_agent(
    lead_name: str,
    trial_day: int,
    weak_subjects: list[str],
    improvement_pct: int = 0,
    source_post: str = "",
) -> AdaptiqMessage:
    if trial_day not in DAY_CONTEXT:
        raise ValueError(f"trial_day must be one of {list(DAY_CONTEXT.keys())}, got {trial_day}")

    ctx = DAY_CONTEXT[trial_day]
    subjects_str = ", ".join(weak_subjects) if weak_subjects else "Polity, Economy, Current Affairs"
    improvement_str = f"{improvement_pct}%" if improvement_pct else "15-22%"

    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are the growth engine for Adaptiq — an AI-powered UPSC preparation app by TOPPER IAS. "
            "Your messages convert free trial users to paid subscribers. "
            "Key differentiators: AI weak area analysis, adaptive mock tests, personalised study plans, rank predictor. "
            "Price: ₹299/month or ₹1,999/year. "
            "Write messages that feel like they're from a real person who cares about the student's UPSC journey. "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Write a Day {trial_day} Adaptiq trial message.\n\n"
            f"Student name: {lead_name}\n"
            f"Weak subjects: {subjects_str}\n"
            f"Improvement so far: {improvement_str}\n"
            f"Source post: {source_post or 'Instagram'}\n"
            f"Day {trial_day} focus: {ctx['focus']}\n"
            f"Tone: {ctx['tone']}\n"
            f"Urgency: {ctx['urgency']}\n\n"
            "Return a JSON object with:\n"
            "  message: Telegram message (warm, personal, under 400 chars, use student name)\n"
            f"  cta_link: '{ctx['cta']}'\n"
            "  subject_tips: list of 2-3 specific, actionable tips for their weak subjects (null for day 1 and 7)\n"
            f"  urgency_level: '{ctx['urgency']}'\n"
            "  push_notification: 1-line push notification text (under 60 chars)\n"
            "  email_subject: compelling email subject line (under 50 chars)"
        )),
    ]

    logger.info(f"[AdaptiqPromoAgent] Day {trial_day} for {lead_name}, weak={weak_subjects}, improvement={improvement_pct}%")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        msg = AdaptiqMessage(**data)
        logger.info(f"[AdaptiqPromoAgent] Message ready, urgency={msg.urgency_level}, cta={msg.cta_link}")
        return msg
    except Exception as e:
        logger.error(f"[AdaptiqPromoAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


