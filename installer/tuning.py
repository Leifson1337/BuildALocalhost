"""Serving performance auto-optimizer (Stage 3).

Pure: given the hardware + goal (+ model footprint), compute the *most efficient* vLLM serving
parameters and a parallelism/replica strategy that maximises concurrent throughput.

Key idea for "as many users as fast as possible": instead of one big tensor-parallel model
hogging all GPUs, run the smallest tensor-parallel size that fits the model, then launch as
many **data-parallel replicas** as the GPUs allow and load-balance across them in the gateway.
More independent replicas → more concurrent requests served in parallel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from installer.hardware import SystemProfile

# Architectures whose vLLM build benefits from an fp8 KV cache (frees VRAM → more concurrency).
_FP8_KV_ARCHES = {"hopper", "blackwell", "ada"}

# Per-GPU-class serving baselines: (max_num_seqs, max_num_batched_tokens).
_BASELINES = {
    "datacenter_high": (384, 16384),
    "datacenter_mid": (256, 12288),
    "accelerator": (256, 12288),
    "consumer": (64, 4096),
    "cpu_only": (8, 2048),
}


@dataclass
class Tuning:
    tensor_parallel_size: int
    data_parallel_replicas: int
    gpu_memory_utilization: float
    max_num_seqs: int
    max_num_batched_tokens: int
    kv_cache_dtype: str            # "fp8" | "auto"
    enable_chunked_prefill: bool
    enable_prefix_caching: bool
    strategy: str                  # human-readable summary
    notes: list[str]


def optimize(system: SystemProfile, *, goal: str, model_vram_gb: float,
             optimize_for: str = "balanced") -> Tuning:
    """Compute optimal serving params. `optimize_for` ∈ throughput|latency|balanced."""
    notes: list[str] = []
    gpu_class = system.gpu_class
    g_total = max(1, system.total_gpu_count)
    per_gpu = system.primary_gpu.vram_gb if system.primary_gpu else 24.0
    arch = system.primary_gpu.architecture if system.primary_gpu else None

    base_seqs, base_tokens = _BASELINES.get(gpu_class, _BASELINES["consumer"])

    # fp8 KV cache where supported → smaller KV → more concurrent sequences.
    kv_dtype = "fp8" if (arch in _FP8_KV_ARCHES and not system.mig_active) else "auto"
    if kv_dtype == "fp8":
        notes.append("fp8 KV-cache: lower KV memory -> hoehere Parallelitaet.")
        base_seqs = int(base_seqs * 1.5)

    # Smallest tensor-parallel size that fits the model (+30% for KV/activations).
    need = model_vram_gb * 1.3
    tp_min = max(1, math.ceil(need / per_gpu)) if per_gpu > 0 else 1
    tp_min = min(tp_min, g_total)

    # Replica / parallelism strategy by goal + optimize_for.
    if goal == "highest_quality":
        tp = g_total                       # one large, accurate model across all GPUs
        replicas = 1
        strategy = "Ein großes Modell, Tensor-Parallel über alle GPUs (Qualität)."
    elif optimize_for == "latency" or goal == "low_latency":
        tp = max(tp_min, 2 if g_total >= 2 else 1)
        replicas = max(1, g_total // tp)
        base_seqs = max(16, base_seqs // 2)   # fewer concurrent seqs → lower latency
        strategy = f"TP={tp}, {replicas} Replica(s), Prefix-Cache + Chunked-Prefill (Latenz)."
    else:
        # throughput / many_users / balanced / default → maximise replicas.
        tp = tp_min
        replicas = max(1, g_total // tp)
        strategy = (f"TP={tp}, {replicas} datenparallele Replica(s) hinter dem Gateway "
                    f"-> maximaler paralleler Durchsatz.")
        if replicas == 1 and g_total > 1:
            notes.append("Modell belegt fast die ganze GPU-Gruppe; nur 1 Replica möglich. "
                         "Kleineres/quantisiertes Modell erlaubt mehr Replicas.")

    if optimize_for == "throughput":
        base_tokens = int(base_tokens * 1.5)
        base_seqs = int(base_seqs * 1.25)

    gpu_util = 0.92 if gpu_class.startswith("datacenter") else 0.88

    return Tuning(
        tensor_parallel_size=tp,
        data_parallel_replicas=replicas,
        gpu_memory_utilization=round(gpu_util, 2),
        max_num_seqs=base_seqs,
        max_num_batched_tokens=base_tokens,
        kv_cache_dtype=kv_dtype,
        enable_chunked_prefill=True,
        enable_prefix_caching=True,
        strategy=strategy,
        notes=notes,
    )
