# Architecture Decision Records (ADRs)

> Chronological log of significant decisions. Each ADR: context → decision → consequences.
> German notes where helpful for the user.

---

## ADR-0001 — Profile generator, not a fixed image

**Context:** The goal is a *modular, selectable* AI inference stack, not "one Docker image".

**Decision:** Build an **installer that generates** Compose/K8s/bare-metal configs from
data-driven catalogs + user choices, rather than shipping a static `docker-compose.yml`.

**Consequences:** More upfront engineering (renderer, catalogs, validation) but vastly more
flexible and maintainable. The same resolved config can target Compose now and Helm later.

---

## ADR-0002 — Staged, runnable delivery

**Context:** The full vision is a complete product (installer, recommendation engine,
RAG, MCP, monitoring, multi-tenancy, plugins, backup, K8s export). Building it "all at once"
yields half-finished placeholders.

**Decision:** Deliver in **three runnable stages** (see `ROADMAP.md`). Stage N is tested
before Stage N+1 begins.

**Consequences:** User sees working software early; scope is controlled; git history is clean
per stage. *(User-confirmed on 2026-06-13.)*

---

## ADR-0003 — Target platform: Linux GPU servers

**Context:** Dev machine is Windows; real deployment is Linux GPU hosts.

**Decision:** Installer = **Python (cross-platform core) + bash bootstrap**; the stack targets
**Linux + Docker + NVIDIA Container Toolkit**. On Windows/macOS only the simulation/dry-run
paths are expected to work. *(User-confirmed.)*

**Consequences:** GPU detection degrades gracefully off-Linux (simulation mode). bash
`install.sh` is the Linux entrypoint; Python `installer/` is portable for testing.

---

## ADR-0004 — vLLM as default engine

**Context:** Many engines exist; need a sensible default for H100-class throughput.

**Decision:** Default to **vLLM** (PagedAttention, continuous batching, OpenAI-compatible),
with SGLang/TGI/NIM/Ollama/llama.cpp as catalog alternatives.

**Consequences:** Good default for many concurrent users; recommendation engine can still pick
alternatives based on hardware/goal.

---

## ADR-0005 — LiteLLM as the single gateway

**Context:** UIs should not talk to engines directly; we want keys, budgets, routing.

**Decision:** Route **all** traffic through **LiteLLM** (OpenAI-compatible proxy) so UIs, API
clients, and MCP all share one auth/rate-limit/routing surface.

**Consequences:** One choke point for security and observability; engines stay private.

---

## ADR-0006 — Data-driven catalogs over hard-coded hardware

**Context:** Hard-coding "H100 logic" rots quickly.

**Decision:** Hardware/engines/UIs/models live in `catalogs/*.yaml`. Code reads catalogs +
**real NVML values**, never blind constants. New GPUs = new YAML rows.

**Consequences:** Future-proof for B300/GB300/AMD; recommendation stays testable without a GPU.

---

## ADR-0007 — Single Jinja2 compose template (toggled services)

**Context:** The spec sketched many `compose/*.yml` fragments to merge.

**Decision:** Use **one `docker-compose.yml.j2`** whose services are conditionally included
from the resolved config, instead of merging N fragments. Simpler to reason about and to keep
networks/volumes consistent.

**Consequences:** All service definitions are in one reviewable template; conditionals driven
by config flags. (If it grows unwieldy in Stage 2, split into Jinja partials/includes.)

---

## ADR-0008 — Security is defense-in-depth, explicitly not a guarantee

**Context:** User asked for "fully secured".

**Decision:** Document honestly that full security is unattainable for LLM/MCP systems; build
layered controls (network/auth/transport/gateway/containers/secrets/MCP/LLM) and surface
residual risks in the preview.

**Consequences:** No false promises; `docs/SECURITY.md` is the contract.

---

## ADR-0009 — Docker socket exposure deferred-hardened

**Context:** Traefik's Docker provider needs the socket; mounting it raw is a root-equiv risk.

**Decision:** Stage 1 mounts the socket read-only **with a preview warning**; Stage 2 replaces
it with a **Docker-Socket-Proxy** (or static file provider).

**Consequences:** Functional now, hardened soon; risk is visible, not hidden.

---

## ADR-0010 — Auth provider is user-selectable, not fixed

**Context:** User asked for "all auth providers, selectable".

**Decision:** `catalogs/auth.yaml` lists `none`, `litellm_keys`, `authelia`, `authentik`,
`keycloak`. The wizard offers all (with per-security-profile recommendations); the renderer
emits the chosen provider's services. Authelia integrates via Traefik forward-auth;
Authentik runs server+worker on shared Postgres/Redis; Keycloak uses shared Postgres.

**Consequences:** Flexible. Authentik/Keycloak realm/flow bootstrap is still manual (flagged
in ROADMAP); secrets are auto-generated into `.env` per provider.

---

## ADR-0011 — Compatibility by inferred model "kind", not per-model rows

**Context:** A per-model compatibility table rots; thousands of models exist.

**Decision:** `catalogs/compatibility.yaml` declares engine support per *format kind*
(gguf/awq/gptq/fp8/vision/embedding/safetensors_default) and infers a model's kind from its
id via substring hints. Validators reject impossible combos (e.g. GGUF on vLLM = fatal) and
gate precision by GPU architecture.

**Consequences:** Robust to new models; occasional false "unverified" warnings are acceptable
and non-fatal.

