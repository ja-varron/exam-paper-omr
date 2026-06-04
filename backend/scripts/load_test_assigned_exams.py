from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass

import requests


@dataclass
class Sample:
    latency_ms: float
    status_code: int
    ok: bool


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def request_once(url: str, timeout_seconds: float) -> Sample:
    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=timeout_seconds)
        latency_ms = (time.perf_counter() - start) * 1000.0
        ok = response.status_code < 400
        return Sample(latency_ms=latency_ms, status_code=response.status_code, ok=ok)
    except requests.RequestException:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Sample(latency_ms=latency_ms, status_code=0, ok=False)


def run_load(
    base_url: str,
    student_id: str,
    requests_per_worker: int,
    concurrency: int,
    timeout_seconds: float,
    limit: int,
    fresh: bool,
) -> list[Sample]:
    path = f"/api/students/{student_id}/assigned-exams?limit={limit}&offset=0"
    if fresh:
        path += "&fresh=1"
    url = base_url.rstrip("/") + path

    samples: list[Sample] = []
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for _ in range(concurrency):
            for _ in range(requests_per_worker):
                futures.append(executor.submit(request_once, url, timeout_seconds))

        for future in as_completed(futures):
            samples.append(future.result())

    elapsed = time.perf_counter() - started
    total = len(samples)
    successes = sum(1 for sample in samples if sample.ok)
    failures = total - successes
    latencies = [sample.latency_ms for sample in samples]
    status_counts = Counter(sample.status_code for sample in samples)

    print("LOAD_TEST_RESULTS")
    print(f"URL={url}")
    print(f"TOTAL_REQUESTS={total}")
    print(f"SUCCESSFUL={successes}")
    print(f"FAILED={failures}")
    print(f"DURATION_SECONDS={elapsed:.3f}")
    print(f"THROUGHPUT_REQ_PER_SEC={(total / elapsed) if elapsed > 0 else 0:.2f}")
    print(f"LATENCY_MEAN_MS={(statistics.fmean(latencies) if latencies else 0.0):.2f}")
    print(f"LATENCY_P50_MS={percentile(latencies, 50):.2f}")
    print(f"LATENCY_P95_MS={percentile(latencies, 95):.2f}")
    print(f"LATENCY_P99_MS={percentile(latencies, 99):.2f}")
    for status_code, count in sorted(status_counts.items(), key=lambda item: item[0]):
        print(f"STATUS_{status_code}={count}")

    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test student assigned-exams endpoint")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests-per-worker", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--fresh", action="store_true", help="Bypass endpoint response cache")

    args = parser.parse_args()

    run_load(
        base_url=args.base_url,
        student_id=args.student_id,
        requests_per_worker=max(1, args.requests_per_worker),
        concurrency=max(1, args.concurrency),
        timeout_seconds=max(1.0, args.timeout_seconds),
        limit=max(1, min(200, args.limit)),
        fresh=bool(args.fresh),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
