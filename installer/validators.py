"""Pre-flight validation.

Returns a list of Issues. Fatal issues must abort before rendering/starting; warnings are
shown but allow continuing. Kept mostly pure: host-touching checks (ports) are isolated and
skipped in dry-run.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Literal

from installer import catalog
from installer.profile_builder import ResolvedConfig

Severity = Literal["fatal", "warning", "info"]


@dataclass
class Issue:
    severity: Severity
    code: str
    message: str


def validate(cfg: ResolvedConfig, *, check_ports: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    issues += _check_compatibility(cfg)
    issues += _check_multimodel(cfg)
    issues += _check_vram(cfg)
    issues += _check_ram(cfg)
    issues += _check_storage(cfg)
    issues += _check_docker_gpu(cfg)
    issues += _check_model_repository(cfg)
    issues += _check_hf_token(cfg)
    issues += _check_license(cfg)
    issues += _check_mcp(cfg)
    issues += _check_policy(cfg)
    issues += _check_supply_chain(cfg)
    issues += _check_rag(cfg)
    issues += _check_public_exposure(cfg)
    if check_ports:
        issues += _check_ports(cfg)
    return issues


def has_fatal(issues: list[Issue]) -> bool:
    return any(i.severity == "fatal" for i in issues)


# --------------------------------------------------------------------------- checks

def _check_multimodel(cfg: ResolvedConfig) -> list[Issue]:
    """Warn that concurrently-served models share the node's VRAM, and sum their floors."""
    models = cfg.data.get("inference", {}).get("models", [])
    if len(models) <= 1:
        return []
    total_need = 0.0
    known = True
    for m in models:
        need = _model_min_vram(m.get("model", ""))
        if need is None:
            known = False
        else:
            total_need += need
    have = cfg.system.total_vram_gb
    msg = (f"{len(models)} models served concurrently share {have} GB VRAM. "
           "Lower gpu_memory_utilization per model or use separate replicas/GPUs.")
    if known and have > 0 and total_need > have:
        return [Issue("fatal", "vram.multimodel",
                      f"Sum of model VRAM floors (~{round(total_need)} GB) exceeds available "
                      f"{have} GB across {len(models)} concurrent models.")]
    return [Issue("warning", "vram.multimodel", msg)]


def _check_compatibility(cfg: ResolvedConfig) -> list[Issue]:
    """Engine × model-format × runtime × precision feasibility (compatibility.yaml)."""
    issues: list[Issue] = []
    compat = catalog.load_compatibility()
    engine_support = compat.get("engine_format_support", {}).get(cfg.engine)
    if not engine_support:
        return [Issue("info", "compat.unknown_engine",
                      f"No compatibility data for engine '{cfg.engine}'.")]

    kind = catalog.infer_model_kind(cfg.model)
    # 1) format support
    if kind in (engine_support.get("not") or []):
        issues.append(Issue("fatal", "compat.format",
                            f"Engine '{cfg.engine}' does not support '{kind}' models "
                            f"(model: {cfg.model}). Choose a compatible engine "
                            f"(e.g. ollama/llama_cpp for GGUF, vLLM for safetensors)."))
    elif kind not in (engine_support.get("formats") or []) and kind != "embedding":
        issues.append(Issue("warning", "compat.format_unverified",
                            f"Model format '{kind}' not listed as supported by '{cfg.engine}'."))

    # 2) runtime (cuda/rocm/cpu)
    runtime = cfg.runtime_kind
    supported_runtimes = engine_support.get("runtimes") or ["cuda"]
    if runtime not in supported_runtimes:
        sev = "fatal" if runtime == "rocm" else "warning"
        issues.append(Issue(sev, "compat.runtime",
                            f"Engine '{cfg.engine}' does not support the '{runtime}' runtime "
                            f"(supported: {', '.join(supported_runtimes)})."))

    # 3) multi-GPU
    if cfg.system.total_gpu_count > 1 and not engine_support.get("multi_gpu", False):
        issues.append(Issue("warning", "compat.multi_gpu",
                            f"Engine '{cfg.engine}' is single-GPU; extra GPUs will be idle. "
                            "Consider data-parallel replicas or another engine."))

    # 4) precision vs architecture
    arch = (cfg.system.primary_gpu.architecture if cfg.system.primary_gpu else None)
    dtype = cfg.data["inference"].get("dtype")
    if arch and dtype:
        allowed = compat.get("precision_by_architecture", {}).get(arch)
        if allowed and dtype not in allowed:
            issues.append(Issue("warning", "compat.precision",
                                f"Precision '{dtype}' may be unsupported on {arch} "
                                f"(supported: {', '.join(allowed)}). Falling back to bfloat16 advised."))
    return issues


