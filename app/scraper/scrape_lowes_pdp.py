import asyncio
import random
import re
import time
from dataclasses import dataclass

from app.browser.browser_pool import browser_pool
from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.render_dispatcher import RenderError, render_via_phone
from app.scraper.block_detector import detect_block
from app.scraper.price_extractor import extract_price
from app.scraper.url_validator import validate_lowes_pdp_url

logger = get_logger(__name__)

HYDRATE_POLL_S = 1.0
HYDRATE_MAX_POLLS = 12
HYDRATED_HTML_LENGTH = 20000

_PRODUCT_ID_RE = re.compile(r"/(\d+)/?(?:[?#].*)?$")


def _product_id(url: str) -> str:
    match = _PRODUCT_ID_RE.search(url)
    return match.group(1) if match else ""


class ScrapeError(Exception):
    def __init__(self, message: str, status_code: int, attempts: int, reason: str = "unknown") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts
        self.reason = reason


@dataclass
class ScrapeResult:
    html: str
    price: str
    attempts: int
    latency_ms: float


async def _jitter_delay() -> None:
    ms = random.uniform(settings.MIN_DELAY_MS, settings.MAX_DELAY_MS)
    await asyncio.sleep(ms / 1000)


def _evaluate_attempt(target_id: str, landed_url: str, status, html: str):
    if target_id and target_id not in landed_url:
        return "wrong-page-landed", None
    block = detect_block(status, html)
    if block.blocked:
        return block.reason or "blocked", None
    price_result = extract_price(html)
    if not price_result.found:
        return "price-not-found", None
    return None, price_result.price_text or ""


async def scrape_lowes_pdp(raw_url: str) -> ScrapeResult:
    if settings.PROXY_BACKEND == "phone_relay_render":
        return await _scrape_via_phone_render(raw_url)
    return await _scrape_via_browser_pool(raw_url)


async def _scrape_via_phone_render(raw_url: str) -> ScrapeResult:
    url = validate_lowes_pdp_url(raw_url)
    start = time.monotonic()
    deadline = start + settings.REQUEST_BUDGET_MS / 1000
    target_id = _product_id(url)

    last_error = "unknown"
    attempts = 0

    while attempts < settings.MAX_ATTEMPTS_PER_REQUEST and time.monotonic() < deadline:
        attempts += 1
        try:
            await _jitter_delay()
            remaining = deadline - time.monotonic()
            result = await render_via_phone(url, timeout_s=remaining)
        except RenderError as err:
            last_error = str(err)
            logger.warning("Phone render attempt %d failed: %s — retrying", attempts, last_error)
            continue
        except Exception as err:
            last_error = str(err)
            logger.warning("Phone render attempt %d threw — retrying: %s", attempts, last_error)
            continue

        html = result.get("html", "")
        status = result.get("status")
        landed_url = result.get("final_url") or url

        error, price = _evaluate_attempt(target_id, landed_url, status, html)
        if error:
            last_error = error
            logger.warning(
                "Blocked/challenged via phone render (attempt=%d reason=%s) — retrying",
                attempts,
                error,
            )
            continue

        return ScrapeResult(
            html=html, price=price or "", attempts=attempts, latency_ms=(time.monotonic() - start) * 1000
        )

    raise ScrapeError(f"Failed after {attempts} attempt(s): {last_error}", 502, attempts, reason=last_error)


async def _scrape_via_browser_pool(raw_url: str) -> ScrapeResult:
    url = validate_lowes_pdp_url(raw_url)
    start = time.monotonic()
    deadline = start + settings.REQUEST_BUDGET_MS / 1000

    last_error = "unknown"
    attempts = 0

    while attempts < settings.MAX_ATTEMPTS_PER_REQUEST and time.monotonic() < deadline:
        attempts += 1
        session = None
        success = False
        try:
            await _jitter_delay()
            session = await browser_pool.acquire_session()
            page = session.page

            status = None
            try:
                response = await page.goto(url, wait_until="commit", timeout=20000)
                status = response.status if response else None
            except Exception as nav_err:
                logger.warning(
                    "Nav to PDP raised (attempt=%d): %s — inspecting landed page anyway",
                    attempts,
                    str(nav_err)[:150],
                )

            await page.wait_for_timeout(1000)
            try:
                html = await page.content()
            except Exception:
                html = ""

            target_id = _product_id(url)
            if target_id and target_id not in page.url:
                last_error = "wrong-page-landed"
                logger.warning(
                    "Landed on %s instead of the target product (attempt=%d) — retrying",
                    page.url,
                    attempts,
                )
                continue

            block = detect_block(status, html)

            if not block.blocked:
                for _ in range(HYDRATE_MAX_POLLS - 1):
                    if len(html) > HYDRATED_HTML_LENGTH:
                        break
                    await page.wait_for_timeout(int(HYDRATE_POLL_S * 1000))
                    try:
                        html = await page.content()
                    except Exception:
                        continue
                block = detect_block(status, html)

            if block.blocked:
                last_error = block.reason or "blocked"
                logger.warning(
                    "Blocked/challenged (attempt=%d reason=%s proxy=%s uses=%d) — retiring session and retrying",
                    attempts,
                    last_error,
                    session.proxy.key if session.proxy else None,
                    session.uses,
                )
                continue

            price_result = extract_price(html)
            if not price_result.found:
                last_error = "price-not-found"
                logger.warning("Price not found in rendered HTML (attempt=%d) — retrying", attempts)
                continue

            success = True
            return ScrapeResult(
                html=html,
                price=price_result.price_text or "",
                attempts=attempts,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as err:
            last_error = str(err)
            logger.warning("Scrape attempt %d threw — retrying: %s", attempts, last_error)
        finally:
            if session:
                await browser_pool.release_session(session, success)

    raise ScrapeError(f"Failed after {attempts} attempt(s): {last_error}", 502, attempts, reason=last_error)
