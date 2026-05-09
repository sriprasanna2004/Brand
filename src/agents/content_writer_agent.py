import os
import json
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


class PostContent(BaseModel):
    caption_a: str
    caption_b: str
    hashtags: list[str]  # 15 hashtags
    best_post_time: str


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.8,
    )


def run_content_writer_agent(topic: str, tone: str) -> PostContent:
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are a viral social media writer specialising in UPSC and government exam content for TOPPER IAS. "
            "You write captions that stop the scroll, build community, and drive DMs. "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Write two Instagram caption variants (A/B test) for the topic: '{topic}' with a {tone} tone.\n"
            "Return a JSON object with:\n"
            "  caption_a: primary caption (200-300 chars, includes 1-2 emojis)\n"
            "  caption_b: alternate variant with different hook (200-300 chars)\n"
            "  hashtags: list of exactly 15 relevant hashtags (no # prefix)\n"
            "  best_post_time: recommended posting time as string e.g. '7:00 AM IST'"
        )),
    ]

    logger.info(f"[ContentWriterAgent] Writing captions for topic='{topic}' tone='{tone}'")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        content = PostContent(**data)
        logger.info(f"[ContentWriterAgent] Captions generated, best_post_time={content.best_post_time}")
        return content
    except Exception as e:
        logger.error(f"[ContentWriterAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


