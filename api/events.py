"""SSE (Server-Sent Events) endpoint for real-time updates.

Provides live updates to the dashboard without polling.
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["events"])

# Simple in-memory event queue (for demo purposes)
# In production, use Redis pub/sub or similar
event_queue: asyncio.Queue = asyncio.Queue()


async def publish_event(event_type: str, data: dict):
    """Publish an event to all connected clients."""
    await event_queue.put({"event": event_type, "data": data})


async def event_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events."""
    while True:
        try:
            # Wait for events with timeout to send keepalive
            event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
            event_type = event["event"]
            data = json.dumps(event["data"])
            yield f"event: {event_type}\ndata: {data}\n\n"
        except asyncio.TimeoutError:
            # Send keepalive comment
            yield ": keepalive\n\n"
        except Exception:
            break


@router.get("/events")
async def sse_endpoint():
    """SSE endpoint for real-time updates.

    Events:
    - task_update: Task status changed
    - claude_status: Claude status changed
    - commit: New commit to a stack
    """
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
