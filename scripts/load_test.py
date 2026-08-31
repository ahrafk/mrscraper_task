import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:3000")
URLS_FILE = Path(os.environ.get("URLS_FILE", "test-urls/pdp-urls.txt"))
CONCURRENCY = int(os.environ.get("LOADTEST_CONCURRENCY", "10"))
MAX_REQUESTS = int(os.environ.get("LOADTEST_MAX_REQUESTS", "100000"))
MAX_DURATION_S = int(os.environ.get("LOADTEST_MAX_DURATION_MS", str(60 * 60 * 1000))) / 1000
REPORT_PATH = Path(os.environ.get("LOADTEST_REPORT", "load-test-report.json"))


@dataclass
class RequestResult:
    url: str
    ok: bool
    status: int
    latency_ms: float
    price_found: Optional[str] = None
    error: Optional[str] = None


def load_urls() -> list[str]:
    if not URLS_FILE.exists():
        raise SystemExit(f"{URLS_FILE} not found — run 'python scripts/harvest_urls.py' first (see README).")
    urls = [line.strip() for line in URLS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        raise SystemExit(f"{URLS_FILE} has no URLs — run 'python scripts/harvest_urls.py' first (see README).")
    return urls


async def hit(client: httpx.AsyncClient, url: str) -> RequestResult:
    start = time.monotonic()
    try:
        res = await client.get(
            f"{API_BASE}/lowes", params={"productUrl": url, "format": "json"}, timeout=70
        )
        latency_ms = (time.monotonic() - start) * 1000
        if res.status_code >= 400:
            return RequestResult(url, False, res.status_code, latency_ms, error=res.text[:300])
        body = res.json()
        return RequestResult(url, True, res.status_code, latency_ms, price_found=body.get("price"))
    except Exception as err:
        return RequestResult(
            url, False, 0, (time.monotonic() - start) * 1000, error=str(err)
        )


def print_progress(results: list[RequestResult]) -> None:
    n = len(results)
    ok_count = sum(1 for r in results if r.ok)
    avg_latency = sum(r.latency_ms for r in results) / n
    err_rate = (n - ok_count) / n * 100
    print(f"[{n} done] ok={ok_count} errRate={err_rate:.1f}% avgLatency={avg_latency:.0f}ms")


async def run_pool(
    urls: list[str], concurrency: int, deadline: float, max_requests: int
) -> list[RequestResult]:
    results: list[RequestResult] = []
    lock = asyncio.Lock()
    counter = 0

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal counter
        while time.monotonic() < deadline and len(results) < max_requests:
            async with lock:
                url = urls[counter % len(urls)]
                counter += 1
            result = await hit(client, url)
            results.append(result)
            if len(results) % 25 == 0:
                print_progress(results)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
    return results


async def main() -> None:
    urls = load_urls()
    if len(urls) < 1000:
        print(
            f"Only {len(urls)} unique URLs in {URLS_FILE} (challenge asks for 1000+ distinct PDPs). "
            "The run will cycle through them repeatedly to still exercise duration/latency/error-rate "
            "targets, but harvest more URLs for a fully faithful volume test."
        )
    print(
        f"Load-testing against {API_BASE} | urls={len(urls)} concurrency={CONCURRENCY} "
        f"duration<={int(MAX_DURATION_S)}s maxRequests={MAX_REQUESTS}"
    )

    deadline = time.monotonic() + MAX_DURATION_S
    started = time.monotonic()
    results = await run_pool(urls, CONCURRENCY, deadline, MAX_REQUESTS)
    duration_s = time.monotonic() - started

    ok_results = [r for r in results if r.ok]
    err_results = [r for r in results if not r.ok]
    avg_latency_ms = sum(r.latency_ms for r in ok_results) / len(ok_results) if ok_results else 0
    error_rate_pct = (len(err_results) / len(results) * 100) if results else 0

    summary = {
        "totalRequests": len(results),
        "successCount": len(ok_results),
        "errorCount": len(err_results),
        "errorRatePct": round(error_rate_pct, 2),
        "avgLatencyMs": round(avg_latency_ms),
        "durationSec": round(duration_s),
        "meetsVolumeCriterion": len(ok_results) >= 1000,
        "meetsLatencyCriterion": avg_latency_ms <= 60000,
        "meetsErrorRateCriterion": error_rate_pct <= 5,
        "meetsDurationCriterion": duration_s >= 3600,
    }

    print("\n=== Load test summary ===")
    print(json.dumps(summary, indent=2))

    REPORT_PATH.write_text(
        json.dumps({"summary": summary, "sampleErrors": [asdict(r) for r in err_results[:50]]}, indent=2),
        encoding="utf-8",
    )
    print(f"\nFull summary (+ up to 50 sample errors) written to {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
