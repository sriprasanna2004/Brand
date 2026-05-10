import os
import json
from datetime import date
from typing import Optional
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

try:
    from src.redis_client import redis_client
    _redis = redis_client()
except Exception:
    _redis = None


class ContentPlan(BaseModel):
    week_start: date
    topics: list[dict]  # 7 dicts: day, topic, content_type, tone


# ---------------------------------------------------------------------------
# Fixed 7-day educational content calendar
# Each day has a subject focus — this ensures consistent, curriculum-aligned
# content that UPSC aspirants can follow week after week.
# ---------------------------------------------------------------------------

WEEKLY_SCHEDULE = [
    {
        "day_name": "Monday",
        "subject": "Polity",
        "focus": "Constitutional Bodies, Fundamental Rights, DPSP, Amendments, Parliament, Judiciary",
        "content_type": "carousel",
        "tone": "educational",
    },
    {
        "day_name": "Tuesday",
        "subject": "History",
        "focus": "Modern India, Freedom Movement, Ancient/Medieval India, Important dates and personalities",
        "content_type": "post",
        "tone": "educational",
    },
    {
        "day_name": "Wednesday",
        "subject": "Economy",
        "focus": "Budget concepts, GDP, Inflation, Banking, RBI, Five Year Plans, Economic Survey",
        "content_type": "carousel",
        "tone": "educational",
    },
    {
        "day_name": "Thursday",
        "subject": "Geography",
        "focus": "Physical features of India, Rivers, Climate, Soil types, Natural resources, World Geography",
        "content_type": "post",
        "tone": "educational",
    },
    {
        "day_name": "Friday",
        "subject": "Current Affairs",
        "focus": "Weekly recap of important national/international events relevant to UPSC",
        "content_type": "reel",
        "tone": "educational",
    },
    {
        "day_name": "Saturday",
        "subject": "Science & Technology",
        "focus": "Space missions, Defence tech, Environment, Biodiversity, Health schemes",
        "content_type": "post",
        "tone": "educational",
    },
    {
        "day_name": "Sunday",
        "subject": "Motivation + Success Story",
        "focus": "Topper success story, study strategy, mindset tips, how to crack UPSC",
        "content_type": "reel",
        "tone": "motivational",
    },
]


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.7,
    )


def _base_system_prompt() -> str:
    base = (
        "You are an expert UPSC content strategist for TOPPER IAS. "
        "You plan specific, educational content that teaches real exam topics — "
        "not generic motivation. Each topic must be a specific, teachable concept "
        "that an aspirant can learn from in 2 minutes. "
        "Examples of good topics: 'Constitutional Bodies under Article 315-323', "
        "'Quit India Movement 1942 — Key Facts', 'RBI Monetary Policy Tools Explained', "
        "'Himalayan Rivers vs Peninsular Rivers'. "
        "Always return valid JSON only, no markdown, no explanation."
    )
    if _redis:
        try:
            perf_context = _redis.get("strategy:performance_context")
            if perf_context:
                base += f"\n\nPerformance data from last week:\n{perf_context}"
        except Exception:
            pass
    return base


def run_strategy_agent(week_start: Optional[date] = None) -> ContentPlan:
    if week_start is None:
        week_start = date.today()

    performance_summary = None
    if _redis:
        try:
            performance_summary = _redis.get("analytics:weekly_summary")
        except Exception as e:
            logger.warning(f"Could not read Redis analytics summary: {e}")

    context_block = ""
    if performance_summary:
        context_block = f"\n\nPrevious week performance summary:\n{performance_summary}"

    # Build the schedule prompt with day-by-day subject assignments
    schedule_text = "\n".join([
        f"Day {i+1} ({s['day_name']}): Subject={s['subject']}, "
        f"Focus areas={s['focus']}, "
        f"Format={s['content_type']}, Tone={s['tone']}"
        for i, s in enumerate(WEEKLY_SCHEDULE)
    ])

    llm = _get_llm()
    messages = [
        SystemMessage(content=_base_system_prompt()),
        HumanMessage(content=(
            f"Create a 7-day Instagram content plan for TOPPER IAS starting {week_start}.\n\n"
            f"Follow this fixed subject schedule:\n{schedule_text}\n\n"
            f"For each day, generate a SPECIFIC educational topic within that subject. "
            f"The topic must be a concrete, teachable concept — not generic. "
            f"For example, instead of 'Polity' write 'Writ Jurisdiction of Supreme Court under Article 32'.\n\n"
            f"Return a JSON object with key 'topics' containing a list of 7 objects, "
            f"each with: day (1-7), topic (specific educational topic string), "
            f"content_type (use the format from the schedule above), "
            f"tone (use the tone from the schedule above), "
            f"subject (the subject area)."
            f"{context_block}"
        )),
    ]

    logger.info(f"[StrategyAgent] Generating educational content plan for week starting {week_start}")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        topics = data.get("topics", data) if isinstance(data, dict) else data
        plan = ContentPlan(week_start=week_start, topics=topics)
        logger.info(f"[StrategyAgent] Plan generated with {len(plan.topics)} topics")
        # Log the topics for visibility
        for t in plan.topics:
            logger.info(f"  Day {t.get('day')}: [{t.get('subject', t.get('tone', ''))}] {t.get('topic')}")
        return plan
    except Exception as e:
        logger.error(f"[StrategyAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise
