"""Compose renderer.

Renders Jinja2 templates into the output directory:
  output/docker-compose.yml
  output/.env
  output/configs/litellm/config.yaml
  output/configs/prometheus/prometheus.yml   (if monitoring)
  output/configs/traefik/dynamic.yml         (if traefik)

Engine launch commands are built in Python (typed, testable) and passed to the template.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from installer import CONFIGS_DIR, TEMPLATES_DIR, catalog
from installer.profile_builder import ResolvedConfig


def render(cfg: ResolvedConfig, output_dir: Path) -> list[Path]:
    """Render all files. Returns the list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "configs" / "litellm").mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = build_context(cfg)
    written: list[Path] = []

    written.append(_write(output_dir / "docker-compose.yml",
                          env.get_template("docker-compose.yml.j2").render(**ctx)))
    written.append(_write(output_dir / ".env",
                          env.get_template("env.j2").render(**ctx)))
    written.append(_write(output_dir / "configs" / "litellm" / "config.yaml",
                          env.get_template("litellm.config.yaml.j2").render(**ctx)))

    if ctx["monitoring"]:
        (output_dir / "configs" / "prometheus").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "prometheus" / "prometheus.yml",
                              env.get_template("prometheus.yml.j2").render(**ctx)))
        # Copy static Grafana provisioning verbatim.
        src = CONFIGS_DIR / "grafana"
        if src.exists():
            dst = output_dir / "configs" / "grafana"
            shutil.copytree(src, dst, dirs_exist_ok=True)
            written.append(dst)
    if ctx["uses_traefik"]:
        (output_dir / "configs" / "traefik").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "traefik" / "dynamic.yml",
                              env.get_template("traefik-dynamic.yml.j2").render(**ctx)))
    return written


def build_context(cfg: ResolvedConfig) -> dict[str, Any]:
    data = cfg.data
    inf = data["inference"]
    web = data.get("web", {})
    sec = data.get("security", {})
    engine = catalog.get_engine(inf["engine"]) or {}

    domains = web.get("domains", {}) or {}
    expose = web.get("expose", {}) or {}

    return {
        "profile_name": cfg.profile_name,
        "model": cfg.model,
        # engine
        "engine_id": inf["engine"],
        "engine_image": engine.get("image", "vllm/vllm-openai:latest"),
        "engine_port": engine.get("default_port", 8000),
        "engine_gpu_required": engine.get("gpu") == "required",
        "engine_command": build_engine_command(cfg, engine),
        "shm_size": "32gb",
        # gateway
        "rate_limits": bool(data.get("gateway", {}).get("rate_limits", False)),
        # web / proxy
        "uses_traefik": web.get("reverse_proxy") == "traefik",
        "tls": bool(web.get("tls")),
        "domains": {
            "api": domains.get("api"),
            "webui": domains.get("webui"),
            "grafana": domains.get("grafana"),
        },
        "bind": sec.get("bind", "127.0.0.1"),
        "open_webui_port": expose.get("open_webui_port", 3000),
        "litellm_port": expose.get("litellm_port", 4000),
        "ui_open_webui": "open-webui" in (web.get("ui") or []),
        # monitoring
        "monitoring": cfg.monitoring_enabled,
        # security
        "security_profile": sec.get("profile", "local_only"),
        "rate_limit_per_minute": sec.get("rate_limit_per_minute", 60),
        # inference params (also used in litellm template + env)
        "tensor_parallel_size": inf.get("tensor_parallel_size", 1),
        "pipeline_parallel_size": inf.get("pipeline_parallel_size", 1),
        "gpu_memory_utilization": inf.get("gpu_memory_utilization", 0.90),
        "max_model_len": inf.get("max_model_len", 32768),
        "dtype": inf.get("dtype", "bfloat16"),
        # secrets (rendered into .env only)
        "secrets": cfg.secrets,
    }


def build_engine_command(cfg: ResolvedConfig, engine: dict) -> list[str]:
    """Build the container command (list form) for the chosen engine.

    Stage 1 fully supports vLLM (default) with best-effort commands for sglang/tgi.
    """
    inf = cfg.data["inference"]
    eid = inf["engine"]
    port = engine.get("default_port", 8000)
    tp = int(inf.get("tensor_parallel_size", 1) or 1)
    pp = int(inf.get("pipeline_parallel_size", 1) or 1)

    if eid == "vllm":
        cmd = [
            "--model", "${MAIN_MODEL}",
            "--host", "0.0.0.0",
            "--port", str(port),
            "--tensor-parallel-size", "${TENSOR_PARALLEL_SIZE}",
            "--gpu-memory-utilization", "${GPU_MEMORY_UTILIZATION}",
            "--max-model-len", "${MAX_MODEL_LEN}",
            "--dtype", "${DTYPE}",
        ]
        if pp > 1:
            cmd += ["--pipeline-parallel-size", "${PIPELINE_PARALLEL_SIZE}"]
        if inf.get("enable_prefix_caching"):
            cmd += ["--enable-prefix-caching"]
        if inf.get("enable_chunked_prefill"):
            cmd += ["--enable-chunked-prefill"]
        return cmd

    if eid == "sglang":
        return [
            "python3", "-m", "sglang.launch_server",
            "--model-path", "${MAIN_MODEL}",
            "--host", "0.0.0.0",
            "--port", str(port),
            "--tp", "${TENSOR_PARALLEL_SIZE}",
            "--mem-fraction-static", "${GPU_MEMORY_UTILIZATION}",
        ]

    if eid == "tgi":
        return [
            "--model-id", "${MAIN_MODEL}",
            "--port", str(port),
            "--num-shard", "${TENSOR_PARALLEL_SIZE}",
            "--max-total-tokens", "${MAX_MODEL_LEN}",
        ]

    if eid == "ollama":
        return []  # ollama serves by default; model pulled separately

    # Fallback: assume an OpenAI-compatible server reads MAIN_MODEL.
    return ["--model", "${MAIN_MODEL}", "--port", str(port)]


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8", newline="\n")
    return path
