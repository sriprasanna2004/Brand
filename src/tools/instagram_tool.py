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


async def create_and_post_trial_story() -> str | None:
    """
    Generate a branded Adaptiq trial promo story image, overlay text,
    upload to R2, then post to Instagram as a Story.
    Returns the Instagram media ID or None on failure.
    """
    import io
    import urllib.parse
    from PIL import Image, ImageDraw, ImageFont

    cfg = _cfg()
    account_id = cfg["account_id"]
    access_token = cfg["access_token"]

    # ── Step 1: Generate 1080x1920 story image via Pollinations ─────────────
    prompt = (
        "Dark purple background #7c3aed, minimal clean design, "
        "abstract geometric shapes, gradient purple to dark, "
        "no people, no text, professional poster style"
    )
    encoded = urllib.parse.quote(prompt)
    poll_url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&nologo=true&seed=99"
    )

    logger.info("[StoryPromo] Generating story image via Pollinations")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(poll_url)
        if not resp.is_success:
            raise Exception(f"Pollinations returned {resp.status_code}")
        image_bytes = resp.content
    except Exception as e:
        logger.error(f"[StoryPromo] Image generation failed: {e}")
        return None

    # ── Step 2: Add text overlay with Pillow ─────────────────────────────────
    def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
        ]
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
        return ImageFont.load_default()

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size  # 1080 x 1920

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Semi-transparent dark overlay for readability
    draw.rectangle([(0, 0), (w, h)], fill=(0, 0, 0, 120))

    # Purple accent bar at top
    draw.rectangle([(0, 0), (w, 10)], fill=(124, 58, 237, 255))
    draw.rectangle([(0, h - 10), (w, h)], fill=(124, 58, 237, 255))

    # Centre Y positions
    center_x = w // 2

    def draw_centered(text, y, font, color):
        try:
            tw = draw.textlength(text, font=font)
        except Exception:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        x = (w - tw) / 2
        draw.text((x, y), text, font=font, fill=color)

    # "TOPPER IAS" — top
    draw_centered("TOPPER IAS", 80, _font(18, bold=True), (255, 255, 255, 200))

    # "Try Adaptiq" — large center
    draw_centered("Try Adaptiq", h // 2 - 120, _font(36, bold=True), (255, 255, 255, 255))

    # "FREE for 7 Days" — purple
    draw_centered("FREE for 7 Days", h // 2 + 10, _font(28, bold=True), (167, 139, 250, 255))

    # "AI-powered UPSC prep" — light gray
    draw_centered("AI-powered UPSC prep", h // 2 + 100, _font(20), (200, 200, 220, 220))

    # Divider line
    line_y = h // 2 + 160
    draw.rectangle([(center_x - 80, line_y), (center_x + 80, line_y + 2)],
                   fill=(124, 58, 237, 180))

    # "Link in bio 👆" — bottom
    draw_centered("Link in bio", h - 160, _font(22, bold=True), (255, 255, 255, 230))

    result = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=92)
    story_bytes = buf.getvalue()

    # ── Step 3: Upload to R2 ─────────────────────────────────────────────────
    try:
        from src.tools.storage_tool import upload_media, generate_filename
        filename = generate_filename("adaptiq-trial-story", content_type="story")
        story_url = upload_media(story_bytes, filename, content_type="image/jpeg")
        logger.info(f"[StoryPromo] Story image uploaded: {story_url}")
    except Exception as e:
        logger.error(f"[StoryPromo] R2 upload failed: {e}")
        return None

    # ── Step 4: Create Instagram Story container ─────────────────────────────
    try:
        container = await _post(
            f"{GRAPH_BASE}/{account_id}/media",
            params={
                "image_url": story_url,
                "media_type": "IMAGE",
                "access_token": access_token,
            },
        )
        container_id = container["id"]
        logger.info(f"[StoryPromo] Story container created: {container_id}")
    except Exception as e:
        logger.error(f"[StoryPromo] Story container creation failed: {e}")
        return None

    # ── Step 5: Publish the story ─────────────────────────────────────────────
    try:
        published = await _post(
            f"{GRAPH_BASE}/{account_id}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": access_token,
            },
        )
        story_id = published["id"]
        logger.info(f"[StoryPromo] Story published: story_id={story_id}")
    except Exception as e:
        logger.error(f"[StoryPromo] Story publish failed: {e}")
        return None

    # ── Step 6: Cross-post to Facebook Page ──────────────────────────────────
    try:
        from src.tools.facebook_tool import post_to_facebook
        fb_caption = (
            "🎯 Try Adaptiq FREE for 7 Days — AI-powered UPSC prep that finds your "
            "weak areas instantly. Link in bio 👆 #UPSC #IAS #Adaptiq #TopperIAS"
        )
        fb_post_id = await post_to_facebook(message=fb_caption, image_url=story_url)
        if fb_post_id:
            logger.info(f"[StoryPromo] Cross-posted to Facebook: {fb_post_id}")
    except Exception as e:
        logger.warning(f"[StoryPromo] Facebook cross-post failed (non-critical): {e}")

    return story_id
