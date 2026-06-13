"""Capacity planner (Stage 3).

Pure, heuristic estimate of how many concurrent users a node can sustain for a model, from
VRAM, context length, and workload shape. Clearly marked as an ESTIMATE — the benchmark
module produces measured numbers (see installer/benchmark.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from installer import catalog
from installer.hardware import SystemProfile


@dataclass
class Workload:
    concurrent_users: int = 10
    avg_prompt_tokens: int = 1024
    avg_output_tokens: int = 512
    latency_target_s: float = 5.0


@dataclass
class CapacityEstimate:
    model: str
    total_vram_gb: float
    model_weights_gb: float
    kv_cache_budget_gb: float
    per_request_gb: float
    max_concurrent_requests: int
    meets_target: bool
    throughput_class: str            # high | medium | low | infeasible
    notes: list[str]


# Very rough KV-cache cost per 1k tokens for a mid-size (~7-13B) bf16 model, in GB.
# Real value depends on layers/heads/dtype; deliberately conservative. ESTIMATE ONLY.
_KV_GB_PER_1K_TOKENS = 0.5


def estimate(system: SystemProfile, model: str, workload: Workload) -> CapacityEstimate:
    notes = ["Heuristische Schätzung — bitte mit `benchmark` verifizieren."]
    total_vram = system.total_vram_gb
    weights = _model_weights_gb(model)

    if total_vram <= 0:
        return CapacityEstimate(model, 0, weights, 0, 0, 0, False, "infeasible",
                                notes + ["Keine GPU/VRAM erkannt."])

    # Reserve weights (replicated per tensor-parallel shard is already in total VRAM budget
    # because TP splits weights across GPUs → approximate weights as a single copy here).
    kv_budget = max(0.0, total_vram * 0.85 - weights)
    tokens_per_req = workload.avg_prompt_tokens + workload.avg_output_tokens
    per_req = (tokens_per_req / 1000.0) * _KV_GB_PER_1K_TOKENS
    max_concurrent = int(kv_budget / per_req) if per_req > 0 else 0

    if weights >= total_vram:
        return CapacityEstimate(model, total_vram, weights, kv_budget, per_req, 0, False,
                                "infeasible", notes + [
                                    f"Modellgewichte (~{weights} GB) passen nicht in {total_vram} GB VRAM."])

    meets = max_concurrent >= workload.concurrent_users
    cls = _throughput_class(max_concurrent)
    if not meets:
        notes.append(f"Geschätzte Parallelität (~{max_concurrent}) < gewünschte "
                     f"{workload.concurrent_users} Nutzer. Kleineres Modell, mehr GPUs, "
                     "kürzere Kontexte oder Quantisierung erwägen.")
    if workload.avg_prompt_tokens + workload.avg_output_tokens > 8192:
        notes.append("Lange Kontexte erhöhen den KV-Cache-Bedarf stark.")

    return CapacityEstimate(model, total_vram, weights, round(kv_budget, 1),
                            round(per_req, 3), max_concurrent, meets, cls, notes)


def _model_weights_gb(model: str) -> float:
    cats = catalog.load_models().get("categories", {})
    for cat in cats.values():
        for sug in cat.get("suggestions", []):
            if sug.get("hf_id") == model:
                # min_vram_gb already approximates weights + a little overhead.
                return float(sug.get("min_vram_gb", 16))
    return 16.0


def _throughput_class(max_concurrent: int) -> str:
    if max_concurrent >= 64:
        return "high"
    if max_concurrent >= 16:
        return "medium"
    if max_concurrent >= 1:
        return "low"
    return "infeasible"
