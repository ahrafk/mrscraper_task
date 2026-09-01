import asyncio
import os
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:3000")
TARGET_COUNT = int(os.environ.get("HARVEST_TARGET", "1200"))
OUTPUT_PATH = Path("test-urls/pdp-urls.txt")
MAX_PAGES_PER_SEED = 15
RESULTS_PER_PAGE_GUESS = 24
HARVEST_CONCURRENCY = int(os.environ.get("HARVEST_CONCURRENCY", "3"))
MIN_DELAY_S = float(os.environ.get("HARVEST_MIN_DELAY_S", "2"))
MAX_DELAY_S = float(os.environ.get("HARVEST_MAX_DELAY_S", "6"))

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


async def extract_pdp_links(client: httpx.AsyncClient, url: str) -> list[str]:
    resp = await client.get(f"{API_BASE}/render", params={"url": url}, timeout=70)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
    html = resp.json().get("html", "")
    found = sorted({f"https://www.lowes.com{path}" for path in PDP_LINK_RE.findall(html)})
    print(f"got {len(found)} links from {url}")
    return found


async def main() -> None:
    collected: set[str] = set()
    lock = asyncio.Lock()
    stop = asyncio.Event()

    queue: asyncio.Queue[str] = asyncio.Queue()
    for term in SEED_SEARCH_TERMS:
        seed = seed_url(term)
        for page_num in range(MAX_PAGES_PER_SEED):
            queue.put_nowait(seed if page_num == 0 else next_page_url(seed, page_num))

    async def worker(client: httpx.AsyncClient) -> None:
        while not stop.is_set():
            try:
                page_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await asyncio.sleep(random.uniform(MIN_DELAY_S, MAX_DELAY_S))
            try:
                links = await extract_pdp_links(client, page_url)
                async with lock:
                    collected.update(links)
                    if len(collected) >= TARGET_COUNT:
                        stop.set()
            except Exception as err:
                print(f"failed on {page_url}: {err}")
            finally:
                queue.task_done()

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(worker(client) for _ in range(HARVEST_CONCURRENCY)))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if OUTPUT_PATH.exists():
        existing = {line.strip() for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}
    combined = sorted(existing | collected)
    OUTPUT_PATH.write_text("\n".join(combined) + "\n", encoding="utf-8")
    print(f"harvest complete: {len(collected)} new, {len(combined)} total written to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
