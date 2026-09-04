import asyncio
import random
import re
import time
from dataclasses import dataclass

from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.render_dispatcher import RenderError, render_via_phone
from app.scraper.block_detector import detect_block
from app.scraper.price_extractor import extract_price
from app.scraper.url_validator import validate_lowes_pdp_url

logger = get_logger(__name__)

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
    url = validate_lowes_pdp_url(raw_url)
    start = time.monotonic()
    deadline = start + settings.REQUEST_BUDGET_MS / 1000
    target_id = _product_id(url)

    last_error = "unknown"
    attempts = 0
    use_search = True
    last_priceless_html: str | None = None

    while attempts < settings.MAX_ATTEMPTS_PER_REQUEST and time.monotonic() < deadline:
        attempts += 1
        try:
            await _jitter_delay()
            remaining = deadline - time.monotonic()
            result = await render_via_phone(url, timeout_s=remaining, use_search=use_search)
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
            if error == "wrong-page-landed":
                use_search = False
            elif error == "price-not-found":
                # the page itself landed correctly and isn't blocked, it just has no price to
                # show right now (commonly a genuinely out of stock or discontinued item), so
                # this is a real, successfully scraped page, not a failed scrape
                last_priceless_html = html
            continue

        return ScrapeResult(
            html=html, price=price or "", attempts=attempts, latency_ms=(time.monotonic() - start) * 1000
        )

    if last_priceless_html is not None:
        return ScrapeResult(
            html=last_priceless_html, price="", attempts=attempts, latency_ms=(time.monotonic() - start) * 1000
        )

    raise ScrapeError(f"Failed after {attempts} attempt(s): {last_error}", 502, attempts, reason=last_error)
