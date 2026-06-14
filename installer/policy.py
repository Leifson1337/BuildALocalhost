"""Policy-as-Code + multi-tenancy builder (Stage 3).

Combines the roles catalog, the security profile's limits, and tenants declared in the
profile into a single policy document. The document is rendered to
`configs/policy/policy.yaml` and consumed by `scripts/bootstrap-tenants.sh` to create
LiteLLM teams/keys/budgets. Pure.
"""
from __future__ import annotations

from typing import Any

from installer import catalog
from installer.profile_builder import ResolvedConfig


def build_policy(cfg: ResolvedConfig) -> dict[str, Any]:
    roles_cat = catalog.load_roles()
    default = dict(roles_cat.get("default_policy", {}))
    sec = cfg.data.get("security", {})

    # Security profile limits override role defaults.
    if sec.get("max_context_tokens"):
        default["max_context_tokens"] = sec["max_context_tokens"]
    if sec.get("max_output_tokens"):
        default["max_output_tokens"] = sec["max_output_tokens"]
    if sec.get("rate_limit_per_minute"):
        default["rate_limit_per_minute"] = sec["rate_limit_per_minute"]

    served = [m["name"] for m in cfg.data.get("inference", {}).get("models", [])]

    tenants_in = cfg.data.get("tenancy", {}).get("tenants", []) or []
    tenants_out = [_expand_tenant(t, served, default) for t in tenants_in]

    # RBAC: IdP group -> role map (catalog default + profile override).
    group_role_map = dict(roles_cat.get("group_role_map", {}))
    group_role_map.update(cfg.data.get("rbac", {}).get("group_role_map", {}) or {})

    return {
        "default": default,
        "roles": roles_cat.get("roles", []),
        "served_models": served,
        "tenants": tenants_out,
        "multi_tenant": bool(cfg.data.get("tenancy", {}).get("enabled", False)),
        "group_role_map": group_role_map,
    }


def _expand_tenant(tenant: dict, served: list[str], default: dict) -> dict[str, Any]:
    """Resolve a tenant's effective allowed models from explicit list + role rights."""
    roles_cat = catalog.load_roles()
    model_rights = roles_cat.get("model_rights", {})

    allow: set[str] = set(tenant.get("models", []) or [])
    for role_id in tenant.get("roles", []) or []:
        role = catalog.get_role(role_id) or {}
        for right in role.get("rights", []):
            for m in model_rights.get(right, []):
                allow.add(m)
    # "*" means all served models.
    if "*" in allow:
        effective = list(served)
    else:
        effective = [m for m in allow if m in served] or list(served[:1])

    return {
        "id": tenant["id"],
        "roles": tenant.get("roles", []),
        "allow_models": effective,
        "budget_usd": tenant.get("budget_usd"),
        "rate_limit_per_minute": tenant.get("rate_limit_per_minute",
                                            default.get("rate_limit_per_minute")),
        "max_context_tokens": tenant.get("max_context_tokens",
                                         default.get("max_context_tokens")),
        "rag_collection": tenant.get("rag_collection"),
        "allow_mcp": tenant.get("allow_mcp", False),
    }


def validate_policy(cfg: ResolvedConfig) -> list[str]:
    """Return human-readable problems (used by validators)."""
    problems: list[str] = []
    pol = build_policy(cfg)
    served = set(pol["served_models"])
    valid_roles = {r["id"] for r in pol["roles"]}
    for t in pol["tenants"]:
        for r in t["roles"]:
            if r not in valid_roles:
                problems.append(f"Tenant '{t['id']}' references unknown role '{r}'.")
        for m in t["allow_models"]:
            if m not in served and m != "*":
                problems.append(f"Tenant '{t['id']}' allows model '{m}' which is not served.")
    for group, role in (pol.get("group_role_map") or {}).items():
        if role not in valid_roles:
            problems.append(f"RBAC group '{group}' maps to unknown role '{role}'.")
    return problems
