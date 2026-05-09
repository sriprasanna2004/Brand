"""
Facebook Page posting tool — posts content to the Topper IAS Facebook Page.
Uses Meta Graph API v19.0.
"""
import os
import httpx
from loguru import logger

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _cfg():
    return {
        "page_id": os.getenv("FACEBOOK_PAGE_ID", ""),
        "token": os.getenv("FACEBOOK_PAGE_TOKEN", ""),
    }


async def post_to_facebook(message: str, image_url: str = "") -> str | None:
    """
    Post a text + optional image to the Facebook Page.
    Returns the Facebook post ID or None on failure.
    """
    cfg = _cfg()
    if not cfg["page_id"] or not cfg["token"]:
        logger.warning("[Facebook] PAGE_ID or PAGE_TOKEN not set, skipping")
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if image_url and not image_url.startswith("data:") and "placeholder" not in image_url:
                # Post with photo
                resp = await client.post(
                    f"{GRAPH_BASE}/{cfg['page_id']}/photos",
                    params={
                        "url": image_url,
                        "caption": message[:63206],  # FB caption limit
                        "access_token": cfg["token"],
                    },
                )
            else:
                # Text-only post
                resp = await client.post(
                    f"{GRAPH_BASE}/{cfg['page_id']}/feed",
                    params={
                        "message": message[:63206],
                        "access_token": cfg["token"],
                    },
                )

        if resp.is_success:
            post_id = resp.json().get("id") or resp.json().get("post_id")
            logger.info(f"[Facebook] Posted successfully: {post_id}")
            return post_id
        else:
            logger.error(f"[Facebook] Post failed: {resp.status_code} {resp.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"[Facebook] Exception: {e}")
        return None


async def get_page_insights(post_id: str) -> dict:
    """Get reach and engagement for a Facebook post."""
    cfg = _cfg()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{post_id}/insights",
                params={
                    "metric": "post_impressions,post_engaged_users,post_clicks",
                    "access_token": cfg["token"],
                },
            )
        if resp.is_success:
            data = resp.json().get("data", [])
            result = {}
            for item in data:
                result[item["name"]] = item.get("values", [{}])[-1].get("value", 0)
            return result
    except Exception as e:
        logger.error(f"[Facebook] Insights failed: {e}")
    return {}
