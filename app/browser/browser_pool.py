import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from camoufox.async_api import AsyncNewBrowser
from camoufox.fingerprints import generate_context_fingerprint
from camoufox.pkgman import installed_verstr
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config import settings
from app.logging_config import get_logger
from app.proxy.proxy_manager import ProxyCredentials, proxy_manager

logger = get_logger(__name__)

HOMEPAGE_URL = "https://www.lowes.com/"
MAX_USES_PER_SESSION = 1
MAX_SESSION_AGE_S = 900
TARGET_TIMEZONE = "America/New_York"
TARGET_LOCALE = "en-US"
MAX_FINGERPRINT_ATTEMPTS = 3


def _installed_ff_major_version() -> Optional[str]:
    try:
        return installed_verstr().split(".", 1)[0]
    except Exception as err:
        logger.warning("Could not determine installed Firefox version: %s", err)
        return None


_FF_VERSION = _installed_ff_major_version()


@dataclass
class WarmSession:
    context: BrowserContext
    page: Page
    proxy: Optional[ProxyCredentials]
    created_at: float = field(default_factory=time.monotonic)
    uses: int = 0

    @property
    def is_stale(self) -> bool:
        return self.uses >= MAX_USES_PER_SESSION or (time.monotonic() - self.created_at) >= MAX_SESSION_AGE_S


class BrowserPool:
    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._launch_lock = asyncio.Lock()
        self._sessions: asyncio.Queue[WarmSession] = asyncio.Queue()
        self._total_sessions = 0
        self._pool_size = settings.MAX_CONCURRENCY
        self._create_lock = asyncio.Lock()

    async def _get_browser(self) -> Browser:
        if self._browser:
            return self._browser
        async with self._launch_lock:
            if self._browser:
                return self._browser
            self._playwright = await async_playwright().start()
            self._browser = await AsyncNewBrowser(
                self._playwright, headless=settings.HEADLESS, geoip=True
            )
            logger.info("Shared Camoufox instance launched")
            return self._browser

    async def _create_session(self) -> WarmSession:
        browser = await self._get_browser()
        proxy = proxy_manager.next()

        proxy_dict: Optional[dict] = None
        if proxy:
            proxy_dict = {"server": proxy.server}
            if proxy.username:
                proxy_dict["username"] = proxy.username
            if proxy.password:
                proxy_dict["password"] = proxy.password

        context = None
        page = None
        applied_tz = None
        for attempt in range(1, MAX_FINGERPRINT_ATTEMPTS + 1):
            fp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: generate_context_fingerprint(
                    os="windows",
                    ff_version=_FF_VERSION,
                    timezone=TARGET_TIMEZONE,
                    locale=TARGET_LOCALE,
                ),
            )
            context_options = dict(fp["context_options"])
            if proxy_dict:
                context_options["proxy"] = proxy_dict
            context = await browser.new_context(**context_options)
            await context.add_init_script(fp["init_script"])
            page = await context.new_page()

            applied_tz = await page.evaluate("() => Intl.DateTimeFormat().resolvedOptions().timeZone")
            if applied_tz == TARGET_TIMEZONE:
                break
            logger.warning(
                "Context timezone mismatch (attempt=%d/%d wanted=%s got=%s)",
                attempt,
                MAX_FINGERPRINT_ATTEMPTS,
                TARGET_TIMEZONE,
                applied_tz,
            )
            if attempt < MAX_FINGERPRINT_ATTEMPTS:
                await context.close()

        if applied_tz != TARGET_TIMEZONE:
            logger.warning(
                "Proceeding with timezone mismatch after %d attempts (got=%s)",
                MAX_FINGERPRINT_ATTEMPTS,
                applied_tz,
            )

        try:
            await page.goto(HOMEPAGE_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
        except Exception as err:
            logger.warning("Session warm-up navigation failed: %s", err)
        logger.info("Warmed new session (proxy=%s)", proxy.key if proxy else None)
        return WarmSession(context=context, page=page, proxy=proxy)

    async def _retire(self, session: WarmSession) -> None:
        self._total_sessions -= 1
        try:
            await session.context.close()
        except Exception:
            pass

    async def acquire_session(self) -> WarmSession:
        while True:
            if not self._sessions.empty():
                session = self._sessions.get_nowait()
                if session.is_stale:
                    await self._retire(session)
                    continue
                return session

            async with self._create_lock:
                if self._total_sessions < self._pool_size:
                    self._total_sessions += 1
                    return await self._create_session()

            session = await self._sessions.get()
            if session.is_stale:
                await self._retire(session)
                continue
            return session

    async def release_session(self, session: WarmSession, success: bool) -> None:
        session.uses += 1
        if not success:
            await self._retire(session)
            return
        if session.is_stale:
            await self._retire(session)
            return
        await self._sessions.put(session)

    async def shutdown(self) -> None:
        while not self._sessions.empty():
            session = self._sessions.get_nowait()
            await self._retire(session)
        if self._browser:
            logger.info("Closing shared Camoufox instance")
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


browser_pool = BrowserPool()
