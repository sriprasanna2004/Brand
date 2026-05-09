import os
import json
from typing import Optional
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

# ---------------------------------------------------------------------------
# Day context — maps exactly to the event-driven nurture spec:
#
#  Day 0  → Instant Instagram auto-reply (handled in webhook_handler, not here)
#  Day 3  → WhatsApp: "Try Adaptiq free for 7 days"
#  Day 7  → WhatsApp: "Batch starting soon — limited seats"
#  Day 14 → WhatsApp: Final nudge with topper testimonial
# ---------------------------------------------------------------------------

DAY_CONTEXT = {
    3: {
        "focus": (
            "Introduce Adaptiq — TOPPER IAS's AI-powered UPSC prep app. "
            "Offer a free 7-day trial. Highlight the personalised weak area analysis feature. "
            "Include the trial link: https://adaptiq.app/trial"
        ),
        "tone": "friendly and helpful, like a senior who found a shortcut",
        "cta": "https://adaptiq.app/trial",
    },
    7: {
        "focus": (
            "Create urgency — the next TOPPER IAS batch is starting soon and seats are limited. "
            "Mention that only a few spots remain. "
            "Include the admission link: https://topperias.com/admission"
        ),
        "tone": "warm but urgent — FOMO without being pushy",
        "cta": "https://topperias.com/admission",
    },
    14: {
        "focus": (
            "Final nudge. Share a short, inspiring topper testimonial (e.g. Priya Sharma, AIR 47, "
            "who joined TOPPER IAS and cracked UPSC in her first attempt). "
            "Make it feel like this could be their story too. "
            "Include the direct admission link: https://topperias.com/join"
        ),
        "tone": "emotional and inspiring — paint a picture of their success",
        "cta": "https://topperias.com/join",
    },
}


class NurtureMessage(BaseModel):
    message: str            # under 500 chars, WhatsApp-ready
    template_name: str      # snake_case
    variables: dict         # dynamic vars used in the message
    cta_link: Optional[str] = None


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.7,
    )


def run_lead_nurture_agent(
    lead_name: str,
    day_number: int,
    lead_status: str,
    intent_keywords: list[str] | None = None,
) -> NurtureMessage:
    if day_number not in DAY_CONTEXT:
        raise ValueError(f"day_number must be one of {list(DAY_CONTEXT.keys())}, got {day_number}")

    ctx = DAY_CONTEXT[day_number]
    keywords_str = ", ".join(intent_keywords) if intent_keywords else "fees, batch"

    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are an empathetic student counsellor for TOPPER IAS who understands the UPSC journey deeply. "
            "Write WhatsApp messages that feel personal, warm, and motivating — never salesy or pushy. "
            "The lead originally asked about: {keywords}. Reference this naturally if it fits. "
            "Keep messages under 500 characters. "
            "Always return valid JSON only, no markdown, no explanation."
        ).format(keywords=keywords_str)),
        HumanMessage(content=(
            f"Write a Day {day_number} WhatsApp nurture message for a UPSC aspirant.\n\n"
            f"Lead name: {lead_name}\n"
            f"Lead status: {lead_status}\n"
            f"Original intent: {keywords_str}\n"
            f"Day {day_number} focus: {ctx['focus']}\n"
            f"Tone: {ctx['tone']}\n\n"
            "Return a JSON object with:\n"
            "  message: WhatsApp message text (under 500 chars, use lead name, feel personal, include CTA link naturally)\n"
            f"  template_name: 'day_{day_number}_nurture'\n"
            "  variables: dict of dynamic variables used (e.g. {{\"name\": \"{lead_name}\", \"cta\": \"{cta}\"}})\n"
            f"  cta_link: '{ctx['cta']}'"
        ).format(lead_name=lead_name, cta=ctx["cta"])),
    ]

    logger.info(
        f"[LeadNurtureAgent] Generating Day {day_number} message for {lead_name} "
        f"(status={lead_status}, keywords={keywords_str})"
    )
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        msg = NurtureMessage(**data)
        logger.info(f"[LeadNurtureAgent] Message ready, template={msg.template_name}, cta={msg.cta_link}")
        return msg
    except Exception as e:
        logger.error(f"[LeadNurtureAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


