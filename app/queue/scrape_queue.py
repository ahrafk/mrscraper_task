import asyncio
import time
from typing import Awaitable, Callable, TypeVar

from app.config import settings

T = TypeVar("T")

_condition = asyncio.Condition()
_pending = 0
_active = 0


class QueueTimeoutError(Exception):
    pass


def _capacity() -> int:
    from app.phone_relay.registry import phone_registry

    return max(phone_registry.count * settings.PHONE_RELAY_MAX_STREAMS_PER_PHONE, 1)


async def enqueue(fn: Callable[[], Awaitable[T]], deadline: float | None = None) -> T:
    global _pending, _active
    _pending += 1
    try:
        async with _condition:
            while _active >= _capacity():
                # without a deadline, an overloaded request would just sit here until a
                # slot frees up, however long that takes, the caller's own timeout would
                # fire first and they'd never see whatever we eventually respond with.
                # bailing out here the moment the caller's own budget is gone means
                # overload turns into a fast, honest failure instead of a slow, silent one
                if deadline is not None and time.monotonic() >= deadline:
                    raise QueueTimeoutError("timed out waiting for phone capacity")
                wait_s = 1.0
                if deadline is not None:
                    wait_s = max(min(deadline - time.monotonic(), 1.0), 0.0)
                try:
                    await asyncio.wait_for(_condition.wait(), timeout=wait_s)
                except asyncio.TimeoutError:
                    pass
            _pending -= 1
            _active += 1
    except BaseException:
        _pending -= 1
        raise

    try:
        return await fn()
    finally:
        async with _condition:
            _active -= 1
            _condition.notify_all()


def queue_status() -> dict:
    return {"pending": _pending, "active": _active, "capacity": _capacity()}
