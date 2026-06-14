# Testing & verification plan

Two layers: **(A)** what is verified *offline* today (no GPU), and **(B)** what *must* be
verified *on real hardware* before production, with concrete combinations, commands, and
acceptance criteria.

> Run the offline suite any time: `python tests/test_smoke.py` (or `make test`).
> Current status: **40/40 passing**, all 9 profiles render valid `docker compose config`.

---

## A. Offline test suite (no GPU) — what it already covers

| Area | Tests | What is guaranteed |
|------|-------|--------------------|
| Hardware model / simulation | `test_simulation_parses_count_and_model` | parse `NxModel`, VRAM/topology from catalog |
| Recommendation | `test_recommend_h100_uses_tensor_parallel`, `test_recommend_consumer_low_vram_warns` | engine/parallelism/warnings per GPU class |
| Rendering (compose) | `test_production_render_writes_files`, `test_minimal_render_no_traefik_no_monitoring` | valid YAML, correct services per profile |
| All profiles × runtimes | `test_all_profiles_render_cuda_and_rocm` | 9 profiles × {cuda, rocm} render |
| **Compatibility matrix sweep** | `test_compatibility_matrix_sweep` | **6 engines × 4 formats × 2 runtimes = 48 combos** match the matrix; valid combos render |
| Format guards | `test_gguf_on_vllm_is_fatal` | GGUF-on-vLLM = fatal |
| AMD ROCm | `test_amd_runtime_and_image`, `test_k8s_rocm_resource_key` | ROCm image + `/dev/kfd`, `amd.com/gpu` |
| VRAM feasibility | `test_vram_insufficient_is_fatal` | model > VRAM = fatal |
| Throughput optimizer | `test_tuning_maximizes_replicas`, `test_tuning_big_model_tensor_parallel`, `test_replicas_get_distinct_gpu_ids` | replica strategy + distinct GPU pinning |
| Multi-model routing | `test_routing_multi_model`, `test_single_model_backward_compatible` | per-model services + LiteLLM entries |
| Security | `test_dangerous_mcp_fatal_on_public`, `test_socket_proxy_replaces_raw_socket` | deny-by-default MCP, socket proxy |
| Policy / multi-tenancy | `test_multi_tenant_policy_render`, `test_policy_rejects_unknown_role`, `test_policy_emitted_for_public_secure_without_tenancy` | tenant/role expansion + validation |
| Supply chain | `test_supply_chain_classify_pin`, `test_supply_chain_pin_compose`, `test_supply_chain_audit_on_rendered` | pin classification + digest pinning |
| Capacity / benchmark / eval | `test_capacity_*`, `test_benchmark_percentiles_pure`, `test_eval_scoring_pure` | pure math correctness |
| Kubernetes | `test_k8s_export_multidoc_valid`, `test_k8s_parity_enterprise`, `test_k8s_node_selector_and_nccl` | manifests, RAG/MCP/monitoring parity, nodeSelector/NCCL |
| MIG | `test_mig_capability_detected_h100` | MIG detection + warnings |
| Plugins / skills | `test_plugin_loader_*`, `test_skills_loader_*`, `test_agent_skills_rendered_in_profile`, `test_mcp_skill_enables_gateway_and_policy` | extension discovery + wiring |
| Endpoints | `test_custom_endpoints_into_litellm` | arbitrary upstreams into the gateway |
| Observability | `test_langfuse_rendered_in_enterprise` | Langfuse wiring |

**What offline tests do NOT prove:** actual model loading, real throughput/latency, GPU memory
fit under load, MIG device binding, multi-node NCCL bandwidth, real vulnerability/signature
status, or third-party image availability (LEANN/TurboQuant/TurboVec). Those need hardware → §B.

---

## B. On-hardware verification plan

### B.1 Hardware matrix (test at least one GPU per class you intend to support)

| Class | Example GPU | VRAM/GPU | Priority combos to verify |
|-------|-------------|----------|---------------------------|
| consumer | RTX 4090 / 3090 | 24 GB | quantized (AWQ/GPTQ/GGUF) small models; ollama + llama.cpp |
| datacenter_mid | A100 80GB / A40 | 40–80 GB | vLLM bf16; MIG on/off (A100); TGI |
| datacenter_high (Hopper) | H100 / H200 | 80–141 GB | vLLM **fp8 KV**; multi-replica throughput; SGLang low-latency |
| datacenter_high (Blackwell) | B200 / B300 / GB300 | 180–288 GB | fp8 **and fp4/nvfp4** (verify engine+model support); large models |
| accelerator (AMD) | MI300X / MI325X | 192–256 GB | **ROCm** images (vLLM/SGLang/TGI); no DCGM |
| cpu_only | — | — | llama.cpp GGUF only (smoke) |
| multi-node | ≥2 nodes, IB/RDMA | — | Kubernetes + NCCL job + pipeline/data parallel |

