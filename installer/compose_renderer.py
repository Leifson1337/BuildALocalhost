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
    if ctx["rag"]["enabled"]:
        (output_dir / "configs" / "rag").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "rag" / "config.yaml",
                              env.get_template("rag-config.yaml.j2").render(**ctx)))
    if ctx["agent_skills"]:
        (output_dir / "configs" / "skills").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "skills" / "skills.yaml",
                              env.get_template("skills.yaml.j2").render(**ctx)))
    if ctx["mcp"]["enabled"]:
        (output_dir / "configs" / "mcp").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "mcp" / "policies.yaml",
                              env.get_template("mcp-policies.yaml.j2").render(**ctx)))
    if ctx["auth"]["id"] == "authelia":
        (output_dir / "configs" / "authelia").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "authelia" / "configuration.yml",
                              env.get_template("authelia.yml.j2").render(**ctx)))
    if cfg.policy_enabled:
        from installer import policy as policy_mod
        (output_dir / "configs" / "policy").mkdir(parents=True, exist_ok=True)
        written.append(_write(output_dir / "configs" / "policy" / "policy.yaml",
                              env.get_template("policy.yaml.j2").render(
                                  profile_name=cfg.profile_name,
                                  policy=policy_mod.build_policy(cfg))))
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
        "models": _models_context(cfg, engine),
        "deployments": _deployments_context(cfg, engine),
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
        # monitoring + observability
        "monitoring": cfg.monitoring_enabled,
        "observability_langfuse": bool(data.get("observability", {}).get("langfuse", False)),
        "plugin_scrape_targets": _plugin_scrape_targets(),
        # security
        "security_profile": cfg.security_profile_id,
        "rate_limit_per_minute": sec.get("rate_limit_per_minute", 60),
        "docker_socket_proxy": bool(sec_prof.get("docker_socket_proxy", False)),
        # auth / rag / mcp blocks
        "auth": _auth_context(cfg),
        "rag": _rag_context(cfg),
        "mcp": _mcp_context(cfg),
        "endpoints": _endpoints_context(cfg),
        "endpoint_env_vars": _endpoint_env_vars(cfg),
        "agent_skills": cfg.agent_skills,
        # inference params (also used in litellm template + env)
        "tensor_parallel_size": inf.get("tensor_parallel_size", 1),
        "pipeline_parallel_size": inf.get("pipeline_parallel_size", 1),
        "gpu_memory_utilization": inf.get("gpu_memory_utilization", 0.90),
        "max_model_len": inf.get("max_model_len", 32768),
        "dtype": inf.get("dtype", "bfloat16"),
        "max_num_seqs": inf.get("max_num_seqs", 256),
        "max_num_batched_tokens": inf.get("max_num_batched_tokens", 8192),
        "kv_cache_dtype": inf.get("kv_cache_dtype", "auto"),
        "tuning_strategy": inf.get("_tuning_strategy", ""),
        # secrets (rendered into .env only)
        "secrets": cfg.secrets,
    }


def _env_var_for(name: str) -> str:
    """Service name -> .env variable, e.g. 'fast-chat' -> 'MODEL_FAST_CHAT'."""
    return "MODEL_" + name.upper().replace("-", "_").replace(".", "_")


def _models_context(cfg: ResolvedConfig, engine: dict) -> list[dict[str, Any]]:
    """Logical models (one per unique name): env var + id. Used for .env MODEL_* vars."""
    port = engine.get("default_port", 8000)
    out: list[dict[str, Any]] = []
    for m in cfg.data["inference"].get("models", []):
        env_var = _env_var_for(m["name"])
        out.append({
            "name": m["name"],
            "role": m.get("role", "main"),
            "service": "inference-" + m["name"],
            "env_var": env_var,
            "model": m["model"],
            "port": port,
            "replicas": int(m.get("replicas", 1) or 1),
            "command": build_engine_command(cfg, engine, model_env=env_var),
        })
    return out


def _deployments_context(cfg: ResolvedConfig, engine: dict) -> list[dict[str, Any]]:
    """One entry per replica: distinct service name, shared model env var + command.

    Data-parallel replicas of the same model share `name` (LiteLLM load-balances across
    them) but get distinct service names (inference-<name>-N).
    """
    inf = cfg.data["inference"]
    port = engine.get("default_port", 8000)
    tp = int(inf.get("tensor_parallel_size", 1) or 1)
    g_total = cfg.system.total_gpu_count
    out: list[dict[str, Any]] = []
    gpu_cursor = 0
    for m in inf.get("models", []):
        env_var = _env_var_for(m["name"])
        replicas = int(m.get("replicas", 1) or 1)
        command = build_engine_command(cfg, engine, model_env=env_var)
        for i in range(replicas):
            suffix = f"-{i + 1}" if replicas > 1 else ""
            # Pin each replica to its own GPU slice so replicas don't collide.
            device_ids: list[str] = []
            if g_total > 0:
                device_ids = [str((gpu_cursor + k) % g_total) for k in range(tp)]
                gpu_cursor += tp
            out.append({
                "name": m["name"],
                "role": m.get("role", "main"),
                "service": f"inference-{m['name']}{suffix}",
                "env_var": env_var,
                "model": m["model"],
                "port": port,
                "command": command,
                "gpu_device_ids": device_ids,
                "multi_replica": replicas > 1,
            })
    return out


