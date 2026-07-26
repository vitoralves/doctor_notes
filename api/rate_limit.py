from __future__ import annotations

from datetime import datetime, timezone

import httpx

from api.config import (
    RATE_LIMIT_PER_DAY,
    UPSTASH_REDIS_REST_TOKEN,
    UPSTASH_REDIS_REST_URL,
)


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, current: int):
        self.limit = limit
        self.current = current
        super().__init__(f"Rate limit exceeded: {current}/{limit} per day")


def _enabled() -> bool:
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def _key(user_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"ratelimit:{user_id}:{day}"


def check_and_increment(user_id: str) -> dict[str, int]:
    if not _enabled():
        return {"limit": RATE_LIMIT_PER_DAY, "remaining": RATE_LIMIT_PER_DAY, "used": 0}

    key = _key(user_id)
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
    base = UPSTASH_REDIS_REST_URL.rstrip("/")

    with httpx.Client(timeout=5.0) as client:
        incr = client.get(f"{base}/incr/{key}", headers=headers)
        incr.raise_for_status()
        used = int(incr.json()["result"])

        if used == 1:
            client.get(f"{base}/expire/{key}/86400", headers=headers)

    if used > RATE_LIMIT_PER_DAY:
        raise RateLimitExceeded(RATE_LIMIT_PER_DAY, used)

    return {
        "limit": RATE_LIMIT_PER_DAY,
        "used": used,
        "remaining": max(RATE_LIMIT_PER_DAY - used, 0),
    }
