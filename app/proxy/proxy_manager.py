import secrets
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ProxyCredentials:
    key: str
    server: str
    username: Optional[str] = None
    password: Optional[str] = None


def _parse_proxy_url(raw: str) -> ProxyCredentials:
    parsed = urlparse(raw)
    server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return ProxyCredentials(
        key=f"{parsed.hostname}:{parsed.port}:{parsed.username or ''}",
        server=server,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
    )


class ProxyManager:
    def __init__(self) -> None:
        self._static_pool = [_parse_proxy_url(p) for p in settings.proxy_list]
        self._cooldowns: dict[str, float] = {}
        self._rr_index = 0
        self._mrscraper_enabled = bool(settings.MRSCRAPER_USERNAME and settings.MRSCRAPER_PASSWORD)
        self._warned_no_proxy = False

    @property
    def has_any_proxy(self) -> bool:
        return self._mrscraper_enabled or bool(self._static_pool)

    def next(self) -> Optional[ProxyCredentials]:
        if settings.PROXY_BACKEND == "phone_relay":
            return self._next_phone_relay()
        if self._mrscraper_enabled:
            return self._next_mrscraper_session()
        if self._static_pool:
            return self._next_from_static_pool()

        if not self._warned_no_proxy:
            logger.warning(
                "No proxies configured (PROXY_LIST / MRSCRAPER_*) — requests will go direct from "
                "this host's IP."
            )
            self._warned_no_proxy = True
        return None

    def report_blocked(self, proxy: ProxyCredentials) -> None:
        if not proxy.key.startswith("mrscraper:"):
            self._cooldowns[proxy.key] = time.time() + settings.PROXY_COOLDOWN_MS / 1000

    def _next_phone_relay(self) -> ProxyCredentials:
        return ProxyCredentials(
            key="phone-relay",
            server=f"http://127.0.0.1:{settings.PHONE_RELAY_LOCAL_PORT}",
        )

    def _next_mrscraper_session(self) -> ProxyCredentials:
        session = secrets.token_hex(6)
        username = settings.MRSCRAPER_SESSION_TEMPLATE.replace(
            "{username}", settings.MRSCRAPER_USERNAME
        ).replace("{session}", session)
        return ProxyCredentials(
            key=f"mrscraper:{session}",
            server=f"http://{settings.MRSCRAPER_HOST}:{settings.MRSCRAPER_PORT}",
            username=username,
            password=settings.MRSCRAPER_PASSWORD,
        )

    def _next_from_static_pool(self) -> Optional[ProxyCredentials]:
        now = time.time()
        n = len(self._static_pool)
        for i in range(n):
            candidate = self._static_pool[(self._rr_index + i) % n]
            if self._cooldowns.get(candidate.key, 0) <= now:
                self._rr_index = (self._rr_index + i + 1) % n
                return candidate
        logger.warning("All static proxies are in cooldown; reusing the least-stale one early.")
        return self._static_pool[self._rr_index % n] if self._static_pool else None


proxy_manager = ProxyManager()
