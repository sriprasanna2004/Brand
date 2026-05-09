"""
YouTube Shorts pipeline — generates script, creates thumbnail,
and prepares upload package for YouTube Shorts.
Uses ReelScriptAgent for script, Canva tool for thumbnail.
Actual upload requires YouTube Data API v3 OAuth (manual setup).
"""
import os
import uuid
from datetime import datetime, timezone
from loguru import logger

from src.agents.reel_script_agent import run_reel_script_agent
from src.tools.canva_tool import create_quote_card, upload_canva_image
from src.tools.storage_tool import generate_filename


async def generate_shorts_package(topic: str, tone: str = "motivational") -> dict:
    """
    Generate a complete YouTube Shorts package:
    - Script (hook + value points + CTA)
    - Thumbnail image
    - Title and description
    - Tags
    Returns dict with all assets ready for upload.
    """
    logger.info(f"[YouTube] Generating Shorts package for topic='{topic}'")

    # Step 1: Generate script
    script = run_reel_script_agent(topic=topic, tone=tone)
    logger.info(f"[YouTube] Script generated, duration={script.duration_seconds}s")

    # Step 2: Generate thumbnail
    thumbnail_bytes = create_quote_card(
        headline=script.hook,
        subtext=f"UPSC Tips | TOPPER IAS",
        watermark="TOPPER IAS",
    )
    filename = generate_filename(topic, content_type="yt-thumb")
    thumbnail_url = await upload_canva_image(thumbnail_bytes, filename)
    logger.info(f"[YouTube] Thumbnail uploaded: {thumbnail_url}")

    # Step 3: Build title and description
    title = f"{script.hook[:70]} | UPSC {datetime.now().year}"
    description = (
        f"{script.hook}\n\n"
        + "\n".join(f"✅ {pt}" for pt in script.value_points)
        + f"\n\n{script.cta}\n\n"
        "📱 Download Adaptiq App: https://adaptiq.app\n"
        "🎓 Join TOPPER IAS: https://topperias.com\n\n"
        "#UPSC #IAS #Shorts #UPSCPreparation #TopperIAS #Adaptiq #CivilServices"
    )

    tags = [
        "UPSC", "IAS", "Shorts", "UPSCPreparation", "CivilServices",
        "TopperIAS", "Adaptiq", "UPSCTips", "IASPreparation", "GovernmentExams",
        topic.replace(" ", ""), "StudyMotivation", "ExamPrep",
    ]

    package = {
        "title": title,
        "description": description[:5000],
        "tags": tags,
        "thumbnail_url": thumbnail_url,
        "script": {
            "hook": script.hook,
            "value_points": script.value_points,
            "cta": script.cta,
            "duration_seconds": script.duration_seconds,
        },
        "caption_for_instagram": script.caption,
        "topic": topic,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"[YouTube] Shorts package ready for topic='{topic}'")
    return package


async def schedule_shorts_batch(topics: list[str]) -> list[dict]:
    """Generate Shorts packages for multiple topics."""
    packages = []
    for topic in topics:
        try:
            pkg = await generate_shorts_package(topic)
            packages.append(pkg)
        except Exception as e:
            logger.error(f"[YouTube] Failed for topic '{topic}': {e}")
            packages.append({"topic": topic, "status": "failed", "error": str(e)})
    return packages
