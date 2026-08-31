import time
from dataclasses import dataclass


@dataclass
class RequestRecord:
    ok: bool
    latency_ms: float
    attempts: int
    blocked_retries: int
    timestamp: float


class Metrics:
    def __init__(self) -> None:
        self._records: list[RequestRecord] = []
        self._started_at = time.time()

    def record(self, entry: RequestRecord) -> None:
        self._records.append(entry)

    def reset(self) -> None:
        self._records = []
        self._started_at = time.time()

    def snapshot(self) -> dict:
        total = len(self._records)
        successes = [r for r in self._records if r.ok]
        errors = [r for r in self._records if not r.ok]
        latencies = sorted(r.latency_ms for r in successes)

        def avg(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        def percentile(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            idx = min(len(values) - 1, int((p / 100) * len(values)))
            return values[idx]

        avg_latency = avg(latencies)
        return {
            "windowStartedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._started_at)),
            "windowDurationSec": round(time.time() - self._started_at),
            "totalRequests": total,
            "successCount": len(successes),
            "errorCount": len(errors),
            "errorRatePct": round((len(errors) / total) * 100, 2) if total else 0,
            "avgLatencyMs": round(avg_latency),
            "p50LatencyMs": round(percentile(latencies, 50)),
            "p95LatencyMs": round(percentile(latencies, 95)),
            "maxLatencyMs": round(latencies[-1]) if latencies else 0,
            "avgAttempts": round(avg([r.attempts for r in self._records]), 2),
            "meetsLatencySla": avg_latency <= 60000,
            "meetsErrorRateSla": (len(errors) / total <= 0.05) if total else True,
        }


metrics = Metrics()
