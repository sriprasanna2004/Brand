"""
Reel video creator — generates a 30-second slideshow video.
Uses PIL for slides + ffmpeg subprocess directly (most reliable approach).
Images from Pollinations.AI (free).
"""
import io
import os
import subprocess
import tempfile
import urllib.parse

import httpx
import numpy as np
from loguru import logger
from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "arial.ttf", "DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _create_text_slide(text: str, subtext: str = "", slide_num: int = 1, total: int = 5) -> Image.Image:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (7, 8, 15))
    draw = ImageDraw.Draw(img)

    for i in range(10):
        draw.rectangle([(0, i * 8), (w, (i + 1) * 8)], fill=(124, 58, 237))
    draw.rectangle([(60, 90), (w - 60, 96)], fill=(0, 229, 195))

    font_brand = _load_font(34)
    draw.text((60, 110), "TOPPER IAS", font=font_brand, fill=(0, 229, 195))

    font_main = _load_font(68)
    words = text.split()
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        bbox = draw.textbbox((0, 0), test, font=font_main)
        if bbox[2] - bbox[0] > w - 120:
            if line: lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line: lines.append(" ".join(line))

    y = h // 3
    for ln in lines[:5]:
        bbox = draw.textbbox((0, 0), ln, font=font_main)
        x = (w - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), ln, font=font_main, fill=(232, 234, 246))
        y += 88

    if subtext:
        font_sub = _load_font(42)
        y += 20
        bbox = draw.textbbox((0, 0), subtext, font=font_sub)
        x = (w - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), subtext, font=font_sub, fill=(74, 79, 114))

    dot_y = h - 80
    for i in range(total):
        color = (0, 229, 195) if i == slide_num - 1 else (28, 31, 50)
        x = w // 2 - (total * 22) // 2 + i * 22
        draw.ellipse([(x, dot_y), (x + 14, dot_y + 14)], fill=color)

    draw.rectangle([(0, h - 10), (w, h)], fill=(124, 58, 237))
    return img


async def _fetch_pollinations(prompt: str) -> Image.Image | None:
    encoded = urllib.parse.quote(f"{prompt}, dark purple educational UPSC")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.is_success and len(resp.content) > 5000:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            return img.resize((1080, 1920), Image.LANCZOS)
    except Exception as e:
        logger.warning(f"[ReelVideo] Pollinations: {e}")
    return None


async def create_reel_video(
    hook: str,
    value_points: list[str],
    cta: str,
    topic: str,
    duration_seconds: int = 30,
) -> str | None:
    """Create slideshow reel using ffmpeg subprocess. Returns R2 URL or None."""

    # Check ffmpeg available
    ffmpeg = None
    for candidate in ["ffmpeg", "/usr/bin/ffmpeg"]:
        try:
            result = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                ffmpeg = candidate
                break
        except Exception:
            pass

    if not ffmpeg:
        # Try imageio-ffmpeg binary
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            logger.error("[ReelVideo] ffmpeg not found")
            return None

    logger.info(f"[ReelVideo] Using ffmpeg: {ffmpeg}")

    slides_data = [
        (hook, ""),
        (value_points[0] if len(value_points) > 0 else topic, "Tip #1"),
        (value_points[1] if len(value_points) > 1 else topic, "Tip #2"),
        (value_points[2] if len(value_points) > 2 else topic, "Tip #3"),
        (cta, "Follow TOPPER IAS 🎯"),
    ]

    fps = 24
    slide_duration = duration_seconds / len(slides_data)

    video_path = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate slide images
            slide_paths = []
            for i, (text, subtext) in enumerate(slides_data):
                img = await _fetch_pollinations(f"{text} UPSC")
                if img is None:
                    img = _create_text_slide(text, subtext, i + 1, len(slides_data))
                else:
                    # Add text overlay
                    draw = ImageDraw.Draw(img)
                    overlay = Image.new("RGBA", (1080, 500), (7, 8, 15, 200))
                    img_rgba = img.convert("RGBA")
                    img_rgba.paste(overlay, (0, 1420), overlay)
                    img = img_rgba.convert("RGB")
                    draw = ImageDraw.Draw(img)
                    font = _load_font(52)
                    words = text.split()
                    lines, line = [], []
                    for word in words:
                        test = " ".join(line + [word])
                        bbox = draw.textbbox((0, 0), test, font=font)
                        if bbox[2] - bbox[0] > 960:
                            if line: lines.append(" ".join(line))
                            line = [word]
                        else:
                            line.append(word)
                    if line: lines.append(" ".join(line))
                    y = 1440
                    for ln in lines[:3]:
                        bbox = draw.textbbox((0, 0), ln, font=font)
                        x = (1080 - (bbox[2] - bbox[0])) // 2
                        draw.text((x, y), ln, font=font, fill=(232, 234, 246))
                        y += 64
                    font_w = _load_font(28)
                    draw.text((60, 1870), "TOPPER IAS", font=font_w, fill=(0, 229, 195))

                path = os.path.join(tmpdir, f"slide_{i:02d}.jpg")
                img.save(path, "JPEG", quality=85)
                slide_paths.append((path, slide_duration))
                logger.info(f"[ReelVideo] Slide {i+1} saved")

            # Build ffmpeg concat input
            concat_file = os.path.join(tmpdir, "concat.txt")
            with open(concat_file, "w") as f:
                for path, dur in slide_paths:
                    f.write(f"file '{path}'\n")
                    f.write(f"duration {dur}\n")
                # Repeat last frame to avoid truncation
                f.write(f"file '{slide_paths[-1][0]}'\n")

            output_path = os.path.join(tmpdir, "reel.mp4")
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", concat_file,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-crf", "28", "-preset", "fast",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"[ReelVideo] ffmpeg error: {result.stderr[-500:]}")
                return None

            size = os.path.getsize(output_path)
            logger.info(f"[ReelVideo] Video created: {size//1024}KB")

            with open(output_path, "rb") as f:
                video_bytes = f.read()

        from src.tools.storage_tool import generate_filename, upload_media
        filename = generate_filename(topic, content_type="reel").replace(".jpg", ".mp4")
        url = upload_media(video_bytes, filename, content_type="video/mp4")
        logger.info(f"[ReelVideo] Uploaded: {url}")
        return url

    except Exception as e:
        import traceback as tb
        err = f"{e}\n{tb.format_exc()[-400:]}"
        logger.error(f"[ReelVideo] Failed: {err}")
        return None
