import asyncio
import os
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from pydantic import BaseModel

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _cfg():
    return {
        "access_token": os.getenv("META_ACCESS_TOKEN", ""),
        "account_id": os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
        "app_id": os.getenv("META_APP_ID", ""),
        "app_secret": os.getenv("META_APP_SECRET", ""),
    }


class InstagramPost(BaseModel):
    post_id: str
    caption: str
    image_url: str
    posted_at: datetime
    reach: int = 0
    saves: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _post(url: str, **kwargs) -> dict:
    """POST with one retry on any HTTP error."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(2):
            resp = await client.post(url, **kwargs)
            if resp.is_success:
                return resp.json()
            if attempt == 0:
                logger.warning(f"[Instagram] POST {url} failed ({resp.status_code}), retrying in 5s...")
                await asyncio.sleep(5)
            else:
                raise Exception(
                    f"Instagram API POST failed after 2 attempts: "
                    f"status={resp.status_code} body={resp.text}"
                )


async def _get(url: str, params: dict) -> dict:
    """GET with one retry on any HTTP error."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(2):
            resp = await client.get(url, params=params)
            if resp.is_success:
                return resp.json()
            if attempt == 0:
                logger.warning(f"[Instagram] GET {url} failed ({resp.status_code}), retrying in 5s...")
                await asyncio.sleep(5)
            else:
                raise Exception(
                    f"Instagram API GET failed after 2 attempts: "
                    f"status={resp.status_code} body={resp.text}"
                )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

async def upload_image_to_instagram(image_url: str) -> str:
    cfg = _cfg()
    data = await _post(
        f"{GRAPH_BASE}/{cfg['account_id']}/media",
        params={
            "image_url": image_url,
            "media_type": "IMAGE",
            "access_token": cfg["access_token"],
        },
    )
    container_id = data["id"]
    logger.info(f"[Instagram] Image container created: {container_id}")
    return container_id


async def create_single_post(container_id: str, caption: str) -> str:
    cfg = _cfg()
    data = await _post(
        f"{GRAPH_BASE}/{cfg['account_id']}/media_publish",
        params={
            "creation_id": container_id,
            "caption": caption,
            "access_token": cfg["access_token"],
        },
    )
    post_id = data["id"]
    logger.info(f"[Instagram] Post published successfully: post_id={post_id}")
    return post_id


async def create_carousel_post(image_urls: list[str], caption: str) -> str:
    cfg = _cfg()

    # Step 1: create a carousel item container for each image
    container_ids = []
    for url in image_urls:
        data = await _post(
            f"{GRAPH_BASE}/{cfg['account_id']}/media",
            params={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": cfg["access_token"],
            },
        )
        container_ids.append(data["id"])
        logger.info(f"[Instagram] Carousel item container: {data['id']}")

    # Step 2: create carousel container
    carousel = await _post(
        f"{GRAPH_BASE}/{cfg['account_id']}/media",
        params={
            "media_type": "CAROUSEL",
            "children": ",".join(container_ids),
            "caption": caption,
            "access_token": cfg["access_token"],
        },
    )
    carousel_id = carousel["id"]
    logger.info(f"[Instagram] Carousel container created: {carousel_id}")

    # Step 3: publish
    post_id = await create_single_post(carousel_id, caption="")
    logger.info(f"[Instagram] Carousel published: post_id={post_id}")
    return post_id


async def get_post_insights(post_id: str) -> dict:
    cfg = _cfg()
    data = await _get(
        f"{GRAPH_BASE}/{post_id}/insights",
        params={
            "metric": "impressions,reach,saved,video_views",
            "access_token": cfg["access_token"],
        },
    )
    result = {"reach": 0, "saves": 0, "impressions": 0, "video_views": 0}
    for item in data.get("data", []):
        name = item.get("name")
        value = item.get("values", [{}])[0].get("value", 0)
        if name == "reach":
            result["reach"] = value
        elif name == "saved":
            result["saves"] = value
        elif name == "impressions":
            result["impressions"] = value
        elif name == "video_views":
            result["video_views"] = value
    logger.info(f"[Instagram] Insights for {post_id}: {result}")
    return result


async def send_dm(ig_user_id: str, message: str) -> bool:
    cfg = _cfg()
    try:
        await _post(
            f"{GRAPH_BASE}/{cfg['account_id']}/messages",
            json={
                "recipient": {"id": ig_user_id},
                "message": {"text": message},
            },
            params={"access_token": cfg["access_token"]},
        )
        logger.info(f"[Instagram] DM sent to {ig_user_id}")
        return True
    except Exception as e:
        logger.error(f"[Instagram] DM failed to {ig_user_id}: {e}")
        return False


async def refresh_token() -> str:
    cfg = _cfg()
    data = await _get(
        f"{GRAPH_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": cfg["app_id"],
            "client_secret": cfg["app_secret"],
            "fb_exchange_token": cfg["access_token"],
        },
    )
    new_token = data["access_token"]
    os.environ["META_ACCESS_TOKEN"] = new_token
    logger.info("[Instagram] Access token refreshed successfully")
    return new_token
