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
        temperature=0.7,
    )


def run_content_writer_agent(topic: str, tone: str) -> PostContent:
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are an expert UPSC educator writing Instagram content for TOPPER IAS. "
            "Your posts teach real exam content — facts, articles, amendments, concepts, dates. "
            "Every caption must have genuine educational value that helps aspirants score marks. "
            "Format rules:\n"
            "- Use numbered lists or bullet points (1. 2. 3. or emoji numbers)\n"
            "- Include specific article numbers, years, or facts\n"
            "- End with a question to boost engagement (Quick test: / Can you answer: / Comment below:)\n"
            "- 150-200 words per caption\n"
            "- 1-2 relevant emojis only (no emoji spam)\n"
            "Example style:\n"
            "'3 Constitutional Bodies you MUST know for UPSC Prelims:\n"
            "1. UPSC — Art 315, conducts Civil Services\n"
            "2. Election Commission — Art 324, independent body\n"
            "3. CAG — Art 148, audits government accounts\n"
            "Key fact: All three are Constitutional bodies but only EC is multi-member by default.\n"
            "Quick test: Which article establishes the Finance Commission?'\n"
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Write two Instagram caption variants (A/B test) for the UPSC topic: '{topic}'.\n"
            f"Tone: {tone}\n\n"
            "Caption A should use a numbered list format with specific facts/articles/dates.\n"
            "Caption B should use a different angle — a common mistake, myth-busting, or comparison format.\n"
            "Both must end with an engagement question.\n\n"
            "Return a JSON object with:\n"
            "  caption_a: educational caption (150-200 words, numbered list, specific facts, ends with question)\n"
            "  caption_b: alternate variant with different hook (150-200 words, ends with question)\n"
            "  hashtags: list of exactly 15 relevant hashtags (no # prefix, mix of broad and niche UPSC tags)\n"
            "  best_post_time: recommended posting time as string e.g. '7:00 AM IST'"
        )),
    ]

    logger.info(f"[ContentWriterAgent] Writing educational captions for topic='{topic}' tone='{tone}'")
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
