"""
Analytics tool — pulls Instagram Insights via Meta Graph API
and stores results in PostAnalytics table.
"""
import os
from datetime import datetime, timezone
from loguru import logger
import httpx

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _token() -> str:
    return os.getenv("META_ACCESS_TOKEN", "")


def _account_id() -> str:
    return os.getenv("INSTAGRAM_ACCOUNT_ID", "")


async def get_post_insights(post_id: str) -> dict:
    """Fetch reach, saves, impressions, video_views for a post."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/{post_id}/insights",
            params={
                "metric": "impressions,reach,saved,video_views,total_interactions",
                "access_token": _token(),
            },
        )
    if not resp.is_success:
        logger.warning(f"[Analytics] Insights failed for {post_id}: {resp.status_code}")
        return {}

    result = {"reach": 0, "saves": 0, "impressions": 0, "video_views": 0, "interactions": 0}
    for item in resp.json().get("data", []):
        name = item.get("name")
        value = item.get("values", [{}])[0].get("value", 0)
        if name == "reach":           result["reach"] = value
        elif name == "saved":         result["saves"] = value
        elif name == "impressions":   result["impressions"] = value
        elif name == "video_views":   result["video_views"] = value
        elif name == "total_interactions": result["interactions"] = value
    return result


async def get_account_insights(period: str = "day") -> dict:
    """Fetch account-level reach, impressions, follower count."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/{_account_id()}/insights",
            params={
                "metric": "reach,impressions,profile_views,follower_count",
                "period": period,
                "access_token": _token(),
            },
        )
    if not resp.is_success:
        logger.warning(f"[Analytics] Account insights failed: {resp.status_code} {resp.text[:200]}")
        return {}

    result = {}
    for item in resp.json().get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        result[name] = values[-1].get("value", 0) if values else 0
    logger.info(f"[Analytics] Account insights: {result}")
    return result


async def sync_post_analytics() -> int:
    """Pull insights for all posted posts and update PostAnalytics table."""
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Post, PostStatus, PostAnalytics
    import uuid

    updated = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).where(Post.status == PostStatus.posted, Post.ig_post_id.isnot(None)).order_by(Post.posted_at.desc()).limit(20)
        )
        posts = result.scalars().all()
        logger.info(f"[Analytics] Syncing insights for {len(posts)} posts with ig_post_id")

        for post in posts:
            try:
                insights = await get_post_insights(post.ig_post_id)  # use real Instagram ID
                if not insights:
                    continue

                # Upsert PostAnalytics
                existing = await db.scalar(
                    select(PostAnalytics).where(PostAnalytics.post_id == post.id)
                )
                if existing:
                    existing.reach = insights.get("reach", 0)
                    existing.saves = insights.get("saves", 0)
                    existing.link_clicks = insights.get("interactions", 0)
                    existing.story_views = insights.get("video_views", 0)
                    existing.recorded_at = datetime.now(timezone.utc)
                else:
                    pa = PostAnalytics(
                        id=uuid.uuid4(),
                        post_id=post.id,
                        reach=insights.get("reach", 0),
                        saves=insights.get("saves", 0),
                        dm_triggers=0,
                        story_views=insights.get("video_views", 0),
                        link_clicks=insights.get("interactions", 0),
                    )
                    db.add(pa)
                updated += 1
            except Exception as e:
                logger.error(f"[Analytics] Failed for post {post.id}: {e}")

        await db.commit()
    logger.info(f"[Analytics] Synced {updated} posts")
    return updated


async def get_top_performing_posts(limit: int = 5) -> list[dict]:
    """Return top posts by reach from PostAnalytics."""
    from sqlalchemy import select, text
    from src.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(text("""
                SELECT p.id::text, LEFT(p.caption_a, 60) as caption,
                       p.platform, pa.reach, pa.saves, pa.link_clicks,
                       p.posted_at::text
                FROM post_analytics pa
                JOIN posts p ON pa.post_id = p.id
                ORDER BY pa.reach DESC
                LIMIT :limit
            """), {"limit": limit})
            return [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"[Analytics] get_top_performing_posts failed: {e}")
            return []
