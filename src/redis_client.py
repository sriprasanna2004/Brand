"""Shared Redis client — handles Railway rediss:// with CERT_NONE param."""
import os
import re
import redis as redis_lib

def _fix_redis_url(url: str) -> str:
    """Railway appends ?ssl_cert_reqs=CERT_NONE but redis-py needs lowercase 'none'."""
    url = re.sub(r'ssl_cert_reqs=CERT_NONE', 'ssl_cert_reqs=none', url, flags=re.IGNORECASE)
    return url

def get_redis():
    url = _fix_redis_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    return redis_lib.from_url(url, decode_responses=True)

try:
    _redis = get_redis()
    _redis.ping()
except Exception:
    _redis = None

def redis_client():
    return _redis
