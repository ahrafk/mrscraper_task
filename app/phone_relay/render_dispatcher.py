import asyncio
import re
import secrets
import time

from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.registry import phone_registry
from app.scraper.block_detector import detect_block

logger = get_logger(__name__)


class RenderError(Exception):
    pass


MIN_RENDER_RESERVE_S = 25.0

_SLUG_RE = re.compile(r"/pd/([^/]+)/(\d+)")


def derive_search_query(url: str) -> str:
    match = _SLUG_RE.search(url)
    if not match:
        return ""
    slug, product_id = match.group(1), match.group(2)
    return f"{slug.replace('-', ' ')} {product_id}"


async def render_via_phone(url: str, timeout_s: float | None = None, use_search: bool = True) -> dict:
    if timeout_s is None:
        timeout_s = settings.PHONE_RELAY_RENDER_TIMEOUT_MS / 1000
    timeout_s = max(timeout_s, 1.0)

    wait_start = time.monotonic()
    pick_budget = max(timeout_s - MIN_RENDER_RESERVE_S, 0.5)
    phone = await phone_registry.pick_phone(max_wait_s=pick_budget)
    if not phone:
        raise RenderError("no phone connected")

    remaining = timeout_s - (time.monotonic() - wait_start)
    if remaining <= 1.0:
        raise RenderError("no phone became available in time")
    timeout_s = remaining

    job_id = secrets.token_hex(8)
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    phone.pending_renders[job_id] = future
    phone.active_stream_count += 1

    try:
        search_query = derive_search_query(url) if use_search else ""
        await phone.send_json(
            {"type": "render", "job_id": job_id, "url": url, "search_query": search_query}
        )
        try:
            result = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("Render timed out on phone=%s after %.1fs", phone.phone_id, timeout_s)
            phone_registry.record_timeout(phone.phone_id)
            raise RenderError("render timed out")
        phone_registry.record_success(phone.phone_id)
        if result.get("error"):
            logger.warning("Render error on phone=%s: %s", phone.phone_id, result["error"])
            raise RenderError(result["error"])
        block = detect_block(result.get("status"), result.get("html", ""))
        if block.blocked:
            logger.warning("Render blocked on phone=%s reason=%s", phone.phone_id, block.reason)
            phone_registry.penalize(phone.phone_id, settings.PHONE_RELAY_BLOCK_PENALTY_MS / 1000)
        return result
    finally:
        phone.pending_renders.pop(job_id, None)
        phone.active_stream_count = max(0, phone.active_stream_count - 1)