def _plugin_scrape_targets() -> list[dict[str, str]]:
    """Plugin-contributed Prometheus scrape targets: [{name, target}]."""
    try:
        from installer import plugins
        out = []
        for m in plugins.contributed_monitoring():
            if m.get("name") and m.get("target"):
                out.append({"name": m["name"], "target": m["target"]})
        return out
    except Exception:
        return []


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

    # Allow ${ENV:-default} image overrides (e.g. LEANN_IMAGE for an unverified wrapper image).
    vdb_image = vdb["image"]
    if vdb.get("image_env"):
        vdb_image = "${" + vdb["image_env"] + ":-" + vdb["image"] + "}"
    data_path = "/qdrant/storage" if vdb_id == "qdrant" else "/data"

    quant = rd.get("vector_quantization", "none")
    quality = {**rag_cat.get("quality_defaults", {}), **(rd.get("quality", {}) or {})}

    return {
        "enabled": True,
        "vector_db": {"id": vdb["id"], "image": vdb_image,
                      "port": vdb.get("internal_port"), "volume": vdb.get("volume"),
                      "data_path": data_path},
        "vector_quantization": quant,
        "quality": quality,
        "embeddings": {"image": tei_image, "port": tei["internal_port"],
                       "model": rd.get("embeddings_model", rag_cat["embeddings"]["default_model"])},
        "reranker": {"image": rer["image"], "port": rer["internal_port"],
                     "model": rd.get("reranker_model", rag_cat["reranker"]["default_model"])},
        "document_app": rd.get("document_app", "none"),
        "anythingllm_image": rag_cat["document_apps"][0]["image"],
        "anythingllm_port": rag_cat["document_apps"][0]["internal_port"],
    }


def _endpoints_context(cfg: ResolvedConfig) -> list[dict[str, Any]]:
    """Extra OpenAI-compatible upstreams to register on the gateway (+ local embeddings).

    Each entry → an additional LiteLLM model_name so ANY endpoint is reachable via the same
    /v1 base URL. Presets fill api_base/api_key automatically.
    """
    out: list[dict[str, Any]] = []
    for ep in cfg.data.get("endpoints", []) or []:
        preset = catalog.get_endpoint_preset(ep.get("preset", "")) or {}
        provider = ep.get("provider", preset.get("provider", "openai"))
        api_base = ep.get("api_base") or preset.get("api_base") or ""
        key_env = ep.get("api_key_env") or preset.get("api_key_env") or "CUSTOM_API_KEY"
        out.append({
            "name": ep["name"],
            "litellm_model": f"{provider}/{ep['model']}",
            "api_base": api_base,
            "api_key_ref": "os.environ/" + key_env,
            "mode": ep.get("mode", "chat"),
        })
    # Expose the local embedding model through the gateway as well (one base URL for all).
    if cfg.rag_enabled:
        rag = _rag_context(cfg)
        out.append({
            "name": "text-embedding",
            "litellm_model": "openai/" + rag["embeddings"]["model"],
            "api_base": f"http://embeddings:{rag['embeddings']['port']}",
            "api_key_ref": "dummy",
            "mode": "embedding",
        })
    return out


def _endpoint_env_vars(cfg: ResolvedConfig) -> list[str]:
    """Distinct API-key env vars needed by the declared endpoints (rendered into .env)."""
    seen: list[str] = []
    for ep in cfg.data.get("endpoints", []) or []:
        preset = catalog.get_endpoint_preset(ep.get("preset", "")) or {}
        key_env = ep.get("api_key_env") or preset.get("api_key_env")
        if key_env and key_env not in seen:
            seen.append(key_env)
    return seen


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


def build_engine_command(cfg: ResolvedConfig, engine: dict, model_env: str = "MAIN_MODEL") -> list[str]:
    """Build the container command (list form) for the chosen engine.

    `model_env` is the .env variable holding the model id for this service (multi-model
    routing renders one service per model, each with its own MODEL_* var).
    Fully supports vLLM with best-effort commands for sglang/tgi.
    """
    inf = cfg.data["inference"]
    eid = inf["engine"]
    port = engine.get("default_port", 8000)
    pp = int(inf.get("pipeline_parallel_size", 1) or 1)
    ref = "${" + model_env + "}"

    if eid == "vllm":
        cmd = [
            "--model", ref,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--tensor-parallel-size", "${TENSOR_PARALLEL_SIZE}",
            "--gpu-memory-utilization", "${GPU_MEMORY_UTILIZATION}",
            "--max-model-len", "${MAX_MODEL_LEN}",
            "--dtype", "${DTYPE}",
            "--max-num-seqs", "${MAX_NUM_SEQS}",
            "--max-num-batched-tokens", "${MAX_NUM_BATCHED_TOKENS}",
            "--kv-cache-dtype", "${KV_CACHE_DTYPE}",
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
            "--model-path", ref,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--tp", "${TENSOR_PARALLEL_SIZE}",
            "--mem-fraction-static", "${GPU_MEMORY_UTILIZATION}",
        ]

    if eid == "tgi":
        return [
            "--model-id", ref,
            "--port", str(port),
            "--num-shard", "${TENSOR_PARALLEL_SIZE}",
            "--max-total-tokens", "${MAX_MODEL_LEN}",
        ]

    if eid in ("triton_vllm", "triton_tensorrt_llm"):
        # Triton serves from a prepared model repository (mounted at /models/model_repository).
        # The OpenAI-compatible frontend exposes /v1 on the configured port.
        return ["tritonserver", "--model-repository=/models/model_repository",
                f"--http-port={port}"]

    if eid == "ollama":
        return []  # ollama serves by default; model pulled separately

    # Fallback: assume an OpenAI-compatible server reads the model env var.
    return ["--model", ref, "--port", str(port)]


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8", newline="\n")
    return path
