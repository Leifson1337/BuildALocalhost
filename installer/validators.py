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
    issues += _check_vram(cfg)
    issues += _check_ram(cfg)
    issues += _check_storage(cfg)
    issues += _check_docker_gpu(cfg)
    issues += _check_hf_token(cfg)
    issues += _check_public_exposure(cfg)
    if check_ports:
        issues += _check_ports(cfg)
    return issues


def has_fatal(issues: list[Issue]) -> bool:
    return any(i.severity == "fatal" for i in issues)


# --------------------------------------------------------------------------- checks

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
    if sec.get("docker_socket_warning"):
        issues.append(Issue("warning", "docker.socket",
                            "Traefik mounts the Docker socket (read-only). This is a privilege risk; "
                            "Stage 2 replaces it with a docker-socket-proxy."))
    # MCP dangerous tools under public profile (Stage 2 wiring; guard now).
    mcp = cfg.data.get("mcp", {})
    if mcp.get("enabled") and profile == "public_secure":
        for srv in mcp.get("servers", []):
            if any(k in str(srv) for k in ("shell-full", "docker-control", "write")):
                issues.append(Issue("fatal", "mcp.dangerous_public",
                                    f"Dangerous MCP server '{srv}' enabled under public profile."))
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
