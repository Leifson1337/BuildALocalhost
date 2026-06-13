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


def build(
    *,
    profile_name: str,
    system: SystemProfile,
    recommendation: Recommendation,
    model: str | None = None,
    goal: str = "high_throughput_chat",
    overrides: dict[str, Any] | None = None,
) -> ResolvedConfig:
    data = copy.deepcopy(catalog.load_profile(profile_name))

    # 1) resolve the model
    resolved_model = model or _default_model(goal)
    data["inference"]["model"] = resolved_model

    # 2) fill engine/parallelism/precision from the recommendation where 'auto'
    inf = data["inference"]
    if inf.get("engine") in (None, "auto"):
        inf["engine"] = recommendation.primary_engine
    if inf.get("tensor_parallel_size") in (None, "auto"):
        inf["tensor_parallel_size"] = recommendation.tensor_parallel_size
    if inf.get("pipeline_parallel_size") in (None, "auto"):
        inf["pipeline_parallel_size"] = recommendation.pipeline_parallel_size
    if inf.get("gpu_memory_utilization") in (None, "auto"):
        inf["gpu_memory_utilization"] = recommendation.gpu_memory_utilization
    if inf.get("dtype") in (None, "auto"):
        inf["dtype"] = recommendation.precision[0]
    if inf.get("max_model_len") in (None, "auto"):
        inf["max_model_len"] = _default_max_len(resolved_model)

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
    }

    return ResolvedConfig(
        data=data,
        system=system,
        recommendation=recommendation,
        model=resolved_model,
        secrets=secret_values,
    )


# --------------------------------------------------------------------------- helpers

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
