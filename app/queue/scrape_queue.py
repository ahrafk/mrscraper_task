import asyncio
from typing import Awaitable, Callable, TypeVar

from app.config import settings

T = TypeVar("T")

_lock = asyncio.Lock()
_pending = 0
_active = 0


def _capacity() -> int:
    from app.phone_relay.registry import phone_registry

    return max(phone_registry.count * settings.PHONE_RELAY_MAX_STREAMS_PER_PHONE, 1)


async def enqueue(fn: Callable[[], Awaitable[T]]) -> T:
    global _pending, _active
    _pending += 1
    try:
        while True:
            async with _lock:
                if _active < _capacity():
                    _pending -= 1
                    _active += 1
                    break
            await asyncio.sleep(0.2)
    except BaseException:
        _pending -= 1
        raise

    try:
        return await fn()
    finally:
        async with _lock:
            _active -= 1


def queue_status() -> dict:
    return {"pending": _pending, "active": _active, "capacity": _capacity()}
