import os
import re
from datetime import datetime

import boto3
import httpx
from loguru import logger


def _s3_client():
    account_id = os.getenv("R2_ACCOUNT_ID", "")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", ""),
        region_name="auto",
    )


def upload_media(file_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    bucket = os.getenv("R2_BUCKET_NAME", "brandiq-media")
    public_url = os.getenv("R2_PUBLIC_URL", "")
    key = f"brandiq-media/{filename}"

    _s3_client().put_object(
        Bucket=bucket,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
        CacheControl="public, max-age=31536000",
    )

    size_kb = round(len(file_bytes) / 1024, 1)
    url = f"{public_url}/brandiq-media/{filename}"
    logger.info(f"[Storage] Uploaded '{filename}' ({size_kb} KB) → {url}")
    return url


def upload_from_url(source_url: str, filename: str) -> str:
    resp = httpx.get(source_url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    return upload_media(resp.content, filename, content_type=content_type)


def generate_filename(topic: str, content_type: str = "post") -> str:
    slug = topic.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")[:50]
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"topper-ias-{content_type}-{slug}-{timestamp}.jpg"
