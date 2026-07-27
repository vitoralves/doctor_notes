from __future__ import annotations

import httpx

from api.config import (
    RATE_LIMIT_LIFETIME,
    UPSTASH_REDIS_REST_TOKEN,
    UPSTASH_REDIS_REST_URL,
)


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, current: int):
        self.limit = limit
        self.current = current
        super().__init__(f"Rate limit exceeded: {current}/{limit} lifetime")


def _enabled() -> bool:
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def _key(user_id: str) -> str:
    return f"ratelimit:lifetime:{user_id}"


def check_and_increment(user_id: str) -> dict[str, int]:
    if not _enabled():
        return {
            "limit": RATE_LIMIT_LIFETIME,
            "remaining": RATE_LIMIT_LIFETIME,
            "used": 0,
            "window": "lifetime",
        }

    key = _key(user_id)
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
    base = UPSTASH_REDIS_REST_URL.rstrip("/")

    with httpx.Client(timeout=5.0) as client:
        incr = client.get(f"{base}/incr/{key}", headers=headers)
        incr.raise_for_status()
        used = int(incr.json()["result"])

    if used > RATE_LIMIT_LIFETIME:
        raise RateLimitExceeded(RATE_LIMIT_LIFETIME, used)

    return {
        "limit": RATE_LIMIT_LIFETIME,
        "used": used,
        "remaining": max(RATE_LIMIT_LIFETIME - used, 0),
        "window": "lifetime",
    }
