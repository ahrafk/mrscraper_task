import asyncio
import secrets

from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.registry import phone_registry

logger = get_logger(__name__)


class RenderError(Exception):
    pass


async def render_via_phone(url: str, timeout_s: float | None = None) -> dict:
    phone = await phone_registry.pick_phone()
    if not phone:
        raise RenderError("no phone connected")

    if timeout_s is None:
        timeout_s = settings.PHONE_RELAY_RENDER_TIMEOUT_MS / 1000
    timeout_s = max(timeout_s, 1.0)

    job_id = secrets.token_hex(8)
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    phone.pending_renders[job_id] = future
    phone.active_stream_count += 1

    try:
        await phone.send_json({"type": "render", "job_id": job_id, "url": url})
        try:
            result = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            raise RenderError("render timed out")
        if result.get("error"):
            raise RenderError(result["error"])
        return result
    finally:
        phone.pending_renders.pop(job_id, None)
        phone.active_stream_count = max(0, phone.active_stream_count - 1)
