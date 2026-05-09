import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import Post, PostStatus
from src.tools.instagram_tool import upload_image_to_instagram, create_single_post


async def publish_pending_posts() -> list[str]:
    """Publish all pending posts whose scheduled_at is now or in the past."""
    now = datetime.now(timezone.utc)
    published_ids = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).where(
                Post.status == PostStatus.pending,
                Post.scheduled_at <= now,
            )
        )
        posts = result.scalars().all()
        logger.info(f"[Publisher] Found {len(posts)} pending post(s) due for publishing")

        for post in posts:
            try:
                # Reel platform with image URL → post as image with reel caption
                # Reel platform with .mp4 URL → post as actual video reel
                if post.image_url.endswith(".mp4"):
                    from src.tools.reel_publisher import upload_reel
                    ig_post_id = await upload_reel(
                        video_url=post.image_url,
                        caption=post.caption_a,
                    )
                    if not ig_post_id:
                        raise Exception("Reel video upload returned None")
                else:
                    # Image post (including reel-script posts with image)
                    container_id = await upload_image_to_instagram(post.image_url)
                    ig_post_id = await create_single_post(container_id, post.caption_a)

                post.status = PostStatus.posted
                post.posted_at = datetime.now(timezone.utc)
                post.ig_post_id = ig_post_id
                await db.commit()

                published_ids.append(ig_post_id)
                logger.info(f"[Publisher] Published post {post.id} → ig_post_id={ig_post_id}")

                # Also post to Facebook Page
                try:
                    from src.tools.facebook_tool import post_to_facebook
                    fb_post_id = await post_to_facebook(
                        message=post.caption_a,
                        image_url=post.image_url,
                    )
                    if fb_post_id:
                        logger.info(f"[Publisher] Also posted to Facebook: {fb_post_id}")
                except Exception as fb_err:
                    logger.warning(f"[Publisher] Facebook post failed (non-critical): {fb_err}")

            except Exception as e:
                logger.error(f"[Publisher] Failed to publish post {post.id}: {e}")
                post.status = PostStatus.failed
                await db.commit()

    return published_ids


async def publish_single_post(post_id: str) -> bool:
    """Immediately publish a specific post regardless of scheduled_at."""
    async with AsyncSessionLocal() as db:
        post = await db.scalar(select(Post).where(Post.id == uuid.UUID(post_id)))
        if not post:
            logger.error(f"[Publisher] Post {post_id} not found")
            return False

        try:
            container_id = await upload_image_to_instagram(post.image_url)
            ig_post_id = await create_single_post(container_id, post.caption_a)

            post.status = PostStatus.posted
            post.posted_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"[Publisher] Immediately published post {post_id} → ig_post_id={ig_post_id}")

            # Also post to Facebook
            try:
                from src.tools.facebook_tool import post_to_facebook
                fb_post_id = await post_to_facebook(message=post.caption_a, image_url=post.image_url)
                if fb_post_id:
                    logger.info(f"[Publisher] Also posted to Facebook: {fb_post_id}")
            except Exception as fb_err:
                logger.warning(f"[Publisher] Facebook post failed (non-critical): {fb_err}")

            return True

        except Exception as e:
            logger.error(f"[Publisher] Failed to publish post {post_id}: {e}")
            post.status = PostStatus.failed
            await db.commit()
            return False
