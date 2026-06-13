# Architecture

> Technical reference (English). German overview in [`../README.md`](../README.md).

The Universal AI Stack Builder is a **profile generator**, not a fixed deployment. It turns
*(detected or simulated hardware)* + *(user choices)* + *(catalogs)* into a rendered,
validated deployment (Docker Compose today; Kubernetes/Helm in Stage 3).

## 1. Layered runtime architecture

The deployed stack strictly separates concerns. **Only the reverse proxy is public.**

```
            User / API client / Web UI
                       │
                       ▼
   ┌───────────────────────────────────────────┐
   │  Edge: Reverse Proxy / TLS / Rate Limit     │   Traefik (Caddy/Nginx alt.)
   └───────────────────────────────────────────┘
                       │  (only public entrypoint)
                       ▼
   ┌───────────────────────────────────────────┐
   │  Auth layer (optional in Stage 1)           │   LiteLLM keys → SSO in Stage 2
   └───────────────────────────────────────────┘
                       │
                       ▼
   ┌───────────────────────────────────────────┐
   │  LLM Gateway (OpenAI-compatible)            │   LiteLLM proxy
   └───────────────────────────────────────────┘
              │                       │
              ▼                       ▼
   ┌──────────────────┐    ┌──────────────────────┐
   │ Inference engine │    │  MCP Gateway (Stage 2) │  deny-by-default broker
   │ vLLM / SGLang /  │    │  fs/git/db/browser …   │
   │ TGI / NIM / …    │    └──────────────────────┘
   └──────────────────┘
              │
              ▼
   ┌───────────────────────────────────────────┐
   │  GPU runtime: Docker + NVIDIA Container TK  │
   └───────────────────────────────────────────┘
              │
              ▼
        GPU(s) + interconnect + NVMe model cache
```

### Network segmentation

Three Docker networks:

| Network      | Internal? | Who attaches                                    |
|--------------|-----------|-------------------------------------------------|
| `public`     | no        | Traefik only (ports 80/443)                     |
| `internal`   | yes       | gateway, engines, UIs, DB, redis, MCP           |
| `monitoring` | yes       | prometheus, grafana, exporters                  |

Inference engines, the gateway DB, Redis, and MCP servers are **never** published to the host.
Traefik routes to them by service name over the internal network.

## 2. Default stack (single H100-class node)

| Layer            | Default              | Alternatives                          |
|------------------|----------------------|---------------------------------------|
| GPU runtime      | NVIDIA Container TK  | —                                     |
| Inference engine | **vLLM**             | SGLang, TGI, NIM, Ollama, llama.cpp   |
| API gateway      | **LiteLLM**          | Nginx/Envoy/Kong proxy                |
| Web UI           | **Open WebUI**       | AnythingLLM, LibreChat, Dify, Flowise |
| RAG (Stage 2)    | Qdrant + local embed | Milvus, Weaviate, pgvector, Chroma    |
| MCP (Stage 2)    | MCP gateway          | per-server policies                   |
| Observability    | Prometheus/Grafana/DCGM | + Loki/Promtail (Stage 2)          |
| Deployment       | Docker Compose       | Kubernetes/Helm (Stage 3)             |

**Why vLLM as default:** high-throughput serving via PagedAttention (efficient KV-cache),
continuous batching, OpenAI-compatible API. SGLang is the low-latency / prefix-cache /
agentic alternative.

## 3. Generation pipeline

```
detect / simulate hardware ─┐
profile (minimal/prod/…)  ──┤
catalogs (engines/hw/ui)  ──┼──▶ ResolvedConfig ──▶ validators ──▶ preview ──▶ render
user overrides            ──┘                          │                         │
                                                  (fail fast)          docker-compose.yml + .env
                                                                       configs/litellm/…
                                                                       configs/prometheus/…
```

Stages:

1. **Hardware** — `installer/hardware.py` + `detect_gpus.py` build a `SystemProfile`
   (auto-detected, manually entered, or simulated from the hardware catalog).
2. **Profile** — `profile_builder.py` loads a base profile and merges user overrides into a
   single `ResolvedConfig` dict.
3. **Recommendation** — `recommend.py` maps hardware → engine, dtype, tensor/pipeline
   parallel size, runtime (Compose vs K8s), and surfaces alternatives + warnings.
4. **Validation** — `validators.py` runs pre-flight checks (VRAM/RAM/storage/ports/Docker
   GPU access/HF token). Fatal issues abort before anything is written.
5. **Preview** — `preview.py` prints the full plan (services, ports, volumes, risks).
6. **Render** — `compose_renderer.py` renders Jinja2 templates into `output/`.

## 4. Parallelism strategy (GPU topology aware)

Derived from `nvidia-smi topo -m` (interconnect) and VRAM/GPU count:

| Topology                         | Strategy                                        |
|----------------------------------|-------------------------------------------------|
| 1 GPU                            | `tensor_parallel_size=1`                        |
| 2/4/8 GPU + NVLink/NVSwitch      | `tensor_parallel_size = #GPU`                   |
| Multi-GPU PCIe-only              | prefer data-parallel replicas; avoid large TP   |
| Multi-node                       | pipeline parallel + (Stage 3) disaggregated     |
| VRAM/GPU ≤ 24 GB                 | quantization (AWQ/GPTQ/GGUF), smaller models    |

Blackwell (B200/B300/GB300) additionally unlocks FP8/FP4/NVFP4 precision *if engine and
model support it* — never assumed blindly; real values from NVML are preferred over catalog
defaults.

## 5. Endpoints (target)

```
https://api.<domain>/v1/chat/completions      → LiteLLM → engine
https://api.<domain>/v1/completions
https://api.<domain>/v1/embeddings
https://api.<domain>/v1/models
https://webui.<domain>/                        → Open WebUI
https://grafana.<domain>/                      → Grafana
https://api.<domain>/mcp                        → MCP gateway (Stage 2)
```

## 6. Extensibility (Stage 3)

Everything hardware/engine/UI-specific is **data-driven** (`catalogs/`), and a plugin
system (`plugins/`) will let new engines/UIs/MCP servers/model sources register themselves
with a self-describing manifest. The same `ResolvedConfig` that renders Compose will render
Helm charts — one source of truth, multiple deployment targets.
