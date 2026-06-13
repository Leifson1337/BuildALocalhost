"""Profile builder.

Merges a base profile + recommendation + model selection + user overrides into a single
ResolvedConfig (a plain dict, ready for templating and validation). Pure.
"""
from __future__ import annotations

import copy
import secrets
from dataclasses import dataclass, field
from typing import Any

from installer import catalog
from installer.hardware import SystemProfile
from installer.recommend import Recommendation


@dataclass
class ResolvedConfig:
    """The fully-resolved deployment plan. `data` mirrors the profile, with all
    `auto`/`null` values filled in. `system` and `recommendation` are kept for preview."""
    data: dict[str, Any]
    system: SystemProfile
    recommendation: Recommendation
    model: str
    secrets: dict[str, str] = field(default_factory=dict)

    # convenience accessors -------------------------------------------------
    @property
    def profile_name(self) -> str:
        return self.data.get("profile_name", "custom")

    @property
    def engine(self) -> str:
        return self.data["inference"]["engine"]

    @property
    def monitoring_enabled(self) -> bool:
        return bool(self.data.get("monitoring", {}).get("enabled", False))

    @property
    def uses_traefik(self) -> bool:
        return self.data.get("web", {}).get("reverse_proxy") == "traefik"

    @property
    def runtime_kind(self) -> str:
        return self.data.get("runtime", {}).get("kind", self.system.runtime_kind)

    @property
    def security_profile_id(self) -> str:
        return self.data.get("security", {}).get("profile", "local_only")

    @property
    def auth_provider_id(self) -> str:
        return self.data.get("web", {}).get("auth", "none")

    @property
    def rag_enabled(self) -> bool:
        return bool(self.data.get("rag", {}).get("enabled", False))

    @property
    def mcp_enabled(self) -> bool:
        return bool(self.data.get("mcp", {}).get("enabled", False))

    @property
    def tenancy_enabled(self) -> bool:
        return bool(self.data.get("tenancy", {}).get("enabled", False))

    @property
    def policy_enabled(self) -> bool:
        """Emit a policy document for multi-tenant or auth-protected deployments."""
        return self.tenancy_enabled or self.security_profile_id in (
            "public_secure", "enterprise_zero_trust")


def build(
    *,
    profile_name: str,
    system: SystemProfile,
    recommendation: Recommendation,
    model: str | None = None,
    goal: str = "high_throughput_chat",
    optimize_for: str = "balanced",
    overrides: dict[str, Any] | None = None,
) -> ResolvedConfig:
    data = copy.deepcopy(catalog.load_profile(profile_name))

    # 1) resolve the model(s). Supports a single `model` or a `models` routing list.
    resolved_model = model or _default_model(goal)
    _normalize_models(data["inference"], resolved_model)
    resolved_model = data["inference"]["model"]  # primary (first) after normalisation

    # 2) fill engine/parallelism/precision from the recommendation where 'auto'
    inf = data["inference"]
    if inf.get("engine") in (None, "auto"):
        inf["engine"] = recommendation.primary_engine
    if inf.get("pipeline_parallel_size") in (None, "auto"):
        inf["pipeline_parallel_size"] = recommendation.pipeline_parallel_size
    # tensor_parallel_size + gpu_memory_utilization are owned by the auto-tuner (step 2b).
    if inf.get("dtype") in (None, "auto"):
        inf["dtype"] = recommendation.precision[0]
    if inf.get("max_model_len") in (None, "auto"):
        inf["max_model_len"] = _default_max_len(resolved_model)

    # 2b) performance auto-tuning: most efficient serving params + replica strategy
    _apply_tuning(data, system, goal=goal, optimize_for=optimize_for)

    # 3) runtime hint + GPU runtime family (cuda/rocm/cpu)
    data.setdefault("runtime", {}).setdefault("type", recommendation.runtime)
    data["runtime"]["kind"] = system.runtime_kind

    # 4) apply user overrides (dotted-path dict merge)
    if overrides:
        _deep_merge(data, overrides)

    # 5) generate secrets
    secret_values = {
        "POSTGRES_PASSWORD": _token(),
        "LITELLM_MASTER_KEY": "sk-" + _token(),
        "GRAFANA_ADMIN_PASSWORD": _token(),
        "WEBUI_SECRET_KEY": _token(),
        # Auth provider secrets (rendered into .env only when that provider is selected).
        "AUTHELIA_JWT_SECRET": _token(),
        "AUTHELIA_SESSION_SECRET": _token(),
        "AUTHELIA_STORAGE_ENCRYPTION_KEY": _token(32),
        "AUTHENTIK_SECRET_KEY": _token(32),
        "KEYCLOAK_ADMIN_PASSWORD": _token(),
        "LANGFUSE_NEXTAUTH_SECRET": _token(32),
        "LANGFUSE_SALT": _token(),
    }

    return ResolvedConfig(
        data=data,
        system=system,
        recommendation=recommendation,
        model=resolved_model,
        secrets=secret_values,
    )


