"""Evaluation / golden-dataset runner (Stage 3).

Runs a dataset of prompts against the gateway and scores responses (contains/equals/regex).
Use it for quality checks and regression after updates. The scoring is pure and unit-tested;
the HTTP run needs a live endpoint.

Dataset format (YAML):

    model: main-chat            # default model for all cases (optional)
    cases:
      - id: greeting
        prompt: "Sag nur das Wort: Hallo"
        expect: { type: contains, value: "Hallo" }
      - id: math
        prompt: "Was ist 2+2? Antworte nur mit der Zahl."
        expect: { type: regex, value: "\\b4\\b" }
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CaseResult:
    id: str
    ok: bool
    latency_s: float
    got: str = ""
    error: str = ""


@dataclass
class EvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    latency_avg_s: float
    results: list[CaseResult] = field(default_factory=list)


def score(expect: dict, output: str) -> bool:
    """Pure: does `output` satisfy the expectation? Unknown types fail closed."""
    etype = (expect or {}).get("type", "contains")
    value = str((expect or {}).get("value", ""))
    text = output or ""
    if etype == "equals":
        return text.strip() == value.strip()
    if etype == "contains":
        return value.lower() in text.lower()
    if etype == "icontains":
        return value.lower() in text.lower()
    if etype == "regex":
        try:
            return re.search(value, text) is not None
        except re.error:
            return False
    if etype == "not_contains":
        return value.lower() not in text.lower()
    return False


def run(*, base_url: str, api_key: str, dataset: dict,
        default_model: str = "main-chat", max_tokens: int = 256) -> EvalReport:
    import requests

    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    model_default = dataset.get("model", default_model)
    cases = dataset.get("cases", []) or []

    import time
    results: list[CaseResult] = []
    for case in cases:
        cid = str(case.get("id", "?"))
        body = {
            "model": case.get("model", model_default),
            "messages": [{"role": "user", "content": case.get("prompt", "")}],
            "max_tokens": max_tokens,
        }
        start = time.perf_counter()
        try:
            r = requests.post(url, json=body, headers=headers, timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            ok = score(case.get("expect", {}), content)
            results.append(CaseResult(cid, ok, time.perf_counter() - start, got=content[:300]))
        except Exception as exc:  # noqa: BLE001
            results.append(CaseResult(cid, False, time.perf_counter() - start, error=str(exc)))

    return summarize(results)


def summarize(results: list[CaseResult]) -> EvalReport:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    avg = round(sum(r.latency_s for r in results) / total, 3) if total else 0.0
    return EvalReport(
        total=total, passed=passed, failed=total - passed,
        pass_rate=round(passed / total, 3) if total else 0.0,
        latency_avg_s=avg, results=results,
    )
