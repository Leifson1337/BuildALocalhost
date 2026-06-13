"""Skills system (Stage 3) — add agent capabilities and MCP-tool skills.

A skill is a directory under `skills/` with a `skill.yaml` manifest (and optional SKILL.md /
resources). Two types:

  * agent — a capability surfaced to the UI/agent layer: name, description, instructions
    (system prompt), and optional `uses` (MCP servers it relies on).
  * mcp   — wraps an MCP tool server (id/package/tier/allowed_tools); merged into the MCP
    gateway as a deny-by-default server.

Profiles/wizard enable skills by name; the builder expands them (agent → skills manifest,
mcp → MCP gateway servers). Pure, fail-safe (bad/disabled skills are skipped with a note).
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from installer import REPO_ROOT

SKILLS_DIR = REPO_ROOT / "skills"
load_notes: list[str] = []


@functools.lru_cache(maxsize=1)
def discover() -> dict[str, Any]:
    """Return {'agent': [...], 'mcp_servers': [...], 'by_name': {name: manifest}}."""
    out: dict[str, Any] = {"agent": [], "mcp_servers": [], "by_name": {}}
    if not SKILLS_DIR.exists():
        return out
    for manifest in sorted(SKILLS_DIR.glob("*/skill.yaml")):
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            load_notes.append(f"Skill {manifest.parent.name}: parse error ({exc}); skipped.")
            continue
        if not data.get("enabled", False):
            continue
        name = data.get("name", manifest.parent.name)
        data["_dir"] = str(manifest.parent)
        out["by_name"][name] = data
        stype = data.get("type", "agent")
        if stype == "mcp":
            server = data.get("server") or {}
            if server.get("id"):
                server = dict(server)
                server.setdefault("tier", "advanced")
                server.setdefault("network", "internal_only")
                server["_skill"] = name
                out["mcp_servers"].append(server)
            else:
                load_notes.append(f"Skill {name}: mcp type without server.id; skipped.")
        else:
            out["agent"].append({
                "name": name,
                "description": data.get("description", ""),
                "instructions": data.get("instructions", ""),
                "uses": data.get("uses", []) or [],
            })
    return out


def available_skill_names() -> list[str]:
    return sorted(discover()["by_name"].keys())


def get_skill(name: str) -> dict[str, Any] | None:
    return discover()["by_name"].get(name)


def mcp_server_specs() -> list[dict[str, Any]]:
    return discover()["mcp_servers"]