For each GPU you actually have: confirm `nvidia-smi` (or `rocm-smi`), driver version, and
`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.

### B.2 Combination test plan

Run the generator, deploy, and check each combination below. Use `--simulate` first to preview,
then real auto-detect to deploy.

1. **Engine × GPU class** (serving works, model loads, OpenAI API answers):
   - vLLM on every datacenter GPU (default).
   - SGLang on Hopper/Blackwell/AMD (latency, prefix cache).
   - TGI on Hopper/AMD.
   - NIM on NVIDIA only (needs NGC key + per-model image).
   - Ollama + llama.cpp on consumer/CPU (GGUF).
2. **Precision × architecture**: bf16 everywhere; **fp8** on Hopper/Ada/Blackwell;
   **fp4/nvfp4** on Blackwell — verify the *specific model* supports it (no silent fallback).
3. **Parallelism / concurrency**:
   - 1 GPU → 1 replica; N GPUs + small model → N replicas (confirm distinct GPU pinning,
     LiteLLM load-balances, throughput scales ~linearly).
   - Large model → tensor-parallel across GPUs (NVLink/NVSwitch present).
   - PCIe-only multi-GPU → confirm data-parallel replicas (not large TP).
4. **MIG (A100/H100)**: enable MIG, regenerate, confirm small models bind to slices and the
   recommendation/preview reflect MIG; disable MIG for large models.
5. **Multi-node (Kubernetes)**: `kubectl apply -f output/k8s/manifests.yaml`; run
   `output/k8s/nccl-test.yaml`; verify GPU nodeSelector scheduling and cross-node throughput.
6. **RAG**: ingest documents; verify hybrid retrieval + reranking + citations; for
   `rag_efficient` verify the **LEANN image you provide** and TurboQuant/TurboVec integration.
7. **MCP**: confirm deny-by-default, that disabled tools are blocked, and that write/shell
   actions require confirmation; confirm MCP is unreachable from outside.
8. **Auth**: for each chosen provider (litellm_keys/Authelia/Authentik/Keycloak) verify login,
   token issuance, and that unauthenticated access is refused.
9. **Multi-tenant**: `make bootstrap-tenants`; verify per-team keys, budgets, model allowlists,
   and isolation between tenants.
10. **Endpoints**: register an external upstream; confirm it answers via the same `/v1` base URL.
11. **Skills**: enable an agent skill (system prompt applied) and an MCP skill (tool available,
    policy enforced).

### B.3 Performance acceptance (per deployment)

```bash
cd output && docker compose up -d
../scripts/healthcheck.sh .
python -m installer benchmark --output . --autotune
```

| Metric | How | Target (tune to your SLA) |
|--------|-----|---------------------------|
| Health | `healthcheck.sh` | `/v1/models` + chat smoke pass |
| Throughput | `benchmark --autotune` | tokens/sec scales with replicas; pick best concurrency |
| TTFT | `benchmark` p95 | within your latency SLA |
| Latency | `benchmark` p50/p95/p99 | within SLA under target concurrency |
| GPU use | Grafana / DCGM | high utilisation, no OOM, KV cache not thrashing |
| Capacity | `plan` vs measured | measured concurrent users ≥ planned |

### B.4 Operations acceptance

| Area | Command | Pass criteria |
|------|---------|---------------|
| Backup/restore | `make backup` then `make restore BACKUP=…` | DB + volumes + keys restored, stack healthy |
| Update/rollback | `make update`; on failure `make rollback` | health-gated update; rollback restores prior images |
| Offline bundle | `make bundle` → import on air-gapped host | images + deployment load and start |
| Supply chain | `make audit-images`, `make scan`, `make sbom`, `make verify-sigs` | no mutable tags in prod; no critical CVEs; SBOMs produced |
| Digest pinning | `make pin` | `docker-compose.pinned.yml` deploys identically |
| TLS | browse the `https://` domains | valid certs (ACME), HSTS, no plaintext |

### B.5 Security verification (defense-in-depth — see SECURITY.md)

- Port-scan the host: only 80/443 reachable; engines/DB/Redis/MCP not exposed.
- Attempt MCP tool abuse / prompt injection against retrieval — confirm guardrails + audit logs.
- Confirm secrets are not in logs and not in prompts.
- (enterprise) verify internal mTLS, image scanning gate, SIEM export.

> Reminder: prompt injection, tool misuse, and data exfiltration are **not fully solvable**.
> These checks reduce risk; they do not eliminate it.

---

## C. Quick offline self-check before any hardware run

```bash
make test                                   # 40/40 offline tests
python -m installer --simulate "8xH100" --profile production --dry-run --non-interactive
python -m installer --simulate "8xMI300X" --profile rag_efficient --dry-run --non-interactive
for p in minimal production rag rag_efficient routing agents_mcp multi_tenant multi_h100 enterprise; do
  python -m installer --profile $p --simulate "8xH100" --non-interactive --output /tmp/$p
  (cd /tmp/$p && docker compose config --quiet && echo "OK $p")
done
```
