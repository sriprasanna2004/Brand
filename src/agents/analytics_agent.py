import os
import json
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


class AnalyticsSummary(BaseModel):
    top_performers: list[dict]          # 3 dicts
    bottom_performers: list[dict]       # 3 dicts
    recommended_content_mix: dict       # e.g. {"reel": 40, "carousel": 30, ...}
    weekly_reach_total: int
    weekly_leads_generated: int
    insight_text: str                   # 2-3 sentences


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.3,
    )


def run_analytics_agent(posts_data: list[dict]) -> AnalyticsSummary:
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are a data scientist specialising in social media analytics for educational brands. "
            "Analyse Instagram post performance data and extract clear, actionable insights. "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            "Analyse this week's Instagram post performance data for TOPPER IAS.\n\n"
            f"Posts data:\n{json.dumps(posts_data, indent=2)}\n\n"
            "Return a JSON object with:\n"
            "  top_performers: list of 3 dicts identifying best posts (include content_type, reach, reason)\n"
            "  bottom_performers: list of 3 dicts identifying worst posts (include content_type, reach, reason)\n"
            "  recommended_content_mix: dict with content_type keys and percentage values (must sum to 100)\n"
            "  weekly_reach_total: sum of all reach values as integer\n"
            "  weekly_leads_generated: sum of all dm_triggers as integer\n"
            "  insight_text: 2-3 sentences summarising key findings and next week's recommendation"
        )),
    ]

    logger.info(f"[AnalyticsAgent] Analysing {len(posts_data)} posts")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        summary = AnalyticsSummary(**data)
        logger.info(
            f"[AnalyticsAgent] Analysis complete, "
            f"total_reach={summary.weekly_reach_total}, leads={summary.weekly_leads_generated}"
        )
        return summary
    except Exception as e:
        logger.error(f"[AnalyticsAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