---

## ADR-0012 — AMD ROCm as a first-class runtime

**Context:** User wants AMD ROCm included in Stage 2.

**Decision:** `SystemProfile.runtime_kind` ∈ {cuda, rocm, cpu} from GPU vendor. The renderer
selects `image_rocm` when present and emits ROCm GPU access (`/dev/kfd`, `/dev/dri`,
`group_add: video`) instead of the NVIDIA device reservation. DCGM exporter (NVIDIA-only) is
omitted on ROCm.

**Consequences:** vLLM/SGLang/TGI ROCm images supported; AMD GPU metrics need a different
exporter (deferred). NIM stays CUDA-only.

---

## ADR-0013 — Single compose template scales via conditionals (revisit threshold)

**Context:** Stage 2 added many optional services (RAG, MCP, 3 auth providers, socket proxy).

**Decision:** Keep the single `docker-compose.yml.j2` with conditional blocks for now; it
still renders and validates (`docker compose config`) across all 6 profiles × {cuda, rocm}.

**Consequences:** If the template keeps growing in Stage 3 (K8s export, multi-node), split
into Jinja includes/partials. Tracked as a refactor trigger, not done preemptively.

---

## ADR-0014 — Kubernetes/Helm export from the same ResolvedConfig

**Context:** Compose suits single-node; multi-node/production wants Kubernetes. We don't want
a second source of truth.

**Decision:** `installer/k8s_renderer.py` consumes the **same `ResolvedConfig`** (via
`compose_renderer.build_context`) and renders (a) plain multi-doc `manifests.yaml` and (b) a
thin Helm chart. Per-model Deployments+Services mirror the Compose multi-model routing; GPU
requests use `nvidia.com/gpu` or `amd.com/gpu` by runtime. Exec-form args inline concrete
values (no shell `${VAR}` expansion in K8s). Helm templates are wrapped in Jinja `{% raw %}`
so they stay valid Go templates.

**Consequences:** One config → two targets. Stage-3 K8s scope is the core serving path;
RAG/MCP/auth/monitoring K8s parity is a documented follow-up (already complete on Compose).
Validated offline by multi-doc YAML parse (no cluster available in dev).

---

## ADR-0015 — Multi-model routing as a first-class profile shape

**Context:** Production wants fast/main/code models behind one endpoint.

**Decision:** `inference.models: [{name, role, model}]` renders one engine service per model;
LiteLLM exposes each as a distinct `model_name`. A single `model` is normalised to a
one-entry list, so all earlier profiles/tests keep working. Validators warn that concurrent
models share VRAM (fatal if the summed floors exceed available VRAM).

**Consequences:** Backward compatible; `routing.yaml` profile demonstrates it.

---

## ADR-0016 — Plugins extend catalogs, never core code

**Context:** "Beliebig erweiterbar" — arbitrary extensibility.

**Decision:** `plugins/<name>/plugin.yaml` manifests contribute extra engines/webuis/mcp
servers, merged (deduped by id, built-ins win) by `installer/plugins.py`. Malformed/disabled
plugins are skipped with a note, never a crash.

**Consequences:** New engines/UIs/MCP servers need no code change. More extension kinds
(model_sources, vector_dbs, auth_providers, …) are planned.

---

## ADR-0017 — Policy-as-Code as a generated artifact; LiteLLM enforces it

**Context:** Multi-tenant production needs roles, per-team model rights, budgets, rate limits,
and a single auditable authorization source.

**Decision:** `catalogs/roles.yaml` defines roles→rights and a default policy. `installer/policy.py`
combines roles + the security profile's limits + profile-declared `tenancy.tenants` into one
`configs/policy/policy.yaml` (rendered for multi-tenant or auth-protected deployments).
`scripts/bootstrap-tenants.sh` turns it into LiteLLM teams/virtual-keys/budgets via the API —
LiteLLM is the runtime enforcement point (ADR-0005). Validators reject tenants that reference
unknown roles or unserved models.

**Consequences:** Policy is reviewable, diffable, regenerable. Tenant identities are examples in
profiles; real tenants are added via overrides/wizard. RBAC at the UI/IdP layer (Authentik
groups) is a follow-up; gateway-level enforcement is covered now.

---

## ADR-0018 — Supply-chain: inventory in code, scanning via external tools

**Context:** Mutable image tags (`:latest`, `:main`) cause silent drift; production wants
vulnerability scanning + SBOMs.

**Decision:** `installer/supply_chain.py` is the pure inventory/classification layer (digest /
version / mutable) over a rendered compose file; `audit-images` reports it and a validator
warns on mutable engine tags (fatal under `enterprise_zero_trust`). Scanning and SBOMs are
delegated to best-in-class external tools via scripts: `scan-images.sh` (Trivy→Grype fallback)
and `generate-sbom.sh` (Syft, CycloneDX), which degrade gracefully when the tool is absent.

**Consequences:** No reinvented scanner; honest about requiring Trivy/Grype/Syft. cosign
signature verification + automatic digest-pinning are tracked follow-ups.

---

## Open decisions (to be asked, not assumed)

Tracked in `ROADMAP.md` → "Offene Fragen". Will be raised when the relevant stage is reached:
domains/TLS email, concrete default model IDs, auth provider, multi-node reality, AMD/CPU
timing, air-gapped requirement.
