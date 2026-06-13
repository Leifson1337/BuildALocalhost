"""Kubernetes / Helm export (Stage 3).

Renders the SAME ResolvedConfig that drives Compose into Kubernetes manifests and a thin Helm
chart. One source of truth, two deployment targets (ADR-0014).

Stage-3 scope: core serving path (namespace, secret, LiteLLM config, Postgres, Redis,
one Deployment+Service per model, LiteLLM, Open WebUI, Ingress). RAG/MCP/auth/monitoring
K8s parity is a documented follow-up (see ROADMAP); on Compose they are already complete.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from installer import TEMPLATES_DIR
from installer.compose_renderer import build_context
from installer.profile_builder import ResolvedConfig


def render(cfg: ResolvedConfig, output_dir: Path) -> list[Path]:
    out = output_dir / "k8s"
    out.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    ctx = _k8s_context(cfg)
    written: list[Path] = []

    # Plain manifests (kubectl apply -f k8s/manifests.yaml)
    written.append(_write(out / "manifests.yaml",
                          env.get_template("k8s/manifests.yaml.j2").render(**ctx)))

    # NCCL test Job (run before serving to validate GPU interconnect).
    written.append(_write(out / "nccl-test.yaml",
                          env.get_template("k8s/nccl-test.yaml.j2").render(**ctx)))

    # Thin Helm chart wrapping the same values.
    chart = out / "helm" / cfg.profile_name
    (chart / "templates").mkdir(parents=True, exist_ok=True)
    written.append(_write(chart / "Chart.yaml",
                          env.get_template("k8s/Chart.yaml.j2").render(**ctx)))
    written.append(_write(chart / "values.yaml",
                          env.get_template("k8s/values.yaml.j2").render(**ctx)))
    written.append(_write(chart / "templates" / "manifests.yaml",
                          env.get_template("k8s/helm-manifests.yaml.j2").render(**ctx)))
    return written


def _k8s_context(cfg: ResolvedConfig) -> dict[str, Any]:
    ctx = build_context(cfg)
    runtime = ctx["runtime_kind"]

    # K8s exec-form args cannot use shell ${VAR} expansion → inline concrete values.
    subs = {
        "TENSOR_PARALLEL_SIZE": str(ctx["tensor_parallel_size"]),
        "PIPELINE_PARALLEL_SIZE": str(ctx["pipeline_parallel_size"]),
        "GPU_MEMORY_UTILIZATION": str(ctx["gpu_memory_utilization"]),
        "MAX_MODEL_LEN": str(ctx["max_model_len"]),
        "DTYPE": str(ctx["dtype"]),
        "MAX_NUM_SEQS": str(ctx["max_num_seqs"]),
        "MAX_NUM_BATCHED_TOKENS": str(ctx["max_num_batched_tokens"]),
        "KV_CACHE_DTYPE": str(ctx["kv_cache_dtype"]),
    }
    for m in ctx["models"]:
        local = dict(subs)
        local[m["env_var"]] = m["model"]
        m["k8s_args"] = [_subst(arg, local) for arg in m["command"]]

    ctx.update({
        "namespace": f"ai-stack-{cfg.profile_name}",
        "gpu_resource_key": "amd.com/gpu" if runtime == "rocm" else "nvidia.com/gpu",
        # GPUs requested per inference pod = tensor-parallel size.
        "gpu_per_pod": int(ctx["tensor_parallel_size"] or 1),
        "chart_version": "0.1.0",
    })
    return ctx


def _subst(arg: str, mapping: dict[str, str]) -> str:
    out = arg
    for key, val in mapping.items():
        out = out.replace("${" + key + "}", val)
    return out


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8", newline="\n")
    return path
