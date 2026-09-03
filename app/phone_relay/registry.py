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
    last_used_at: float = 0.0
    penalty_until: float = 0.0
    consecutive_timeouts: int = 0
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

    def penalize(self, phone_id: str, penalty_s: float) -> None:
        phone = self._phones.get(phone_id)
        if phone:
            phone.penalty_until = max(phone.penalty_until, time.monotonic() + penalty_s)
            logger.warning("Phone %s put on block penalty for %.0fs", phone_id, penalty_s)

    def record_success(self, phone_id: str) -> None:
        phone = self._phones.get(phone_id)
        if phone:
            phone.consecutive_timeouts = 0

    def record_timeout(self, phone_id: str) -> None:
        phone = self._phones.get(phone_id)
        if not phone:
            return
        phone.consecutive_timeouts += 1
        if phone.consecutive_timeouts >= settings.PHONE_RELAY_TIMEOUT_STRIKE_LIMIT:
            penalty_s = settings.PHONE_RELAY_TIMEOUT_PENALTY_MS / 1000
            phone.penalty_until = max(phone.penalty_until, time.monotonic() + penalty_s)
            logger.warning(
                "Phone %s unresponsive %d times in a row — pulled from rotation for %.0fs",
                phone_id,
                phone.consecutive_timeouts,
                penalty_s,
            )

    async def pick_phone(self, max_wait_s: float = 120.0) -> Optional[PhoneConnection]:
        started = time.monotonic()
        cooldown_s = settings.PHONE_RELAY_COOLDOWN_MS / 1000
        while True:
            if not self._phones:
                return None
            now = time.monotonic()
            phones = list(self._phones.values())
            n = len(phones)
            for i in range(n):
                candidate = phones[(self._rr_index + i) % n]
                if (
                    candidate.active_stream_count < settings.PHONE_RELAY_MAX_STREAMS_PER_PHONE
                    and now - candidate.last_used_at >= cooldown_s
                    and now >= candidate.penalty_until
                ):
                    self._rr_index = (self._rr_index + i + 1) % n
                    candidate.last_used_at = now
                    return candidate
            if now - started >= max_wait_s:
                available = [
                    p for p in phones if p.active_stream_count < settings.PHONE_RELAY_MAX_STREAMS_PER_PHONE
                ]
                unpenalized = [p for p in available if now >= p.penalty_until]
                pool = unpenalized or available or phones
                fallback = pool[self._rr_index % len(pool)]
                self._rr_index = (self._rr_index + 1) % n
                fallback.last_used_at = now
                return fallback
            await asyncio.sleep(0.5)


phone_registry = PhoneRegistry()
