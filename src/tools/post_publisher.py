import os
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import create_engine, select as sa_select
from sqlalchemy.orm import sessionmaker

from src.models import Post, PostStatus


def _get_sync_session():
    db_url = os.getenv("DATABASE_URL_SYNC", "")
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


async def publish_pending_posts() -> list[str]:
    """
    Publish all pending posts whose scheduled_at is now or in the past.
    Uses sync DB for the query/update, async for the Instagram API calls.
    """
    from src.tools.instagram_tool import upload_image_to_instagram, create_single_post

    now = datetime.now(timezone.utc)
    published_ids = []

    db = _get_sync_session()
    try:
        posts = db.execute(
            sa_select(Post).where(
                Post.status == PostStatus.pending,
                Post.scheduled_at <= now,
            )
        ).scalars().all()
        logger.info(f"[Publisher] Found {len(posts)} pending post(s) due for publishing")
    except Exception as e:
        logger.error(f"[Publisher] DB query failed: {e}")
        db.close()
        return []

    for post in posts:
        try:
            if post.image_url.endswith(".mp4"):
                from src.tools.reel_publisher import upload_reel
                ig_post_id = await upload_reel(
                    video_url=post.image_url,
                    caption=post.caption_a,
                )
                if not ig_post_id:
                    raise Exception("Reel video upload returned None")
            else:
                container_id = await upload_image_to_instagram(post.image_url)
                ig_post_id = await create_single_post(container_id, post.caption_a)

            post.status = PostStatus.posted
            post.posted_at = datetime.now(timezone.utc)
            post.ig_post_id = ig_post_id
            db.commit()

            published_ids.append(ig_post_id)
            logger.info(f"[Publisher] Published post {post.id} → ig_post_id={ig_post_id}")

            # Cross-post to Facebook
            try:
                from src.tools.facebook_tool import post_to_facebook
                fb_post_id = await post_to_facebook(
                    message=post.caption_a,
                    image_url=post.image_url,
                )
                if fb_post_id:
                    post.fb_post_id = fb_post_id
                    db.commit()
                    logger.info(f"[Publisher] Cross-posted to Facebook: {fb_post_id}")
            except Exception as fb_err:
                logger.warning(f"[Publisher] Facebook post failed (non-critical): {fb_err}")

        except Exception as e:
            logger.error(f"[Publisher] Failed to publish post {post.id}: {e}")
            try:
                post.status = PostStatus.failed
                db.commit()
            except Exception:
                db.rollback()

    db.close()
    return published_ids


async def publish_single_post(post_id: str) -> bool:
    """Immediately publish a specific post regardless of scheduled_at."""
    from src.tools.instagram_tool import upload_image_to_instagram, create_single_post

    db = _get_sync_session()
    try:
        post = db.execute(
            sa_select(Post).where(Post.id == uuid.UUID(post_id))
        ).scalar_one_or_none()

        if not post:
            logger.error(f"[Publisher] Post {post_id} not found")
            return False

        container_id = await upload_image_to_instagram(post.image_url)
        ig_post_id = await create_single_post(container_id, post.caption_a)

        post.status = PostStatus.posted
        post.posted_at = datetime.now(timezone.utc)
        post.ig_post_id = ig_post_id
        db.commit()

        logger.info(f"[Publisher] Immediately published post {post_id} → ig_post_id={ig_post_id}")

        # Cross-post to Facebook
        try:
            from src.tools.facebook_tool import post_to_facebook
            fb_post_id = await post_to_facebook(message=post.caption_a, image_url=post.image_url)
            if fb_post_id:
                post.fb_post_id = fb_post_id
                db.commit()
                logger.info(f"[Publisher] Cross-posted to Facebook: {fb_post_id}")
        except Exception as fb_err:
            logger.warning(f"[Publisher] Facebook post failed (non-critical): {fb_err}")

        return True

    except Exception as e:
        logger.error(f"[Publisher] Failed to publish post {post_id}: {e}")
        try:
            post.status = PostStatus.failed
            db.commit()
        except Exception:
            db.rollback()
        return False
    finally:
        db.close()
