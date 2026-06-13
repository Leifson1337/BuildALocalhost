"""Catalog loader.

Loads the data-driven YAML catalogs and profiles. Pure (no side effects beyond file IO).
All hardware/engine/UI knowledge lives in YAML — never hard-coded here (see ADR-0006).
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from installer import CATALOGS_DIR, PROFILES_DIR


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Catalog/profile file missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at top level of {path}")
    return data


@functools.lru_cache(maxsize=None)
def load_engines() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "serving_engines.yaml")


@functools.lru_cache(maxsize=None)
def load_hardware() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "hardware.yaml")


@functools.lru_cache(maxsize=None)
def load_webuis() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "webuis.yaml")


@functools.lru_cache(maxsize=None)
def load_models() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "models.curated.yaml")


@functools.lru_cache(maxsize=None)
def load_auth() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "auth.yaml")


@functools.lru_cache(maxsize=None)
def load_security() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "security.yaml")


@functools.lru_cache(maxsize=None)
def load_rag() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "rag.yaml")


@functools.lru_cache(maxsize=None)
def load_mcp() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "mcp_servers.yaml")


@functools.lru_cache(maxsize=None)
def load_compatibility() -> dict[str, Any]:
    return _load_yaml(CATALOGS_DIR / "compatibility.yaml")


def load_profile(name: str) -> dict[str, Any]:
    """Load a base profile by name (without .yaml)."""
    return _load_yaml(PROFILES_DIR / f"{name}.yaml")


def available_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def get_engine(engine_id: str) -> dict[str, Any] | None:
    for engine in load_engines().get("engines", []):
        if engine.get("id") == engine_id:
            return engine
    return None


def find_hardware_model(query: str) -> dict[str, Any] | None:
    """Match a model name/alias (case-insensitive) against the hardware catalog.

    Returns a normalised dict with at least: model, vram_gb, class,
    default_interconnect, precision, plus the architecture name and vendor.
    """
    if not query:
        return None
    q = query.lower().replace(" ", "").replace("-", "")
    hw = load_hardware()
    for vendor in ("nvidia", "amd"):
        for arch, models in (hw.get(vendor) or {}).items():
            for entry in models:
                names = [entry["model"]] + list(entry.get("aliases", []))
                # Aliases like `4090` parse as ints in YAML — coerce to str.
                normalised = {str(n).lower().replace(" ", "").replace("-", "") for n in names}
                if q in normalised:
                    out = dict(entry)
                    out["vendor"] = vendor
                    out["architecture"] = arch
                    return out
    return None


def custom_fallback_gpu() -> dict[str, Any]:
    out = dict(load_hardware().get("custom_fallback", {}))
    out.setdefault("vendor", "custom")
    out.setdefault("architecture", "unknown")
    return out


def interconnect_parallelism_hint(interconnect: str) -> str:
    table = load_hardware().get("interconnect_parallelism", {})
    return table.get(interconnect, "data_parallel_replicas")


def get_security_profile(profile_id: str) -> dict[str, Any] | None:
    for prof in load_security().get("profiles", []):
        if prof.get("id") == profile_id:
            return prof
    return None


def get_auth_provider(provider_id: str) -> dict[str, Any] | None:
    for prov in load_auth().get("providers", []):
        if prov.get("id") == provider_id:
            return prov
    return None


def get_mcp_server(server_id: str) -> dict[str, Any] | None:
    for srv in load_mcp().get("servers", []):
        if srv.get("id") == server_id:
            return srv
    return None


def infer_model_kind(model_id: str) -> str:
    """Infer a coarse format/kind from a model id (see compatibility.yaml kind_hints).

    Returns one of: gguf, awq, gptq, fp8, vision, embedding, safetensors_default.
    """
    if not model_id:
        return "safetensors_default"
    mid = model_id.lower()
    hints = load_compatibility().get("kind_hints", {})
    # Order matters: format/quant hints before generic.
    for kind in ("gguf", "awq", "gptq", "fp8", "vision", "embedding"):
        for needle in hints.get(kind, []):
            if needle.lower() in mid:
                return kind
    return "safetensors_default"