def _model_min_vram(model: str) -> float | None:
    cats = catalog.load_models().get("categories", {})
    for cat in cats.values():
        for sug in cat.get("suggestions", []):
            if sug.get("hf_id") == model:
                return float(sug.get("min_vram_gb", 0)) or None
    return None


def _check_vram(cfg: ResolvedConfig) -> list[Issue]:
    sys = cfg.system
    need = _model_min_vram(cfg.model)
    if need is None:
        return [Issue("info", "vram.unknown",
                      f"VRAM requirement for '{cfg.model}' unknown (not in curated catalog).")]
    have = sys.total_vram_gb
    if have <= 0:
        return [Issue("warning", "vram.no_gpu",
                      "No GPU VRAM detected (simulation/CPU). Skipping VRAM feasibility.")]
    if need > have:
        return [Issue("fatal", "vram.insufficient",
                      f"Model '{cfg.model}' needs ~{need} GB VRAM but only {have} GB available. "
                      "Choose a smaller/quantized model or add GPUs.")]
    if need > have * 0.85:
        return [Issue("warning", "vram.tight",
                      f"VRAM is tight (~{need} GB needed of {have} GB). KV-cache/context may be limited.")]
    return []


def _check_ram(cfg: ResolvedConfig) -> list[Issue]:
    ram = cfg.system.ram_gb
    if ram is None:
        return []
    if ram < 32:
        return [Issue("warning", "ram.low",
                      f"Only {ram} GB system RAM detected; 64 GB+ recommended for serving.")]
    return []


def _check_storage(cfg: ResolvedConfig) -> list[Issue]:
    free = cfg.system.storage_free_gb
    if free is None:
        return []
    if free < 100:
        return [Issue("fatal", "storage.insufficient",
                      f"Only {free} GB free; model weights + caches need substantially more.")]
    if free < 300:
        return [Issue("warning", "storage.low",
                      f"{free} GB free; large models may not fit. 500 GB+ recommended.")]
    return []


def _check_model_repository(cfg: ResolvedConfig) -> list[Issue]:
    """Triton/NIM-style engines need a prepared model repository / per-model image."""
    engine = catalog.get_engine(cfg.engine) or {}
    if engine.get("needs_model_repository"):
        return [Issue("info", "engine.model_repository",
                      f"Engine '{cfg.engine}' needs a prepared Triton model repository at "
                      "/models/model_repository (TensorRT-LLM engines must be pre-compiled). "
                      "Mount it before starting.")]
    return []


def _check_docker_gpu(cfg: ResolvedConfig) -> list[Issue]:
    engine = catalog.get_engine(cfg.engine) or {}
    if engine.get("gpu") != "required":
        return []
    ok = cfg.system.docker_gpu_ok
    if ok is False:
        return [Issue("fatal", "docker.no_gpu",
                      "Engine requires GPU but NVIDIA Docker runtime is not available. "
                      "Install the NVIDIA Container Toolkit.")]
    if ok is None and cfg.system.mode == "auto":
        return [Issue("warning", "docker.gpu_unknown",
                      "Could not verify Docker GPU access; ensure NVIDIA Container Toolkit is set up.")]
    return []


def _check_hf_token(cfg: ResolvedConfig) -> list[Issue]:
    if not _model_is_gated(cfg.model):
        return []
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        return [Issue("fatal", "hf.token_missing",
                      f"Model '{cfg.model}' is gated but no HF_TOKEN is set. "
                      "Export HF_TOKEN with access to this model.")]
    return [Issue("info", "hf.token_present",
                  f"Gated model '{cfg.model}': HF_TOKEN present (access not verified offline).")]


def _model_is_gated(model: str) -> bool:
    cats = catalog.load_models().get("categories", {})
    for cat in cats.values():
        for sug in cat.get("suggestions", []):
            if sug.get("hf_id") == model:
                return bool(sug.get("gated", False))
    return False


def _check_license(cfg: ResolvedConfig) -> list[Issue]:
    """Surface gated/license obligations before download (Stage 2).

    We cannot verify license terms offline; we flag gated models and remind the user to
    confirm commercial-use / public-hosting rights.
    """
    if _model_is_gated(cfg.model):
        return [Issue("info", "license.gated",
                      f"'{cfg.model}' is gated: accept its license on Hugging Face and ensure "
                      "your HF token has access. Verify commercial-use / hosting rights.")]
    return [Issue("info", "license.check",
                  f"Confirm '{cfg.model}' license permits your use (commercial / public hosting).")]


