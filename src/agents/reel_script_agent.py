import os
import json
from typing import Literal
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


class ReelScript(BaseModel):
    hook: str                       # max 10 words, 0-3 sec
    value_points: list[str]         # exactly 3 points, 3-25 sec
    cta: str                        # 25-30 sec
    caption: str
    duration_seconds: Literal[30, 60]


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.8,
    )


def run_reel_script_agent(topic: str, tone: str = "motivational") -> ReelScript:
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are a YouTube and Instagram Reels expert for TOPPER IAS educational content. "
            "You write scripts that hook viewers in 3 seconds, deliver dense value, and drive action. "
            "Structure: Hook (0-3s) → Value (3-25s) → CTA (25-30s). "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Write a viral Reels script for topic: '{topic}' with a {tone} tone.\n\n"
            "Return a JSON object with:\n"
            "  hook: opening line max 10 words (must stop the scroll)\n"
            "  value_points: list of exactly 3 punchy value statements (3-25 sec segment)\n"
            "  cta: closing call-to-action (25-30 sec, drive DMs or saves)\n"
            "  caption: Instagram caption for the reel (150-200 chars)\n"
            "  duration_seconds: 30 or 60 (choose based on content depth)"
        )),
    ]

    logger.info(f"[ReelScriptAgent] Writing reel script for topic='{topic}' tone='{tone}'")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        script = ReelScript(**data)
        logger.info(f"[ReelScriptAgent] Script ready, duration={script.duration_seconds}s, hook='{script.hook}'")
        return script
    except Exception as e:
        logger.error(f"[ReelScriptAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


