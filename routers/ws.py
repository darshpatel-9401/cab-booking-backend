import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from auth import TokenError, verify_token
from database import engine
from events import channel_for
from models import Driver
from redis_client import redis_client
from config import ALLOWED_ORIGINS, origin_allowed

router = APIRouter(tags=["websocket"])

AUTH_TIMEOUT_SECONDS = 10


async def authenticate_websocket(websocket: WebSocket):
    """Wait for the first message {"type": "auth", "token": "..."}.

    Returns the user dictionary, or None if the client disconnected or the
    token was missing or invalid (the socket is closed in the second case).
    """
    token = None
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
        )
        message = json.loads(raw)
        if message.get("type") == "auth":
            token = message.get("token")
    except WebSocketDisconnect:
        return None
    except (asyncio.TimeoutError, ValueError, AttributeError):
        token = None

    if not isinstance(token, str):
        await websocket.close(code=1008)
        return None

    try:
        return await asyncio.to_thread(verify_token, token)
    except TokenError:
        await websocket.close(code=1008)
        return None


def is_registered_driver(user_id: uuid.UUID) -> bool:
    with Session(engine) as db:
        return db.get(Driver, user_id) is not None


async def forward_events(websocket: WebSocket, user_id: uuid.UUID, hello: dict):
    channel = channel_for(user_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    await websocket.send_json(hello)

    # Two tasks send on this socket, so we take turns with a lock
    send_lock = asyncio.Lock()

    async def redis_to_socket():
        async for message in pubsub.listen():
            if message["type"] == "message":
                async with send_lock:
                    await websocket.send_text(message["data"])

    async def watch_socket():
        # Reads whatever the client sends. We only act on {"type": "ping"}.
        # Reading is also how we notice that the client disconnected.
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                async with send_lock:
                    await websocket.send_json({"type": "pong"})

    sender = asyncio.create_task(redis_to_socket())
    watcher = asyncio.create_task(watch_socket())

    try:
        await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (sender, watcher):
            task.cancel()
        await asyncio.gather(sender, watcher, return_exceptions=True)
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception as e:
            print("Redis cleanup error:", e)
        try:
            await websocket.close()
        except Exception:
            pass
        print("WebSocket closed for user:", user_id)


async def serve_user_socket(
    websocket: WebSocket, path_user_id: uuid.UUID, channel_name: str
):

    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()

    user = await authenticate_websocket(websocket)
    if user is None:
        return

    user_id = uuid.UUID(user["id"])
    if user_id != path_user_id:
        await websocket.close(code=1008)
        return

    if channel_name == "driver":
        is_driver = await asyncio.to_thread(is_registered_driver, user_id)
        if not is_driver:
            await websocket.close(code=1008)
            return

    await forward_events(
        websocket, user_id, {"type": "connected", "channel": channel_name}
    )


@router.websocket("/ws/rider/{rider_id}")
async def rider_ws(websocket: WebSocket, rider_id: str):
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin):
        print("WS rejected: origin", origin)
        await websocket.close(code=1008)
        return


@router.websocket("/ws/driver/{driver_id}")
async def driver_socket(websocket: WebSocket, driver_id: uuid.UUID):
    await serve_user_socket(websocket, driver_id, "driver")
