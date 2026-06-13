"""Recommendation engine.

Pure mapping: (SystemProfile, goal) -> Recommendation. Reads catalogs; never hard-codes a
single GPU model — only architecture-class and interconnect rules (ADR-0006). Testable
without a GPU.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from installer import catalog
from installer.hardware import SystemProfile

GOALS = {
    "high_throughput_chat",
    "low_latency",
    "many_users",
    "highest_quality",
    "rag",
    "agents_mcp",
    "development",
}


@dataclass
class Alternative:
    name: str
    engine: str
    rationale: str


@dataclass
class Recommendation:
    primary_engines: list[str]
    advanced_engines: list[str]
    precision: list[str]
    tensor_parallel_size: int
    pipeline_parallel_size: int
    data_parallel_replicas: int
    runtime: str                      # docker_compose | kubernetes
    gpu_memory_utilization: float
    alternatives: list[Alternative] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def primary_engine(self) -> str:
        return self.primary_engines[0] if self.primary_engines else "vllm"


def recommend(system: SystemProfile, goal: str = "high_throughput_chat") -> Recommendation:
    if goal not in GOALS:
        goal = "high_throughput_chat"

    warnings: list[str] = []
    gpu_class = system.gpu_class
    gpu_count = system.total_gpu_count
    primary = system.primary_gpu
    interconnect = primary.interconnect if primary else "unknown"

    engines = _engine_order(gpu_class)
    precision = _precision(primary)
    tp, pp, dp = _parallelism(system, interconnect, warnings, goal)
    runtime = "kubernetes" if gpu_count > 8 else "docker_compose"
    gpu_util = 0.90 if gpu_class.startswith("datacenter") else 0.85

    _engine_goal_adjust(engines, goal)
    _emit_warnings(system, gpu_class, interconnect, warnings)

    alts = _alternatives(engines, gpu_class)

    return Recommendation(
        primary_engines=engines[:2] or ["vllm"],
        advanced_engines=engines[2:] or ["tgi"],
        precision=precision,
        tensor_parallel_size=tp,
        pipeline_parallel_size=pp,
        data_parallel_replicas=dp,
        runtime=runtime,
        gpu_memory_utilization=gpu_util,
        alternatives=alts,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- internals

def _engine_order(gpu_class: str) -> list[str]:
    pref = catalog.load_engines().get("preference_by_class", {})
    if gpu_class in pref:
        return list(pref[gpu_class])
    # Map catalog hardware classes onto engine-preference buckets.
    if gpu_class == "datacenter_high":
        return list(pref.get("datacenter_high", ["vllm", "sglang", "tgi"]))
    if gpu_class in ("datacenter_mid", "accelerator"):
        return list(pref.get("datacenter_mid", ["vllm", "sglang", "tgi"]))
    if gpu_class == "cpu_only":
        return list(pref.get("cpu_only", ["llama_cpp", "ollama"]))
    return list(pref.get("consumer", ["vllm", "ollama", "llama_cpp"]))


def _engine_goal_adjust(engines: list[str], goal: str) -> None:
    """Reorder in-place to favour the engine that best fits the goal."""
    def promote(eid: str) -> None:
        if eid in engines:
            engines.remove(eid)
            engines.insert(0, eid)

    if goal in ("low_latency", "agents_mcp"):
        promote("sglang")
    elif goal in ("high_throughput_chat", "many_users", "highest_quality"):
        promote("vllm")
    elif goal == "development":
        promote("ollama")


def _precision(primary) -> list[str]:
    if primary is None:
        return ["bfloat16"]
    # Prefer what the catalog says the GPU supports; keep order meaningful.
    order = ["bfloat16", "fp8", "fp4", "nvfp4", "fp16", "int8", "gguf"]
    supported = [p for p in order if p in (primary.precision or [])]
    return supported or ["bfloat16"]


def _parallelism(system: SystemProfile, interconnect: str, warnings: list[str], goal: str):
    """Return (tensor_parallel, pipeline_parallel, data_parallel_replicas)."""
    gpu_count = system.total_gpu_count
    if gpu_count <= 1:
        return 1, 1, 1

    hint = catalog.interconnect_parallelism_hint(interconnect)
    if hint == "tensor_parallel":
        return gpu_count, 1, 1
    if hint == "pipeline_parallel":
        return 1, gpu_count, 1
    # data_parallel_replicas (PCIe-only / unknown): avoid big TP across slow links.
    warnings.append(
        f"Interconnect '{interconnect}' is not high-bandwidth; preferring "
        f"{gpu_count} data-parallel replicas over large tensor parallelism."
    )
    return 1, 1, gpu_count


def _emit_warnings(system, gpu_class, interconnect, warnings: list[str]) -> None:
    primary = system.primary_gpu
    if primary and primary.vram_gb <= 24:
        warnings.append(
            f"Low VRAM ({primary.vram_gb} GB/GPU): use quantized models (AWQ/GPTQ/GGUF) "
            "and modest context lengths."
        )
    if primary and not primary.authoritative:
        warnings.append(
            f"{primary.model} VRAM is a catalog estimate, not measured — confirm with NVML."
        )
    if system.docker_gpu_ok is False:
        warnings.append("NVIDIA Docker runtime not detected — GPU containers will fail.")
    if gpu_class == "cpu_only":
        warnings.append("No GPU: expect very low throughput; use small GGUF models only.")
    if system.mig_active:
        warnings.append("MIG is enabled: each model is bound to a GPU slice; tensor parallelism "
                        "across full GPUs is unavailable until MIG is disabled.")
    elif system.mig_capable and system.total_gpu_count >= 2:
        warnings.append("GPUs are MIG-capable: consider partitioning for many small concurrent "
                        "models (see docs). Large models need full GPUs (MIG off).")


def _alternatives(engines: list[str], gpu_class: str) -> list[Alternative]:
    alts = [
        Alternative("A — Max throughput", "vllm",
                    "Tensor parallel across GPUs, OpenAI-compatible, many concurrent users."),
        Alternative("B — Low latency / agents", "sglang",
                    "Prefix caching, good for tool-use and repeated prompts."),
    ]
    if gpu_class == "datacenter_high":
        alts.append(Alternative("C — NVIDIA enterprise", "nim",
                                 "Validated NVIDIA containers / Triton+TensorRT-LLM; more setup."))
    alts.append(Alternative("D — Simplicity", "ollama",
                            "Ollama + Open WebUI; easy, not max GPU utilisation."))
    return alts
