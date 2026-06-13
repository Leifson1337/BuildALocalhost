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
    if ctx["mcp"]["enabled"]:
        (output_dir / "configs" / "mcp").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "mcp" / "policies.yaml",
                              env.get_template("mcp-policies.yaml.j2").render(**ctx)))
    if ctx["auth"]["id"] == "authelia":
        (output_dir / "configs" / "authelia").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "authelia" / "configuration.yml",
                              env.get_template("authelia.yml.j2").render(**ctx)))
    return written


def build_context(cfg: ResolvedConfig) -> dict[str, Any]:
    data = cfg.data
    inf = data["inference"]
    web = data.get("web", {})
    sec = data.get("security", {})
    engine = catalog.get_engine(inf["engine"]) or {}

    domains = web.get("domains", {}) or {}
    expose = web.get("expose", {}) or {}
    sec_prof = catalog.get_security_profile(cfg.security_profile_id) or {}
    runtime_kind = cfg.runtime_kind

    return {
        "profile_name": cfg.profile_name,
        "model": cfg.model,
        "runtime_kind": runtime_kind,                 # cuda | rocm | cpu
        # engine
        "engine_id": inf["engine"],
        "engine_image": _engine_image(engine, runtime_kind),
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
        "bind": sec.get("bind", sec_prof.get("bind", "127.0.0.1")),
        "open_webui_port": expose.get("open_webui_port", 3000),
        "litellm_port": expose.get("litellm_port", 4000),
        "ui_open_webui": "open-webui" in (web.get("ui") or []),
        # monitoring
        "monitoring": cfg.monitoring_enabled,
        # security
        "security_profile": cfg.security_profile_id,
        "rate_limit_per_minute": sec.get("rate_limit_per_minute", 60),
        "docker_socket_proxy": bool(sec_prof.get("docker_socket_proxy", False)),
        # auth / rag / mcp blocks
        "auth": _auth_context(cfg),
        "rag": _rag_context(cfg),
        "mcp": _mcp_context(cfg),
        # inference params (also used in litellm template + env)
        "tensor_parallel_size": inf.get("tensor_parallel_size", 1),
        "pipeline_parallel_size": inf.get("pipeline_parallel_size", 1),
        "gpu_memory_utilization": inf.get("gpu_memory_utilization", 0.90),
        "max_model_len": inf.get("max_model_len", 32768),
        "dtype": inf.get("dtype", "bfloat16"),
        # secrets (rendered into .env only)
        "secrets": cfg.secrets,
    }


def _engine_image(engine: dict, runtime_kind: str) -> str:
    if runtime_kind == "rocm" and engine.get("image_rocm"):
        return engine["image_rocm"]
    return engine.get("image", "vllm/vllm-openai:latest")


def _auth_context(cfg: ResolvedConfig) -> dict[str, Any]:
    prov = catalog.get_auth_provider(cfg.auth_provider_id) or {"id": "none", "service": False}
    return {
        "id": prov.get("id", "none"),
        "service": bool(prov.get("service", False)),
        "image": prov.get("image"),
        "port": prov.get("internal_port"),
        "forward_auth": bool(prov.get("forward_auth", False)),
        "needs_db": bool(prov.get("needs_db", False)),
        "needs_redis": bool(prov.get("needs_redis", False)),
    }


def _rag_context(cfg: ResolvedConfig) -> dict[str, Any]:
    if not cfg.rag_enabled:
        return {"enabled": False}
    rag_cat = catalog.load_rag()
    rd = cfg.data.get("rag", {})
    vdb_id = rd.get("vector_db", "qdrant")
    vdb = next((v for v in rag_cat["vector_dbs"] if v["id"] == vdb_id), rag_cat["vector_dbs"][0])
    tei = rag_cat["embeddings"]["serving"]
    rer = rag_cat["reranker"]["serving"]
    runtime_kind = cfg.runtime_kind
    tei_image = tei.get("image_cpu") if runtime_kind == "cpu" and tei.get("image_cpu") else tei["image"]
    return {
        "enabled": True,
        "vector_db": {"id": vdb["id"], "image": vdb["image"],
                      "port": vdb.get("internal_port"), "volume": vdb.get("volume")},
        "embeddings": {"image": tei_image, "port": tei["internal_port"],
                       "model": rd.get("embeddings_model", rag_cat["embeddings"]["default_model"])},
        "reranker": {"image": rer["image"], "port": rer["internal_port"],
                     "model": rd.get("reranker_model", rag_cat["reranker"]["default_model"])},
        "document_app": rd.get("document_app", "none"),
        "anythingllm_image": rag_cat["document_apps"][0]["image"],
        "anythingllm_port": rag_cat["document_apps"][0]["internal_port"],
    }


def _mcp_context(cfg: ResolvedConfig) -> dict[str, Any]:
    if not cfg.mcp_enabled:
        return {"enabled": False, "servers": []}
    mcp_cat = catalog.load_mcp()
    gw = mcp_cat["gateway"]
    server_ids = list(cfg.data.get("mcp", {}).get("servers", []) or [])
    details = [catalog.get_mcp_server(sid) for sid in server_ids]
    return {
        "enabled": True,
        "gateway_image": gw["image"],
        "gateway_port": gw["internal_port"],
        "servers": server_ids,
        "server_details": [d for d in details if d],
        "default_policy": mcp_cat.get("default_policy", {}),
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
