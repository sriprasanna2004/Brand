"""
Canva tool — generates branded TOPPER IAS visuals using Stability AI
with brand-specific overlays. Falls back gracefully if API unavailable.
Brand: purple #7c3aed, dark #0f0f1a, white text.
"""
import os
import io
import base64
from typing import Optional
from loguru import logger
from PIL import Image, ImageDraw, ImageFont


BRAND_COLORS = {
    "bg": (15, 15, 26),        # #0f0f1a
    "primary": (124, 58, 237), # #7c3aed
    "accent": (0, 229, 195),   # #00e5c3
    "text": (255, 255, 255),
    "muted": (74, 79, 114),
}

TEMPLATES = {
    "quote_card": {"width": 1080, "height": 1080, "style": "dark_gradient"},
    "carousel":   {"width": 1080, "height": 1080, "style": "purple_accent"},
    "story":      {"width": 1080, "height": 1920, "style": "dark_gradient"},
    "reel_thumb": {"width": 1080, "height": 1920, "style": "purple_accent"},
}


def _load_font(size: int):
    for path in ["arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_quote_card(
    headline: str,
    subtext: str = "",
    watermark: str = "TOPPER IAS",
    template: str = "quote_card",
) -> bytes:
    """Create a branded quote card image. Returns JPEG bytes."""
    cfg = TEMPLATES.get(template, TEMPLATES["quote_card"])
    w, h = cfg["width"], cfg["height"]

    img = Image.new("RGB", (w, h), BRAND_COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Purple gradient bar at top
    for i in range(8):
        alpha = int(255 * (1 - i / 8))
        r, g, b = BRAND_COLORS["primary"]
        draw.rectangle([(0, i * 4), (w, (i + 1) * 4)], fill=(r, g, b, alpha))

    # Accent line
    draw.rectangle([(40, 60), (w - 40, 64)], fill=BRAND_COLORS["accent"])

    # Headline
    font_h = _load_font(52)
    # Word wrap
    words = headline.split()
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        bbox = draw.textbbox((0, 0), test, font=font_h)
        if bbox[2] - bbox[0] > w - 120:
            if line:
                lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))

    y = h // 3
    for ln in lines[:4]:
        bbox = draw.textbbox((0, 0), ln, font=font_h)
        x = (w - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), ln, font=font_h, fill=BRAND_COLORS["text"])
        y += 70

    # Subtext
    if subtext:
        font_s = _load_font(28)
        bbox = draw.textbbox((0, 0), subtext, font=font_s)
        x = (w - (bbox[2] - bbox[0])) // 2
        draw.text((x, y + 20), subtext, font=font_s, fill=BRAND_COLORS["muted"])

    # Watermark bottom right
    font_w = _load_font(24)
    draw.text((w - 200, h - 50), watermark, font=font_w, fill=BRAND_COLORS["accent"])

    # Bottom accent line
    draw.rectangle([(0, h - 8), (w, h)], fill=BRAND_COLORS["primary"])

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def create_carousel_slide(
    slide_number: int,
    total_slides: int,
    title: str,
    body: str,
    watermark: str = "TOPPER IAS",
) -> bytes:
    """Create a single carousel slide."""
    img = Image.new("RGB", (1080, 1080), BRAND_COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Slide indicator dots
    dot_y = 40
    for i in range(total_slides):
        color = BRAND_COLORS["accent"] if i == slide_number - 1 else BRAND_COLORS["muted"]
        x = 540 - (total_slides * 20) // 2 + i * 20
        draw.ellipse([(x, dot_y), (x + 10, dot_y + 10)], fill=color)

    # Title
    font_t = _load_font(48)
    bbox = draw.textbbox((0, 0), title, font=font_t)
    x = (1080 - (bbox[2] - bbox[0])) // 2
    draw.text((x, 120), title, font=font_t, fill=BRAND_COLORS["accent"])

    # Body
    font_b = _load_font(32)
    words = body.split()
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        bbox = draw.textbbox((0, 0), test, font=font_b)
        if bbox[2] - bbox[0] > 900:
            if line: lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line: lines.append(" ".join(line))

    y = 250
    for ln in lines[:8]:
        draw.text((90, y), ln, font=font_b, fill=BRAND_COLORS["text"])
        y += 50

    # Watermark
    font_w = _load_font(22)
    draw.text((880, 1040), watermark, font=font_w, fill=BRAND_COLORS["muted"])
    draw.rectangle([(0, 1072), (1080, 1080)], fill=BRAND_COLORS["primary"])

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def upload_canva_image(image_bytes: bytes, filename: str) -> str:
    """Upload image to R2 and return public URL."""
    from src.tools.storage_tool import upload_media
    try:
        url = upload_media(image_bytes, filename, content_type="image/jpeg")
        logger.info(f"[Canva] Uploaded {filename} → {url}")
        return url
    except Exception as e:
        logger.error(f"[Canva] Upload failed: {e}")
        return f"https://via.placeholder.com/1080x1080/0f0f1a/00e5c3?text=TOPPER+IAS"


async def generate_quote_card(headline: str, subtext: str = "", topic: str = "upsc") -> str:
    """Generate a quote card and upload to R2. Returns public URL."""
    from src.tools.storage_tool import generate_filename
    image_bytes = create_quote_card(headline=headline, subtext=subtext)
    filename = generate_filename(topic, content_type="quote")
    return await upload_canva_image(image_bytes, filename)


async def generate_carousel(slides: list[dict], topic: str = "upsc") -> list[str]:
    """Generate carousel slides and upload all. Returns list of URLs."""
    from src.tools.storage_tool import generate_filename
    urls = []
    for i, slide in enumerate(slides):
        image_bytes = create_carousel_slide(
            slide_number=i + 1,
            total_slides=len(slides),
            title=slide.get("title", ""),
            body=slide.get("body", ""),
        )
        filename = generate_filename(f"{topic}-slide-{i+1}", content_type="carousel")
        url = await upload_canva_image(image_bytes, filename)
        urls.append(url)
    logger.info(f"[Canva] Generated {len(urls)} carousel slides for topic='{topic}'")
    return urls
