import json
import uuid
from typing import Optional, Union

from redis_client import redis_client, redis_sync


def channel_for(user_id: Union[str, uuid.UUID]) -> str:
    return f"user:{user_id}"


def build_payload(event_type: str, data: Optional[dict]) -> str:
    return json.dumps({"type": event_type, "data": data or {}})


async def publish_event(
    user_id: Union[str, uuid.UUID], event_type: str, data: Optional[dict] = None
) -> int:
    return await redis_client.publish(
        channel_for(user_id), build_payload(event_type, data)
    )


def publish_event_sync(
    user_id: Union[str, uuid.UUID], event_type: str, data: Optional[dict] = None
) -> int:
    try:
        return redis_sync.publish(
            channel_for(user_id), build_payload(event_type, data)
        )
    except Exception as e:
        print("Event publish failed:", e)
        return 0