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

# Brand colours
PURPLE = (124, 58, 237)        # #7c3aed
WHITE  = (255, 255, 255)
LIGHT_GRAY = (226, 232, 240)   # #e2e8f0
DARK_OVERLAY = (0, 0, 0, 180)  # 70% opacity black


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Try common system fonts, fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def add_educational_overlay(image_bytes: bytes, caption_text: str, topic: str) -> bytes:
    """
    Add educational text overlay to a generated image:
    - Purple gradient bar at top (8px)
    - Semi-transparent dark overlay on bottom 40%
    - Topic title in the overlay area
    - Up to 4 bullet/numbered lines from caption
    - TOPPER IAS watermark bottom right
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ── 1. Purple bar at top ─────────────────────────────────────────────────
    draw.rectangle([(0, 0), (w, 8)], fill=(*PURPLE, 255))

    # ── 2. Dark overlay on bottom 40% ────────────────────────────────────────
    overlay_top = int(h * 0.60)
    draw.rectangle([(0, overlay_top), (w, h)], fill=DARK_OVERLAY)

    # ── 3. Topic title ────────────────────────────────────────────────────────
    font_title = _load_font(28, bold=True)
    title_y = overlay_top + 16
    # Truncate title if too long
    title = topic[:55] + "..." if len(topic) > 55 else topic
    draw.text((20, title_y), title, font=font_title, fill=(*WHITE, 255))

    # ── 4. Bullet points from caption ────────────────────────────────────────
    font_body = _load_font(20, bold=False)
    lines = []
    for line in caption_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Keep lines that start with numbers, bullets, or emoji numbers
        if (
            line[0].isdigit()
            or line.startswith(("-", "*", "•", "–"))
            or any(line.startswith(e) for e in ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"))
        ):
            lines.append(line[:72])  # truncate long lines
        if len(lines) == 4:
            break

    bullet_y = title_y + 44
    for line in lines:
        draw.text((20, bullet_y), line, font=font_body, fill=(*LIGHT_GRAY, 230))
        bullet_y += 30

    # ── 5. TOPPER IAS watermark bottom right ─────────────────────────────────
    font_wm = _load_font(16, bold=True)
    wm_text = "TOPPER IAS"
    bbox = draw.textbbox((0, 0), wm_text, font=font_wm)
    wm_w = bbox[2] - bbox[0]
    draw.text((w - wm_w - 16, h - 28), wm_text, font=font_wm, fill=(*PURPLE, 220))

    # ── Composite and return ──────────────────────────────────────────────────
    result = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def generate_image(prompt: str, topic: str, caption_text: str = "") -> str:
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
                image_bytes = add_educational_overlay(image_bytes, caption_text, topic)
                r2_account = os.getenv("R2_ACCOUNT_ID", "REPLACE_ME")
                if r2_account and r2_account != "REPLACE_ME":
                    try:
                        filename = generate_filename(topic, content_type="post")
                        url = upload_media(image_bytes, filename, content_type="image/jpeg")
                        logger.info(f"[Visual] Stability AI image uploaded to R2: {url}")
                        return url
                    except Exception as e:
                        logger.warning(f"[Visual] R2 upload failed: {e}")
                b64 = base64.b64encode(image_bytes).decode()
                return f"data:image/jpeg;base64,{b64}"
            elif resp.status_code == 429 or "insufficient_balance" in resp.text:
                logger.warning("[Visual] Stability AI out of credits, falling back to Pollinations")
            else:
                logger.warning(f"[Visual] Stability AI error {resp.status_code}, falling back")
        except Exception as e:
            logger.warning(f"[Visual] Stability AI exception: {e}, falling back")

    return await _generate_pollinations(prompt, topic, caption_text)


async def _generate_pollinations(prompt: str, topic: str, caption_text: str = "") -> str:
    """Generate image using Pollinations.AI (completely free, no key needed)."""
    import urllib.parse
    full_prompt = f"{prompt}, {BRAND_SUFFIX}, dark purple theme, TOPPER IAS"
    encoded = urllib.parse.quote(full_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed=42"

    logger.info(f"[Visual] Generating via Pollinations.AI for topic='{topic}'")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(image_url)
        if not resp.is_success:
            raise Exception(f"Pollinations returned {resp.status_code}")

        image_bytes = resp.content
        image_bytes = add_educational_overlay(image_bytes, caption_text, topic)

        r2_account = os.getenv("R2_ACCOUNT_ID", "REPLACE_ME")
        if r2_account and r2_account != "REPLACE_ME":
            try:
                filename = generate_filename(topic, content_type="post")
                url = upload_media(image_bytes, filename, content_type="image/jpeg")
                logger.info(f"[Visual] Pollinations image uploaded to R2: {url}")
                return url
            except Exception as e:
                logger.warning(f"[Visual] R2 upload failed: {e}")

        logger.info(f"[Visual] Using Pollinations URL directly: {image_url[:80]}")
        return image_url

    except Exception as e:
        logger.error(f"[Visual] Pollinations failed: {e}")
        from src.tools.canva_tool import create_quote_card, upload_canva_image
        image_bytes = create_quote_card(headline=topic, subtext="UPSC Preparation | TOPPER IAS")
        image_bytes = add_educational_overlay(image_bytes, caption_text, topic)
        filename = generate_filename(topic, content_type="post")
        return await upload_canva_image(image_bytes, filename)


def add_watermark(image_bytes: bytes, text: str = "TOPPER IAS") -> bytes:
    """Legacy watermark function — kept for backward compatibility."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    margin = 16
    x = img.width - text_w - margin
    y = img.height - text_h - margin
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 180))

    watermarked = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    watermarked.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
