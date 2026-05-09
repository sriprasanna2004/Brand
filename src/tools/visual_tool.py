import base64
import io
import os

import httpx
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from src.tools.storage_tool import generate_filename, upload_media

STABILITY_API_URL = (
    "https://api.stability.ai/v1/generation/"
    "stable-diffusion-xl-1024-v1-0/text-to-image"
)
BRAND_SUFFIX = (
    "educational poster style, purple and dark theme, "
    "professional, UPSC exam preparation, no text overlays"
)


async def generate_image(prompt: str, topic: str) -> str:
    api_key = os.getenv("STABILITY_API_KEY", "")

    # Try Stability AI first if credits available
    if api_key and api_key != "REPLACE_ME":
        try:
            full_prompt = f"{prompt}, {BRAND_SUFFIX}"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    STABILITY_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={
                        "text_prompts": [{"text": full_prompt, "weight": 1.0}],
                        "cfg_scale": 7,
                        "height": 1024,
                        "width": 1024,
                        "samples": 1,
                        "steps": 30,
                    },
                )
            if resp.is_success:
                data = resp.json()
                image_b64 = data["artifacts"][0]["base64"]
                image_bytes = base64.b64decode(image_b64)
                watermarked = add_watermark(image_bytes)
                r2_account = os.getenv("R2_ACCOUNT_ID", "REPLACE_ME")
                if r2_account and r2_account != "REPLACE_ME":
                    try:
                        from src.tools.storage_tool import generate_filename, upload_media
                        filename = generate_filename(topic, content_type="post")
                        url = upload_media(watermarked, filename, content_type="image/jpeg")
                        logger.info(f"[Visual] Stability AI image uploaded to R2: {url}")
                        return url
                    except Exception as e:
                        logger.warning(f"[Visual] R2 upload failed: {e}")
                b64 = base64.b64encode(watermarked).decode()
                return f"data:image/jpeg;base64,{b64}"
            elif resp.status_code == 429 or "insufficient_balance" in resp.text:
                logger.warning("[Visual] Stability AI out of credits, falling back to Pollinations")
            else:
                logger.warning(f"[Visual] Stability AI error {resp.status_code}, falling back")
        except Exception as e:
            logger.warning(f"[Visual] Stability AI exception: {e}, falling back")

    # Free fallback: Pollinations.AI — no API key, no signup needed
    return await _generate_pollinations(prompt, topic)


async def _generate_pollinations(prompt: str, topic: str) -> str:
    """Generate image using Pollinations.AI (completely free, no key needed)."""
    import urllib.parse
    full_prompt = f"{prompt}, {BRAND_SUFFIX}, dark purple theme, TOPPER IAS"
    encoded = urllib.parse.quote(full_prompt)
    # Pollinations returns a real image at this URL
    image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed=42"

    logger.info(f"[Visual] Generating via Pollinations.AI for topic='{topic}'")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(image_url)
        if not resp.is_success:
            raise Exception(f"Pollinations returned {resp.status_code}")

        image_bytes = resp.content
        watermarked = add_watermark(image_bytes)

        # Upload to R2 if configured
        r2_account = os.getenv("R2_ACCOUNT_ID", "REPLACE_ME")
        if r2_account and r2_account != "REPLACE_ME":
            try:
                from src.tools.storage_tool import generate_filename, upload_media
                filename = generate_filename(topic, content_type="post")
                url = upload_media(watermarked, filename, content_type="image/jpeg")
                logger.info(f"[Visual] Pollinations image uploaded to R2: {url}")
                return url
            except Exception as e:
                logger.warning(f"[Visual] R2 upload failed: {e}")

        # Return the Pollinations URL directly (Instagram can fetch it)
        logger.info(f"[Visual] Using Pollinations URL directly: {image_url[:80]}")
        return image_url

    except Exception as e:
        logger.error(f"[Visual] Pollinations failed: {e}")
        # Last resort: Canva tool branded image
        from src.tools.canva_tool import create_quote_card, upload_canva_image
        from src.tools.storage_tool import generate_filename
        image_bytes = create_quote_card(headline=topic, subtext="UPSC Preparation | TOPPER IAS")
        filename = generate_filename(topic, content_type="post")
        return await upload_canva_image(image_bytes, filename)


def add_watermark(image_bytes: bytes, text: str = "TOPPER IAS") -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    # Measure text size
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    margin = 16
    x = img.width - text_w - margin
    y = img.height - text_h - margin

    # Semi-transparent white text
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 180))

    watermarked = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    watermarked.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
