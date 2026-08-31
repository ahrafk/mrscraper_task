import asyncio
from typing import Awaitable, Callable, TypeVar

from app.config import settings

T = TypeVar("T")

_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENCY)
_pending = 0
_active = 0


async def enqueue(fn: Callable[[], Awaitable[T]]) -> T:
    global _pending, _active
    _pending += 1
    async with _semaphore:
        _pending -= 1
        _active += 1
        try:
            return await fn()
        finally:
            _active -= 1


def queue_status() -> dict:
    return {"pending": _pending, "active": _active}
