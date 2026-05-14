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

# ---------------------------------------------------------------------------
# Real TOPPER IAS product details — used in auto-reply messages
# ---------------------------------------------------------------------------
PRODUCT_INFO = """
TOPPER IAS — UPSC Coaching Institute, Coimbatore

COURSES & FEES:
1. Full Batch (Prelims + Mains + Interview) — ₹25,000
   - Complete UPSC preparation, all subjects covered
   - Daily classes + weekly tests + mentorship

2. Prelims Batch — ₹8,000
   - Focus on GS Paper 1 & 2 (CSAT)
   - 3-month intensive program

3. Test Series — ₹3,000
   - 20 full-length mock tests
   - Detailed performance analysis

4. Mentorship Program — ₹15,000
   - 1-on-1 guidance from IAS officers
   - Personalised study plan

FREE TRIAL:
- Adaptiq AI app — 7 days free
- Finds your weak areas, builds personalised study plan
- Link: https://hospitable-comfort-production.up.railway.app/adaptiq

CONTACT:
- Instagram: @content1.topperias
- Telegram: @brandiq_topper_bot
- Location: Coimbatore, Tamil Nadu
"""


class LeadStatusEnum(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class LeadScore(BaseModel):
    ig_handle: str
    status: LeadStatusEnum
    intent_keywords_found: list[str]
    auto_reply_message: str          # personalised, under 500 chars
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
            "You are a friendly admissions counsellor for TOPPER IAS UPSC coaching institute. "
            "When someone asks about fees, batches, or admission — give them the ACTUAL details immediately. "
            "Don't say 'our team will get back to you' — give real information from the product details provided. "
            "Score leads as hot (ready to buy), warm (interested), or cold (just browsing). "
            "Write replies that feel warm and human, include specific fees/course info when asked. "
            "Always return valid JSON only, no markdown, no explanation.\n\n"
            f"TOPPER IAS Product Information:\n{PRODUCT_INFO}"
        )),
        HumanMessage(content=(
            f"Analyse this DM and score the lead. Write an immediate helpful reply.\n\n"
            f"Handle: @{ig_handle}\n"
            f"Message: \"{message_text}\"\n"
            f"Intent keywords detected: {found_keywords}\n\n"
            "Return a JSON object with:\n"
            "  ig_handle: the handle string\n"
            "  status: 'hot', 'warm', or 'cold'\n"
            "  intent_keywords_found: list of detected intent keywords\n"
            "  auto_reply_message: immediate helpful reply under 500 chars — "
            "if they asked about fees/batch/admission, include ACTUAL prices and course names. "
            "End with a CTA like 'Reply YES to get the full brochure' or 'Try Adaptiq free: [link]'\n"
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
