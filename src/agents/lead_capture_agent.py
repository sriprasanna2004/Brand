import os
import json
import enum
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

INTENT_KEYWORDS = [
    "fees", "batch", "admission", "join", "cost", "price", "how to",
    "register", "enroll", "course", "classes", "timing", "schedule",
    "syllabus", "rank", "topper",
]


class LeadStatusEnum(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class LeadScore(BaseModel):
    ig_handle: str
    status: LeadStatusEnum
    intent_keywords_found: list[str]
    auto_reply_message: str          # personalised, under 400 chars
    should_notify_admin: bool


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.4,
    )


def run_lead_capture_agent(message_text: str, ig_handle: str) -> LeadScore:
    # Pre-scan for intent keywords (case-insensitive)
    text_lower = message_text.lower()
    found_keywords = [kw for kw in INTENT_KEYWORDS if kw in text_lower]

    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are an expert sales analyst for TOPPER IAS who identifies serious UPSC aspirants from casual followers. "
            "Score leads as hot (ready to buy), warm (interested, needs nurturing), or cold (just browsing). "
            "Write personalised, empathetic replies that feel human — never robotic. "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Analyse this Instagram DM and score the lead.\n\n"
            f"Instagram handle: @{ig_handle}\n"
            f"Message: \"{message_text}\"\n"
            f"Intent keywords already detected: {found_keywords}\n\n"
            "Return a JSON object with:\n"
            "  ig_handle: the handle string\n"
            "  status: 'hot', 'warm', or 'cold'\n"
            "  intent_keywords_found: list of detected intent keywords\n"
            "  auto_reply_message: personalised reply under 400 chars (mention TOPPER IAS, be warm)\n"
            "  should_notify_admin: true if status is hot, else false"
        )),
    ]

    logger.info(f"[LeadCaptureAgent] Scoring lead @{ig_handle}, keywords found: {found_keywords}")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        score = LeadScore(**data)
        logger.info(f"[LeadCaptureAgent] @{ig_handle} scored as {score.status}, notify_admin={score.should_notify_admin}")
        return score
    except Exception as e:
        logger.error(f"[LeadCaptureAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