# --------------------------------------------------------------------------- helpers

def _apply_tuning(data: dict, system, *, goal: str, optimize_for: str) -> None:
    """Fill serving params from the auto-optimizer for maximum efficient throughput.

    Sets vLLM batching/KV params on every model and, for a single-model profile under a
    throughput goal, expands data-parallel replicas to maximise concurrency.
    """
    from installer import tuning
    inf = data.get("inference", {})
    models = inf.get("models", [])
    primary_model = models[0]["model"] if models else inf.get("model", "")
    t = tuning.optimize(system, goal=goal, model_vram_gb=_model_vram(primary_model),
                        optimize_for=optimize_for)

    # Tensor parallelism (only when the profile left it auto).
    if inf.get("tensor_parallel_size") in (None, "auto"):
        inf["tensor_parallel_size"] = t.tensor_parallel_size
    if inf.get("gpu_memory_utilization") in (None, "auto"):
        inf["gpu_memory_utilization"] = t.gpu_memory_utilization

    # Batching / KV params (always applied unless explicitly overridden later).
    inf.setdefault("max_num_seqs", t.max_num_seqs)
    inf.setdefault("max_num_batched_tokens", t.max_num_batched_tokens)
    inf.setdefault("kv_cache_dtype", t.kv_cache_dtype)
    inf["enable_chunked_prefill"] = inf.get("enable_chunked_prefill", t.enable_chunked_prefill)
    inf["enable_prefix_caching"] = inf.get("enable_prefix_caching", t.enable_prefix_caching)

    # Data-parallel replicas: only auto-expand a single-model throughput deployment.
    auto_replica_goals = {"high_throughput_chat", "many_users"}
    if len(models) == 1 and "replicas" not in models[0] and goal in auto_replica_goals:
        models[0]["replicas"] = t.data_parallel_replicas
    inf["_tuning_strategy"] = t.strategy


def _model_vram(model: str) -> float:
    cats = catalog.load_models().get("categories", {})
    for cat in cats.values():
        for sug in cat.get("suggestions", []):
            if sug.get("hf_id") == model:
                return float(sug.get("min_vram_gb", 16))
    return 16.0


def _normalize_models(inf: dict, resolved_model: str) -> None:
    """Normalise inference into a `models` routing list.

    A profile may declare either a single `model` or a `models: [{name, model, role}]` list
    (multi-model routing). After this call `inf['models']` is always a non-empty list and
    `inf['model']` is the primary (first) model id.
    """
    models = inf.get("models")
    if models:
        for m in models:
            if m.get("model") in (None, "auto"):
                m["model"] = resolved_model
            m.setdefault("name", "main-chat")
            m.setdefault("role", "main")
    else:
        models = [{"name": "main-chat", "model": resolved_model, "role": "main"}]
    inf["models"] = models
    inf["model"] = models[0]["model"]


def _default_model(goal: str) -> str:
    defaults = catalog.load_models().get("defaults", {})
    return defaults.get(goal) or defaults.get("high_throughput_chat") or "Qwen/Qwen2.5-7B-Instruct"


def _default_max_len(model: str) -> int:
    """Look up a sensible context length from the curated catalog; fall back to 32768."""
    cats = catalog.load_models().get("categories", {})
    for cat in cats.values():
        for sug in cat.get("suggestions", []):
            if sug.get("hf_id") == model and sug.get("context"):
                return int(sug["context"])
    return 32768


def _token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def _deep_merge(base: dict, override: dict) -> None:
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
