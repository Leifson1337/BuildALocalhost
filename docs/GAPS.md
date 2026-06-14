# Known gaps & limitations (honest status)

What is **not** done, and why. Nothing here is hidden in the code — it is all flagged at
generate/preview time or in `ROADMAP.md`. Split by *why* it isn't done.

## 1. Requires real hardware (cannot be built/verified offline)

These are implemented as far as is meaningful offline; the rest needs a GPU host / cluster:

- **Measured engine-side auto-tuning** — the optimizer (`tuning.py`) is heuristic. A *measured*
  sweep of `max_num_seqs` / `gpu_memory_utilization` etc. requires restarting the engine on real
  GPUs. `benchmark --autotune` does the client-side sweep today.
- **MIG device binding** — MIG is detected and surfaced, but assigning models to specific MIG
  *instance UUIDs* needs a MIG-partitioned GPU.
- **Multi-node NCCL / InfiniBand-RDMA** — K8s manifests + an NCCL test job exist; true multi-node
  collective performance and an MPI-operator path need ≥2 GPU nodes.
- **fp4 / nvfp4 on Blackwell** — selectable and gated by architecture, but per-model support
  must be confirmed on B200/B300 hardware.

## 2. Third-party integrations to verify before production

- **LEANN / TurboQuant / TurboVec** — integrated as overridable images/options with
  `verify_image` / `verify_integration` warnings. You must supply/build the real container
  image or library binding; defaults are placeholders and the stack falls back cleanly.
- **NVIDIA NIM** — needs an NGC API key and per-model images (resolved interactively).
- **Auth IdPs (Authentik/Keycloak)** — services render and start, but realm/flow/group bootstrap
  is manual; UI/IdP-level RBAC (mapping IdP groups → roles) is not yet automated.

## 3. Additive features not yet built (offline-doable, just not requested/finished)

- **Selectable Triton / TensorRT-LLM / Aphrodite / LMDeploy engines** — only
  vLLM/SGLang/TGI/NIM/Ollama/llama.cpp are in the engine catalog today. Adding more is one
  catalog entry + a command builder each.
- **Expert single-toggles for CUDA version / cuDNN / NCCL / Nsight** — intentionally
  container-managed (ADR-0003/0010); not exposed as individual switches.
- **K8s parity for auth providers** — RAG/MCP/monitoring have K8s parity; Authentik/Keycloak on
  K8s (StatefulSets) is still Compose-only.
- **More plugin extension points** — `engines/webuis/mcp_servers/vector_dbs/auth_providers` are
  supported; `model_sources/monitoring/deployment_targets` are planned.
- **Richer bespoke admin UI** — today: Grafana dashboard + `status` CLI (deliberately reusing
  proven tools instead of a custom app).

## 4. Inherent limitations (cannot be "fixed")

- **Security is defense-in-depth, not a guarantee.** Prompt injection, tool misuse, and data
  exfiltration remain unsolved LLM/MCP risks (see `SECURITY.md`).
- **Heuristic estimates** (capacity planner, tuner) are starting points; real numbers come from
  `benchmark` on the target hardware.
- **Exhaustive combination testing** is impossible (combinatorial explosion). Instead, a
  compatibility *matrix* + validators reject bad combos, and a 48-combo sweep + all 9 profiles ×
  {cuda,rocm} are tested (see `TESTING.md`).

## Priorities if you want to close gaps next

1. (offline) Add Triton + TensorRT-LLM as selectable engines.
2. (offline) K8s parity for auth providers + more plugin points.
3. (hardware) Run the full `TESTING.md` §B plan on your GPU host; record measured tuning.
