import os
import json
from typing import Optional
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

BRAND_COLORS = {
    "primary": "#7c3aed",      # purple
    "background": "#0f0f1a",   # dark
    "text": "#ffffff",         # white
}


class VisualAsset(BaseModel):
    image_prompt: str
    canva_template_id: Optional[str] = None
    overlay_text: str          # max 10 words
    watermark_text: str = "TOPPER IAS"


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.6,
    )


def run_visual_creator_agent(caption: str, topic: str) -> VisualAsset:
    llm = _get_llm()
    messages = [
        SystemMessage(content=(
            "You are an expert brand visual designer for TOPPER IAS, an IAS coaching institute. "
            f"Brand palette: primary purple {BRAND_COLORS['primary']}, "
            f"dark background {BRAND_COLORS['background']}, white text {BRAND_COLORS['text']}. "
            "Create cinematic, aspirational visuals that inspire UPSC students. "
            "Always return valid JSON only, no markdown, no explanation."
        )),
        HumanMessage(content=(
            f"Create a visual asset spec for this Instagram post.\n"
            f"Topic: {topic}\n"
            f"Caption: {caption}\n\n"
            "Return a JSON object with:\n"
            "  image_prompt: detailed Stability AI prompt (describe scene, lighting, colors, mood — reference brand colors)\n"
            "  canva_template_id: null (we don't have one yet)\n"
            "  overlay_text: short bold text to overlay on image (max 10 words)\n"
            "  watermark_text: always 'TOPPER IAS'"
        )),
    ]

    logger.info(f"[VisualCreatorAgent] Generating visual spec for topic='{topic}'")
    response = llm.invoke(messages)
    raw = response.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        asset = VisualAsset(**data)
        logger.info(f"[VisualCreatorAgent] Visual asset created, overlay='{asset.overlay_text}'")
        return asset
    except Exception as e:
        logger.error(f"[VisualCreatorAgent] Failed to parse response: {e}\nRaw: {raw}")
        raise


