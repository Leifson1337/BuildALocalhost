# Installer reference

> Technical reference (English). Wizard texts themselves are German.

## Entry points

| Command                              | Purpose                                            |
|--------------------------------------|----------------------------------------------------|
| `./install.sh`                       | Bootstrap (Linux/macOS): checks, venv, run wizard  |
| `python -m installer`                | Run the wizard directly (venv must have deps)      |
| `python -m installer --help`         | Show all CLI options                               |

## CLI options (Stage 1)

```
python -m installer [OPTIONS]

  --profile TEXT        Base profile: minimal | production         [default: production]
  --simulate TEXT       Simulate hardware, e.g. "8xH100", "2xRTX4090", "4xB300"
  --goal TEXT           Optimisation goal (see below)              [default: high_throughput_chat]
  --output PATH         Output directory for generated files        [default: ./output]
  --non-interactive     Skip prompts; use profile + flags only
  --dry-run             Render + preview, but do not start the stack
  --no-validate         Skip pre-flight validation (not recommended)
  -v, --verbose         Verbose logging
```

Goals: `high_throughput_chat`, `low_latency`, `many_users`, `highest_quality`,
`rag`, `agents_mcp`, `development`.

## Modes (all implemented in Stage 2)

| Mode         | How                          | Use case                              |
|--------------|------------------------------|---------------------------------------|
| Auto         | detect real hardware (NVML)  | run on the actual GPU host            |
| Simulation   | `--simulate "8xH100"`        | preview a setup without that hardware |
| Manual       | wizard prompts GPUs/RAM/…    | hardware not auto-detectable          |
| Profile      | `--profile production`       | start from a known-good profile       |
| Expert       | wizard: pick every layer     | engine/model/UI/RAG/MCP/auth/precision|

In interactive mode the wizard first asks the **mode**, then goal, profile, and the stack
selections. Manual mode prompts vendor/model/count/VRAM/interconnect/RAM/storage. Expert mode
additionally exposes RAG, MCP server selection (deny-by-default, dangerous tiers hidden unless
the security profile allows them), and precision.

## Wizard flow

```
1.  Modus wählen (auto / simulate / profile)
2.  Ziel wählen (goal)
3.  Hardware bestätigen (detected or simulated)
4.  Stack-Empfehlung anzeigen (engine, parallelism, runtime, alternatives, warnings)
5.  Details bearbeiten           ← Stage 2 (engine/model/UI/RAG/MCP/security)
6.  Validierung (pre-flight, fail-fast on fatal issues)
7.  Vorschau (services, ports, volumes, risks, expected perf class)
8.  Generieren (docker-compose.yml + .env + configs)
9.  [optional] Modelle laden + Stack starten + Health checks
```

## Hardware simulation strings

`--simulate` accepts `"<count>x<model>"`, case-insensitive, model matched against
`catalogs/hardware.yaml`:

```
1xH100   2xH100   4xH100   8xH100
2xH200   8xB200   8xB300   GB300NVL72
2xRTX4090   1xA100   8xMI300X
```

Unknown models fall back to a `custom` GPU with catalog-default VRAM and a warning.

## Recommendation engine

`recommend.py` is **pure**: `(SystemProfile, goal) → Recommendation`. It returns:

- `primary_engines` / `advanced_engines` (ordered)
- `precision` candidates (bf16 / fp8 / fp4 / quantized)
- `tensor_parallel_size`, `pipeline_parallel_size`, `data_parallel_replicas`
- `runtime` (docker_compose vs kubernetes)
- `alternatives` (variant A throughput / B latency / C NVIDIA-enterprise / D simplicity)
- `warnings` (PCIe bottleneck, low VRAM, public exposure, etc.)

It reads the hardware catalog (architecture, interconnect, VRAM) and **never hard-codes a
single GPU model** — only architecture-class rules.

## Generated output

```
output/
├── docker-compose.yml          # rendered, ready for `docker compose up -d`
├── .env                        # generated secrets + chosen values (git-ignored)
└── configs/
    ├── litellm/config.yaml
    ├── prometheus/prometheus.yml
    └── traefik/dynamic.yml
```

Then:

```bash
cd output
docker compose pull
docker compose up -d
../scripts/healthcheck.sh
```

## Validation (pre-flight)

See `docs/SECURITY.md` → "Pre-flight validation". Fatal issues abort before rendering;
warnings are shown but allow continuing.
