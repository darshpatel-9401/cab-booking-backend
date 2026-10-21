import os

from fastapi import Depends, HTTPException

from auth import get_current_user
from redis_client import redis_sync


def rate_limit(name: str, limit: int, window_seconds: int):
    """A per-user limit: at most `limit` calls in each `window_seconds` window."""

    def dependency(user: dict = Depends(get_current_user)):
        if os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "true":
            return user

        key = f"rl:{name}:{user['id']}"
        try:
            pipe = redis_sync.pipeline(transaction=False)
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl is None or ttl < 0:
                # A new key, or one that lost its expiry: (re)start the window
                redis_sync.expire(key, window_seconds)
                ttl = window_seconds
        except Exception as e:
            print("Rate limiter unavailable (skipping):", e)
            return user

        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down and try again shortly.",
                headers={"Retry-After": str(max(int(ttl), 1))},
            )
        return user

    return dependency