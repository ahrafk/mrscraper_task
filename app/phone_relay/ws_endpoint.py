import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.registry import phone_registry

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/phone-relay/ws/{phone_id}")
async def phone_ws(websocket: WebSocket, phone_id: str, token: str = Query(...)):
    if not settings.PHONE_RELAY_ENABLED:
        await websocket.close(code=4404)
        return
    if not settings.PHONE_RELAY_TOKEN or token != settings.PHONE_RELAY_TOKEN:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    phone = phone_registry.register(phone_id, websocket)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            text = message.get("text")
            if text is not None:
                await _handle_control_message(phone, text)
                continue

            raw = message.get("bytes")
            if raw is not None and len(raw) >= 16:
                stream_id = uuid.UUID(bytes=raw[:16])
                payload = raw[16:]
                queue = phone.streams.get(stream_id)
                if queue is not None:
                    queue.put_nowait(payload)
    except WebSocketDisconnect:
        pass
    except Exception as err:
        logger.warning("Phone websocket error (phone=%s): %s", phone_id, err)
    finally:
        phone_registry.unregister(phone_id, phone)


async def _handle_control_message(phone, text: str) -> None:
    import json

    try:
        data = json.loads(text)
    except Exception:
        return

    msg_type = data.get("type")

    if msg_type in ("render_result", "render_error"):
        job_id = data.get("job_id")
        fut = phone.pending_renders.get(job_id)
        if fut and not fut.done():
            if msg_type == "render_result":
                fut.set_result(
                    {
                        "html": data.get("html", ""),
                        "status": data.get("status"),
                        "final_url": data.get("final_url"),
                    }
                )
            else:
                fut.set_result({"error": data.get("error", "unknown render error")})
        return

    raw_stream_id = data.get("stream_id")
    if not raw_stream_id:
        return
    try:
        stream_id = uuid.UUID(raw_stream_id)
    except Exception:
        return

    if msg_type == "opened":
        fut = phone.pending_opens.get(stream_id)
        if fut and not fut.done():
            fut.set_result(True)
    elif msg_type == "open_failed":
        fut = phone.pending_opens.get(stream_id)
        if fut and not fut.done():
            fut.set_result(False)
    elif msg_type == "close":
        queue = phone.streams.get(stream_id)
        if queue is not None:
            queue.put_nowait(None)
