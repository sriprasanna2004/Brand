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


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.7,
    )


def _base_system_prompt() -> str:
    base = (
        "You are an expert UPSC content strategist for TOPPER IAS. "
        "You know exactly what resonates with UPSC aspirants — motivation, "
        "study tips, current affairs, and exam strategy. "
        "Always return valid JSON only, no markdown, no explanation."
    )
    if _redis:
        try:
            perf_context = _redis.get("strategy:performance_context")
            if perf_context:
                base += f"\n\nPerformance data from last week:\n{perf_context}"
        except Exception as e:
            pass  # Redis unavailable — use default prompt
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

    llm = _get_llm()
    messages = [
        SystemMessage(content=_base_system_prompt()),
        HumanMessage(content=(
            f"Create a 7-day Instagram content plan starting {week_start}. "
            f"Return a JSON object with key 'topics' containing a list of 7 objects, "
            f"each with: day (1-7), topic (string), "
            f"content_type (one of: post, reel, carousel, story), "
            f"tone (one of: motivational, educational, tactical)."
            f"{context_block}"
        )),
    ]

    logger.info(f"[StrategyAgent] Generating content plan for week starting {week_start}")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        topics = data.get("topics", data) if isinstance(data, dict) else data
        plan = ContentPlan(week_start=week_start, topics=topics)
        logger.info(f"[StrategyAgent] Plan generated with {len(plan.topics)} topics")
        return plan
    except Exception as e:
        logger.error(f"[StrategyAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


