# Repository structure

> Technical reference (English).

```
ai-stack/
├── install.sh                  # Bootstrap: checks Python/Docker, creates venv, runs installer
├── Makefile                    # Convenience targets (install, preview, up, down, health, …)
├── requirements.txt            # Installer Python dependencies
├── pyproject.toml              # Package metadata + tooling config
│
├── installer/                  # The Python installer (the "brain")
│   ├── __init__.py
│   ├── __main__.py             # `python -m installer`
│   ├── main.py                 # Typer CLI + wizard entrypoint
│   ├── hardware.py             # SystemProfile / GPUProfile dataclasses + builders
│   ├── detect_gpus.py          # NVML / nvidia-smi detection with graceful fallback
│   ├── catalog.py              # Loads YAML catalogs, typed accessors
│   ├── recommend.py            # Recommendation engine (hardware → engine/parallelism)
│   ├── profile_builder.py      # Load base profile + merge overrides → ResolvedConfig
│   ├── validators.py           # Pre-flight checks (VRAM/RAM/ports/Docker/HF token)
│   ├── preview.py              # Rich preview of the planned deployment
│   └── compose_renderer.py     # Jinja2 render → output/docker-compose.yml + .env + configs
│
├── catalogs/                   # Data-driven catalogs (no hard-coded logic in code)
│   ├── serving_engines.yaml    # vLLM, SGLang, TGI, NIM, Ollama, llama.cpp
│   ├── hardware.yaml           # GPU families (Hopper/Blackwell/Ada/Ampere/AMD)
│   ├── webuis.yaml             # Open WebUI, AnythingLLM, LibreChat, Dify, Flowise
│   └── models.curated.yaml     # Curated starter models by category
│
├── profiles/                   # Pre-baked stack profiles
│   ├── minimal.yaml            # vLLM + LiteLLM + Open WebUI, local only
│   └── production.yaml         # + Traefik TLS, monitoring, rate limits
│   # (Stage 2/3: rag.yaml, agents_mcp.yaml, multi_h100.yaml, enterprise.yaml)
│
├── templates/                  # Jinja2 render templates
│   ├── docker-compose.yml.j2   # Single compose file, services toggled by config
│   ├── env.j2                  # .env with generated secrets
│   ├── litellm.config.yaml.j2  # LiteLLM model_list + router settings
│   ├── prometheus.yml.j2       # Scrape config (DCGM, node, cadvisor, litellm)
│   └── traefik-dynamic.yml.j2  # Secure headers, middlewares
│
├── configs/                    # Static config building blocks (copied as-is)
│   └── grafana/                # Datasource + dashboard provisioning
│
├── scripts/
│   └── healthcheck.sh          # Post-deploy health checks against endpoints
│
├── docs/                       # This documentation set (EN)
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   ├── STRUCTURE.md
│   ├── DECISIONS.md
│   └── INSTALLER.md
│
└── output/                     # Generated deployments (git-ignored, created at render time)
    ├── docker-compose.yml
    ├── .env
    └── configs/…
```

## Module responsibilities

| Module                 | Responsibility                                                       | Pure? |
|------------------------|---------------------------------------------------------------------|-------|
| `hardware.py`          | Define the hardware data model; build it from auto/manual/sim input | yes   |
| `detect_gpus.py`       | Side-effecting probe of the host (NVML, nvidia-smi)                  | no    |
| `catalog.py`           | Load & validate YAML catalogs                                       | yes   |
| `recommend.py`         | Deterministic mapping hardware+goal → recommendation                | yes   |
| `profile_builder.py`   | Merge profile + overrides into `ResolvedConfig`                     | yes   |
| `validators.py`        | Check feasibility, return errors/warnings                           | mixed |
| `preview.py`           | Render the plan to the terminal                                     | no    |
| `compose_renderer.py`  | Render templates to files                                           | no    |
| `main.py`              | Orchestrate the wizard / CLI                                        | no    |

**Design rule:** keep decision logic *pure and data-driven* (`recommend.py`, catalogs) so it
is testable without a GPU and reusable for the future Kubernetes renderer.

## Why data-driven catalogs

Hard-coding "H100 logic" rots within weeks (new GPUs, new engines, new models). Instead:

- **Hardware** lives in `catalogs/hardware.yaml` — adding B300 means adding a YAML entry.
- **Engines/UIs** live in their catalogs with capability flags.
- **Recommendation** reads catalogs + real NVML values; it never hard-codes a single GPU.
