import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PhoneConnection:
    phone_id: str
    websocket: WebSocket
    connected_at: float = field(default_factory=time.monotonic)
    pending_opens: dict = field(default_factory=dict)
    pending_renders: dict = field(default_factory=dict)
    streams: dict = field(default_factory=dict)
    active_stream_count: int = 0
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send_json(self, payload: dict) -> None:
        async with self.send_lock:
            await self.websocket.send_json(payload)

    async def send_binary(self, stream_id: uuid.UUID, data: bytes) -> None:
        async with self.send_lock:
            await self.websocket.send_bytes(stream_id.bytes + data)


class PhoneRegistry:
    def __init__(self) -> None:
        self._phones: dict[str, PhoneConnection] = {}
        self._rr_index = 0

    def register(self, phone_id: str, websocket: WebSocket) -> PhoneConnection:
        phone = PhoneConnection(phone_id=phone_id, websocket=websocket)
        self._phones[phone_id] = phone
        logger.info("Phone connected: %s (total=%d)", phone_id, len(self._phones))
        return phone

    def unregister(self, phone_id: str) -> None:
        phone = self._phones.pop(phone_id, None)
        if phone:
            for q in phone.streams.values():
                q.put_nowait(None)
            for fut in phone.pending_opens.values():
                if not fut.done():
                    fut.set_result(False)
            for fut in phone.pending_renders.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("phone disconnected mid-render"))
            logger.info("Phone disconnected: %s (total=%d)", phone_id, len(self._phones))

    @property
    def count(self) -> int:
        return len(self._phones)

    def pick_phone(self) -> Optional[PhoneConnection]:
        if not self._phones:
            return None
        phones = list(self._phones.values())
        n = len(phones)
        for i in range(n):
            candidate = phones[(self._rr_index + i) % n]
            if candidate.active_stream_count < settings.PHONE_RELAY_MAX_STREAMS_PER_PHONE:
                self._rr_index = (self._rr_index + i + 1) % n
                return candidate
        self._rr_index = (self._rr_index + 1) % n
        return phones[self._rr_index]


phone_registry = PhoneRegistry()
