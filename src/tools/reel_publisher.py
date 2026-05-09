"""
Reel publisher — uploads video to Instagram Reels via Meta Graph API.
Flow: upload video → create reel container → publish.
"""
import os
import asyncio
from loguru import logger
import httpx

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _cfg():
    return {
        "token": os.getenv("META_ACCESS_TOKEN", ""),
        "account_id": os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
    }


async def _wait_for_container(container_id: str, max_wait: int = 120) -> bool:
    """Poll until container status is FINISHED."""
    cfg = _cfg()
    for _ in range(max_wait // 5):
        await asyncio.sleep(5)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": cfg["token"]},
            )
        if resp.is_success:
            status = resp.json().get("status_code", "")
            if status == "FINISHED":
                return True
            if status == "ERROR":
                logger.error(f"[Reel] Container {container_id} errored")
                return False
    logger.warning(f"[Reel] Container {container_id} timed out")
    return False


async def upload_reel(
    video_url: str,
    caption: str,
    cover_url: str = "",
    share_to_feed: bool = True,
) -> str | None:
    """
    Upload a reel to Instagram.
    video_url: publicly accessible URL to the video file
    Returns: Instagram media ID or None on failure
    """
    cfg = _cfg()

    # Step 1: Create reel container
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "access_token": cfg["token"],
    }
    if cover_url:
        params["cover_url"] = cover_url

    logger.info(f"[Reel] Creating container for video: {video_url[:60]}")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/{cfg['account_id']}/media",
            params=params,
        )

    if not resp.is_success:
        logger.error(f"[Reel] Container creation failed: {resp.status_code} {resp.text[:200]}")
        return None

    container_id = resp.json().get("id")
    logger.info(f"[Reel] Container created: {container_id}, waiting for processing...")

    # Step 2: Wait for video processing
    ready = await _wait_for_container(container_id)
    if not ready:
        return None

    # Step 3: Publish
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/{cfg['account_id']}/media_publish",
            params={"creation_id": container_id, "access_token": cfg["token"]},
        )

    if not resp.is_success:
        logger.error(f"[Reel] Publish failed: {resp.status_code} {resp.text[:200]}")
        return None

    media_id = resp.json().get("id")
    logger.info(f"[Reel] Published successfully: media_id={media_id}")
    return media_id


async def create_reel_from_script(
    script: dict,
    video_url: str,
    topic: str,
) -> dict:
    """
    Takes a ReelScript dict and a video URL, publishes to Instagram.
    script: output from run_reel_script_agent()
    Returns result dict with media_id and status.
    """
    caption = script.get("caption", "")
    hook = script.get("hook", "")
    cta = script.get("cta", "")
    full_caption = f"{hook}\n\n{caption}\n\n{cta}\n\n#UPSC #IAS #TopperIAS #Adaptiq"

    media_id = await upload_reel(
        video_url=video_url,
        caption=full_caption[:2200],  # Instagram caption limit
    )

    return {
        "status": "published" if media_id else "failed",
        "media_id": media_id,
        "topic": topic,
        "caption_preview": full_caption[:80],
    }
