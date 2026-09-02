import time
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.logging_config import get_logger
from app.metrics import RequestRecord, metrics
from app.phone_relay.registry import phone_registry
from app.phone_relay.render_dispatcher import RenderError, render_via_phone
from app.queue.scrape_queue import enqueue, queue_status
from app.scraper.scrape_lowes_pdp import ScrapeError, scrape_lowes_pdp
from app.scraper.url_validator import InvalidProductUrlError

logger = get_logger(__name__)
router = APIRouter()


@router.get("/lowes")
async def get_lowes_pdp(
    productUrl: str = Query(..., min_length=1, description="Full Lowe's PDP URL"),
    format: Literal["html", "json"] = Query(
        "html", description="html: raw rendered HTML body. json: metadata + html."
    ),
):
    start = time.monotonic()
    try:
        result = await enqueue(lambda: scrape_lowes_pdp(productUrl))
        metrics.record(
            RequestRecord(
                ok=True,
                latency_ms=result.latency_ms,
                attempts=result.attempts,
                blocked_retries=result.attempts - 1,
                timestamp=time.time(),
            )
        )
        if format == "json":
            return {
                "productUrl": productUrl,
                "price": result.price,
                "attempts": result.attempts,
                "latencyMs": result.latency_ms,
                "html": result.html,
            }
        return HTMLResponse(
            content=result.html,
            headers={"X-Price-Found": result.price, "X-Attempts": str(result.attempts)},
        )
    except InvalidProductUrlError as err:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "message": str(err)})
    except ScrapeError as err:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.record(
            RequestRecord(
                ok=False,
                latency_ms=latency_ms,
                attempts=err.attempts,
                blocked_retries=err.attempts,
                timestamp=time.time(),
            )
        )
        logger.error("Scrape failed for %s: %s", productUrl, err)
        return JSONResponse(
            status_code=err.status_code, content={"error": "scrape_failed", "message": str(err)}
        )
    except Exception as err:
        latency_ms = (time.monotonic() - start) * 1000
        metrics.record(
            RequestRecord(ok=False, latency_ms=latency_ms, attempts=0, blocked_retries=0, timestamp=time.time())
        )
        logger.exception("Unexpected error scraping %s", productUrl)
        return JSONResponse(status_code=500, content={"error": "scrape_failed", "message": str(err)})


@router.get("/render")
async def render_url(url: str = Query(..., min_length=1)):
    if not url.startswith("https://www.lowes.com/"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "message": "url must be under https://www.lowes.com/"},
        )
    try:
        result = await enqueue(lambda: render_via_phone(url))
        return {
            "url": url,
            "status": result.get("status"),
            "finalUrl": result.get("final_url"),
            "html": result.get("html", ""),
        }
    except RenderError as err:
        return JSONResponse(status_code=502, content={"error": "render_failed", "message": str(err)})


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "queue": queue_status(),
        "phonesConnected": phone_registry.count,
        "phoneIds": list(phone_registry._phones.keys()),
    }


@router.get("/metrics")
async def get_metrics():
    return metrics.snapshot()


@router.get("/metrics/reset")
async def reset_metrics():
    metrics.reset()
    return {"reset": True}
