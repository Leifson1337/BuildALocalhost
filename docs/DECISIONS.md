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

## Open decisions (to be asked, not assumed)

Tracked in `ROADMAP.md` → "Offene Fragen". Will be raised when the relevant stage is reached:
domains/TLS email, concrete default model IDs, auth provider, multi-node reality, AMD/CPU
timing, air-gapped requirement.
