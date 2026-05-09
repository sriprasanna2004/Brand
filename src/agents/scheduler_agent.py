import os
import json
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


class ScheduleDecision(BaseModel):
    post_time: datetime
    reason: str
    expected_reach: int


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.3,
    )


def run_scheduler_agent(analytics_data: list[dict] | None = None) -> ScheduleDecision:
    llm = _get_llm()
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    today_str = now_ist.strftime("%Y-%m-%d")
    current_hour = now_ist.hour

    # Pick next optimal slot: 7:30 PM today if before 7 PM, else 7:30 AM tomorrow
    if current_hour < 19:
        default_time = now_ist.replace(hour=19, minute=30, second=0, microsecond=0)
    else:
        tomorrow = now_ist + timedelta(days=1)
        default_time = tomorrow.replace(hour=7, minute=30, second=0, microsecond=0)

    analytics_block = ""
    if analytics_data:
        analytics_block = f"\n\nHistorical analytics data:\n{json.dumps(analytics_data, indent=2)}"

    messages = [
        SystemMessage(content=(
            "You are a data-driven social media scheduler who maximises reach for UPSC content on Instagram. "
            "UPSC aspirants are most active early morning (6-8 AM IST) and evening (7-10 PM IST). "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Today's date is {today_str}. Current time is {now_ist.strftime('%H:%M')} IST.\n"
            "Pick the single optimal posting time for the next Instagram post — must be in the future.\n"
            f"{analytics_block}\n\n"
            "Return a JSON object with:\n"
            f"  post_time: ISO 8601 datetime string with +05:30 offset, must be after {today_str}\n"
            "  reason: one sentence explaining why this time was chosen\n"
            "  expected_reach: estimated reach as integer"
        )),
    ]

    logger.info("[SchedulerAgent] Calculating optimal post time")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        decision = ScheduleDecision(**data)

        # Validate post_time is in the future — if not, use default
        now_utc = datetime.now(timezone.utc)
        if decision.post_time.replace(tzinfo=timezone.utc) < now_utc:
            logger.warning(f"[SchedulerAgent] LLM returned past date {decision.post_time}, using default {default_time}")
            decision = ScheduleDecision(
                post_time=default_time,
                reason=decision.reason,
                expected_reach=decision.expected_reach,
            )

        logger.info(f"[SchedulerAgent] Scheduled for {decision.post_time}, expected reach={decision.expected_reach}")
        return decision
    except Exception as e:
        logger.error(f"[SchedulerAgent] Failed to parse response: {e}\nRaw: {raw}")
        # Return safe default instead of raising
        return ScheduleDecision(
            post_time=default_time,
            reason="Default optimal evening slot for UPSC audience",
            expected_reach=5000,
        )