def _check_mcp(cfg: ResolvedConfig) -> list[Issue]:
    """Validate selected MCP servers against the security profile (deny dangerous on public)."""
    if not cfg.mcp_enabled:
        return []
    issues: list[Issue] = []
    sec = catalog.get_security_profile(cfg.security_profile_id) or {}
    allow_dangerous = bool(sec.get("allow_dangerous_mcp", False))
    for srv_id in cfg.data.get("mcp", {}).get("servers", []) or []:
        srv = catalog.get_mcp_server(srv_id)
        if srv is None:
            issues.append(Issue("warning", "mcp.unknown",
                                f"Unknown MCP server '{srv_id}' (not in catalog)."))
            continue
        if srv.get("tier") == "dangerous_requires_confirmation" and not allow_dangerous:
            issues.append(Issue("fatal", "mcp.dangerous",
                                f"Dangerous MCP server '{srv_id}' is not allowed under security "
                                f"profile '{cfg.security_profile_id}'. Enable it only on local_only "
                                "or with explicit override."))
    return issues


def _check_rag(cfg: ResolvedConfig) -> list[Issue]:
    """Flag external RAG efficiency methods (LEANN/TurboQuant/TurboVec) for image/integration verify."""
    if not cfg.rag_enabled:
        return []
    issues: list[Issue] = []
    rd = cfg.data.get("rag", {})
    rag_cat = catalog.load_rag()
    vdb_id = rd.get("vector_db", "qdrant")
    vdb = next((v for v in rag_cat.get("vector_dbs", []) if v.get("id") == vdb_id), {})
    if vdb.get("verify_image"):
        issues.append(Issue("warning", "rag.verify_image",
                            f"Vector index '{vdb_id}' uses a placeholder/unverified image "
                            f"(override via ${{{vdb.get('image_env', 'IMAGE')}}}). Build/verify before production."))
    quant = rd.get("vector_quantization", "none")
    qmeta = next((q for q in rag_cat.get("vector_quantization", []) if q.get("id") == quant), {})
    if qmeta.get("verify_integration"):
        issues.append(Issue("info", "rag.quant_external",
                            f"Vector quantization '{quant}' is an external method — verify the "
                            "library/integration; it falls back to no quantization if unavailable."))
    return issues


def _check_supply_chain(cfg: ResolvedConfig) -> list[Issue]:
    """Warn when the engine image uses a mutable tag (supply-chain drift risk)."""
    from installer import supply_chain
    from installer.compose_renderer import _engine_image
    engine = catalog.get_engine(cfg.engine) or {}
    image = _engine_image(engine, cfg.runtime_kind)
    if supply_chain.classify_pin(image) == "mutable":
        sev = "warning"
        if cfg.security_profile_id == "enterprise_zero_trust":
            sev = "fatal"   # zero-trust mandates pinned images
        return [Issue(sev, "supply_chain.mutable_tag",
                      f"Engine image '{image}' uses a mutable tag. Pin to a version/digest "
                      "for reproducibility (run `audit-images`, scan with scripts/scan-images.sh).")]
    return []


def _check_policy(cfg: ResolvedConfig) -> list[Issue]:
    """Validate tenant role/model references against served models + known roles."""
    if not cfg.tenancy_enabled:
        return []
    from installer import policy as policy_mod
    problems = policy_mod.validate_policy(cfg)
    return [Issue("fatal", "policy.tenant", p) for p in problems]


def _check_public_exposure(cfg: ResolvedConfig) -> list[Issue]:
    issues: list[Issue] = []
    sec = cfg.data.get("security", {})
    web = cfg.data.get("web", {})
    profile = sec.get("profile")
    if profile == "public_secure":
        domains = web.get("domains", {}) or {}
        if not domains.get("api"):
            issues.append(Issue("warning", "tls.no_domain",
                                "public_secure selected but no API domain set; TLS/ACME needs a domain."))
    # Docker socket: only a residual risk if we are NOT using the socket proxy.
    sec_prof = catalog.get_security_profile(cfg.security_profile_id) or {}
    if cfg.uses_traefik and not sec_prof.get("docker_socket_proxy", False):
        issues.append(Issue("warning", "docker.socket",
                            "Traefik mounts the Docker socket (read-only). Privilege risk; "
                            "use a security profile with docker_socket_proxy enabled."))
    return issues


def _check_ports(cfg: ResolvedConfig) -> list[Issue]:
    issues: list[Issue] = []
    ports = _host_ports(cfg)
    for port in ports:
        if _port_in_use(port):
            issues.append(Issue("fatal", "port.in_use",
                                f"Host port {port} is already in use; free it or change the mapping."))
    return issues


def _host_ports(cfg: ResolvedConfig) -> list[int]:
    web = cfg.data.get("web", {})
    if cfg.uses_traefik:
        return [80, 443]
    expose = web.get("expose", {}) or {}
    return [int(p) for p in (expose.get("open_webui_port"), expose.get("litellm_port")) if p]


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False
