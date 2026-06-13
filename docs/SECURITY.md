# Security model

> Technical reference (English). This project pursues **defense-in-depth**, not a guarantee.

## Honest disclaimer

"Fully secured" is **not achievable** for LLM/MCP systems. Prompt injection, tool abuse,
and data exfiltration remain real, unsolved risks (cf. OWASP LLM Top 10; MCP threat
taxonomies). The goal here is to *reduce* attack surface through layered controls and to
make risky actions explicit and auditable — never to promise safety.

## Core principles

1. **Only the reverse proxy is public.** No GPU engine, DB, Redis, or MCP server is reachable
   from outside.
2. **Deny-by-default** for MCP tools and dangerous capabilities.
3. **Least privilege** containers (non-root, dropped caps, read-only FS where possible).
4. **Secrets never in logs or prompts.**
5. **Everything risky requires explicit confirmation** (write/delete/shell/external HTTP).

## Defense-in-depth layers

### Network
- private Docker networks (`internal`, `monitoring` flagged `internal: true`)
- public edge network only for the reverse proxy
- no direct model-server / DB / MCP exposure; internal DNS by service name

### Auth (grows by stage)
- **Stage 1:** LiteLLM master key + per-key access; admin bootstrap
- **Stage 2:** SSO (Authentik/Keycloak/Authelia), per-user/per-team keys, budgets, service tokens

### Transport
- TLS at the edge (ACME/Let's Encrypt), HSTS, secure headers
- optional internal mTLS (Stage 3 enterprise)

### Gateway
- rate limits, max context size, max output tokens, request timeout, retry budget
- model allowlists per key/team, abuse detection

### Containers
- non-root users, read-only root FS where supported, dropped Linux capabilities
- **no privileged containers** except documented unavoidable cases
- **no host networking** except documented exceptions
- pinned image versions (Stage 3 enforces hash-pinning + scanning + SBOM)

### Docker socket — known risk
The naive Traefik setup mounts `/var/run/docker.sock:ro`, which is a privilege risk
(socket access ≈ root on host). **Stage 2 replaces this with a Docker-Socket-Proxy** that
exposes only the read-only endpoints Traefik needs, or uses static Traefik file config.
Until then this is flagged in the preview as a warning.

> Hardening targets: rootless Docker, no exposed Docker TCP API, user namespaces,
> never pass `/var/run/docker.sock` into application containers.

### Secrets
- `.env` for local dev only (git-ignored)
- Docker secrets for Compose
- Vault / SOPS / age for production (Stage 3)
- no secrets in logs, no secrets in model prompts

### MCP (Stage 2) — highest-risk surface
MCP introduces its own threat classes: tool-description manipulation, indirect prompt
injection, excessive tool chaining, dynamic-trust problems. Controls:

- per-server **allowlist / denylist** of tools, deny-by-default
- per-user/role scoping (`allowed_users`)
- `internal_only` networking — MCP is **never** internet-facing
- `max_calls_per_request`, `timeout_seconds`
- `require_user_confirmation_for: [external_http, write, delete, shell, email, calendar]`
- full audit logging
- sandboxed filesystem, no unrestricted shell

Example policy (`configs/mcp/policies.yaml`, Stage 2):

```yaml
mcp_policy:
  server_id: filesystem-readonly
  enabled: true
  network: internal_only
  auth_required: true
  allowed_users: [admin, rag-worker]
  allowed_tools: [read_file, list_directory]
  denied_tools: [write_file, delete_file, shell]
  max_calls_per_request: 5
  timeout_seconds: 15
  audit_log: true
  require_user_confirmation_for: [external_http, write, delete, shell, email]
```

### LLM-specific
- system-prompt isolation, retrieval-source labeling, output validation
- structured tool schemas, deny dangerous tool chains
- (Stage 3) PII detection/redaction, prompt-free logging option, data retention rules

## Security profiles (Stage 2)

| Profile                 | Intent                                                        |
|-------------------------|---------------------------------------------------------------|
| `local_only`            | bound to localhost, no TLS, single user — dev only            |
| `private_lan`           | LAN-reachable, basic auth, no public exposure                 |
| `public_secure`         | TLS + auth + rate limits + monitoring (default for internet)  |
| `enterprise_zero_trust` | SSO + RBAC + mTLS + Vault/SOPS + SIEM export + image scanning  |

## Pre-flight validation (Stage 1, implemented)

`installer/validators.py` refuses to render/start when:
- requested model VRAM exceeds available VRAM (fatal) ;
- required ports are occupied (fatal) ;
- Docker GPU access is missing on a GPU profile (fatal) ;
- a gated model is selected without a valid HF token (fatal) ;
- dangerous MCP tools are enabled under a public profile (fatal) ;
- RAM/storage are below recommended thresholds (warning).
