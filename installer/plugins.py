"""Plugin system (Stage 3).

Plugins extend the data-driven catalogs without touching core code. Each plugin is a
directory under `plugins/` containing a `plugin.yaml` manifest that can contribute extra
serving engines, web UIs, or MCP servers. Disabled plugins (`enabled: false`) are ignored.

Manifest schema (see plugins/README.md):

    name: my-custom-engine
    type: inference_engine | webui | mcp_server
    enabled: true
    provides:
      engines: [ { id: ..., name: ..., image: ..., default_port: ..., gpu: required } ]
      webuis:  [ { id: ..., name: ..., image: ..., internal_port: ... } ]
      mcp_servers: [ { id: ..., tier: ..., package: ... } ]

This module is pure (file IO only) and fails safe: a malformed plugin is skipped with a note.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from installer import REPO_ROOT

PLUGINS_DIR = REPO_ROOT / "plugins"

# Collected non-fatal load problems, surfaced by the wizard/preview if desired.
load_notes: list[str] = []


@functools.lru_cache(maxsize=1)
def discover() -> dict[str, list[dict[str, Any]]]:
    """Return contributed catalog entries grouped by kind.

    {'engines': [...], 'webuis': [...], 'mcp_servers': [...]}
    """
    kinds = ("engines", "webuis", "mcp_servers", "vector_dbs", "auth_providers",
             "model_sources", "monitoring", "deployment_targets")
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in kinds}
    if not PLUGINS_DIR.exists():
        return out
    for manifest in sorted(PLUGINS_DIR.glob("*/plugin.yaml")):
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            load_notes.append(f"Plugin {manifest.parent.name}: parse error ({exc}); skipped.")
            continue
        if not data.get("enabled", False):
            continue
        provides = data.get("provides", {}) or {}
        for key in kinds:
            for entry in provides.get(key, []) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    entry["_plugin"] = data.get("name", manifest.parent.name)
                    out[key].append(entry)
                else:
                    load_notes.append(
                        f"Plugin {data.get('name', manifest.parent.name)}: invalid {key} entry; skipped."
                    )
    return out


def contributed_engines() -> list[dict[str, Any]]:
    return discover()["engines"]


def contributed_webuis() -> list[dict[str, Any]]:
    return discover()["webuis"]


def contributed_mcp_servers() -> list[dict[str, Any]]:
    return discover()["mcp_servers"]


def contributed_model_sources() -> list[dict[str, Any]]:
    return discover()["model_sources"]


def contributed_monitoring() -> list[dict[str, Any]]:
    """Extra monitoring targets: [{name, target}] merged into Prometheus scrape config."""
    return discover()["monitoring"]


def contributed_deployment_targets() -> list[dict[str, Any]]:
    return discover()["deployment_targets"]
