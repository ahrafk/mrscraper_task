import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.browser.browser_pool import browser_pool
from app.logging_config import configure_logging, get_logger
from app.scraper.block_detector import detect_block

configure_logging()
logger = get_logger(__name__)

TARGET_COUNT = 1200
OUTPUT_PATH = Path("test-urls/pdp-urls.txt")
MAX_PAGES_PER_SEED = 15
RESULTS_PER_PAGE_GUESS = 24

SEED_SEARCH_TERMS = [
    "refrigerator",
    "dishwasher",
    "washer",
    "dryer",
    "drill",
    "paint",
    "faucet",
    "lawn mower",
    "water heater",
    "ceiling fan",
    "grill",
    "garage door",
    "air conditioner",
    "toilet",
    "water filter",
]

PDP_LINK_RE = re.compile(r'href="(?:https://www\.lowes\.com)?(/pd/[^"?#]+/\d+)')


def seed_url(term: str) -> str:
    return f"https://www.lowes.com/search?searchTerm={quote(term)}"


def next_page_url(seed: str, page_num: int) -> str:
    parts = urlsplit(seed)
    query = parse_qs(parts.query)
    query["offset"] = [str(page_num * RESULTS_PER_PAGE_GUESS)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


async def extract_pdp_links(url: str) -> list[str]:
    session = await browser_pool.acquire_session()
    success = False
    try:
        page = session.page
        await page.goto(url, wait_until="commit", timeout=20000)
        await page.wait_for_timeout(3000)

        html = await page.content()
        found = sorted({f"https://www.lowes.com{path}" for path in PDP_LINK_RE.findall(html)})
        logger.info(
            "Harvested %d PDP links from %s (proxy=%s)",
            len(found),
            url,
            session.proxy.key if session.proxy else None,
        )
        success = not detect_block(None, html).blocked
        return found
    finally:
        await browser_pool.release_session(session, success)


HARVEST_CONCURRENCY = 6


async def main() -> None:
    collected: set[str] = set()
    lock = asyncio.Lock()
    stop = asyncio.Event()

    queue: asyncio.Queue[str] = asyncio.Queue()
    for term in SEED_SEARCH_TERMS:
        seed = seed_url(term)
        for page_num in range(MAX_PAGES_PER_SEED):
            queue.put_nowait(seed if page_num == 0 else next_page_url(seed, page_num))

    async def worker() -> None:
        while not stop.is_set():
            try:
                page_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                links = await extract_pdp_links(page_url)
                async with lock:
                    collected.update(links)
                    if len(collected) >= TARGET_COUNT:
                        stop.set()
            except Exception as err:
                logger.warning("Failed to harvest %s — skipping: %s", page_url, err)
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(HARVEST_CONCURRENCY)))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(sorted(collected)) + "\n", encoding="utf-8")
    logger.info("Harvest complete: %d URLs written to %s", len(collected), OUTPUT_PATH)
    if len(collected) < 1000:
        logger.warning(
            "Fewer than 1000 URLs harvested (%d) — add more seed terms/pages, or paste extra "
            "PDP URLs into the output file by hand.",
            len(collected),
        )
    await browser_pool.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
