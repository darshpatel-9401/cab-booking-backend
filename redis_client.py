import os

import redis as redis_lib
from dotenv import load_dotenv
from redis import asyncio as redis_async

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL is missing in backend/.env")

# Async client: used by WebSocket code (async def)
redis_client = redis_async.from_url(REDIS_URL, decode_responses=True)

# Sync client: used by normal routes (def), which run in a thread pool
redis_sync = redis_lib.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
)