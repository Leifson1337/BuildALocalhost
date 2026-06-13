"""Benchmark & light auto-tuning (Stage 3).

Fires concurrent chat-completion requests at the OpenAI-compatible gateway and measures
time-to-first-token (TTFT), end-to-end latency percentiles, and output tokens/sec. Produces
*measured* numbers to complement the heuristic capacity planner.

Requires a running stack. The percentile math is pure and unit-tested; the HTTP load loop
needs a live endpoint.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


@dataclass
class RequestSample:
    ok: bool
    ttft_s: float | None
    total_s: float
    output_tokens: int


@dataclass
class BenchmarkResult:
    requests: int
    concurrency: int
    successes: int
    failures: int
    ttft_p50: float
    ttft_p95: float
    ttft_p99: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    tokens_per_sec: float
    wall_s: float
    notes: list[str] = field(default_factory=list)


def percentiles(values: list[float], ps=(50, 95, 99)) -> dict[int, float]:
    """Nearest-rank percentiles. Pure; returns {p: value}. Empty -> zeros."""
    if not values:
        return {p: 0.0 for p in ps}
    s = sorted(values)
    out: dict[int, float] = {}
    for p in ps:
        k = max(0, min(len(s) - 1, int(round((p / 100.0) * len(s) + 0.5)) - 1))
        out[p] = round(s[k], 4)
    return out


def run(*, base_url: str, api_key: str, model: str = "main-chat",
        requests_total: int = 50, concurrency: int = 10,
        prompt: str = "Erkläre kurz, was ein Transformer-Modell ist.",
        max_tokens: int = 128) -> BenchmarkResult:
    import requests  # local import: only needed when actually benchmarking

    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def one() -> RequestSample:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
        }
        start = time.perf_counter()
        ttft = None
        tokens = 0
        try:
            with requests.post(url, json=body, headers=headers, stream=True, timeout=300) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    if ttft is None:
                        ttft = time.perf_counter() - start
                    if line.strip() == b"data: [DONE]":
                        break
                    tokens += 1
            return RequestSample(True, ttft, time.perf_counter() - start, tokens)
        except Exception:
            return RequestSample(False, None, time.perf_counter() - start, 0)

    wall_start = time.perf_counter()
    samples: list[RequestSample] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(one) for _ in range(requests_total)]
        for f in as_completed(futs):
            samples.append(f.result())
    wall = time.perf_counter() - wall_start

    ok = [s for s in samples if s.ok]
    ttfts = [s.ttft_s for s in ok if s.ttft_s is not None]
    lats = [s.total_s for s in ok]
    total_tokens = sum(s.output_tokens for s in ok)

    tp = percentiles(ttfts)
    lp = percentiles(lats)
    notes = []
    if not ok:
        notes.append("Keine erfolgreichen Requests — Stack erreichbar? Modell geladen?")
    return BenchmarkResult(
        requests=requests_total, concurrency=concurrency,
        successes=len(ok), failures=len(samples) - len(ok),
        ttft_p50=tp[50], ttft_p95=tp[95], ttft_p99=tp[99],
        latency_p50=lp[50], latency_p95=lp[95], latency_p99=lp[99],
        tokens_per_sec=round(total_tokens / wall, 1) if wall > 0 else 0.0,
        wall_s=round(wall, 2), notes=notes,
    )


def autotune(*, base_url: str, api_key: str, model: str,
             concurrency_levels=(1, 4, 8, 16, 32)) -> tuple[int, list[BenchmarkResult]]:
    """Sweep concurrency, return (best_concurrency_by_throughput, all_results).

    Note: this sweeps *client* concurrency only. Engine-side parameter sweeps
    (max_num_seqs, gpu_memory_utilization, …) require restarting the engine and are tracked
    as future work (ROADMAP).
    """
    results: list[BenchmarkResult] = []
    for c in concurrency_levels:
        results.append(run(base_url=base_url, api_key=api_key, model=model,
                           requests_total=max(c * 3, 12), concurrency=c))
    best = max(results, key=lambda r: r.tokens_per_sec, default=None)
    best_c = best.concurrency if best else (concurrency_levels[0] if concurrency_levels else 1)
    return best_c, results
