# Universal AI Stack Builder

> Ein interaktiver **AI-Infrastructure-Builder**: kein starres Docker-Image, sondern ein
> **Profil-Generator**, der GPU-Hardware erkennt (oder simuliert), den durchsatz­stärksten
> Stack vorschlägt, eine vollständige Vorschau zeigt und daraus **Docker Compose** oder
> **Kubernetes/Helm** erzeugt — selbst optimiert, voll auswählbar, erweiterbar.

Sprache: Wizard & dieser Überblick **Deutsch**, technische Referenz unter [`docs/`](docs/) **Englisch**.

---

## Inhaltsverzeichnis
- [Was es ist](#was-es-ist)
- [Schnellstart](#schnellstart)
- [Wie es funktioniert (Pipeline)](#wie-es-funktioniert-pipeline)
- [Betriebsmodi](#betriebsmodi)
- [Was alles auswählbar ist](#was-alles-auswählbar-ist)
- [Profile](#profile)
- [Performance: maximaler Durchsatz](#performance-maximaler-durchsatz)
- [Effizientes RAG](#effizientes-rag)
- [Endpunkte einfach anbinden](#endpunkte-einfach-anbinden)
- [Skills & Erweiterbarkeit](#skills--erweiterbarkeit)
- [Sicherheit](#sicherheit)
- [Befehle](#befehle)
- [Testen](#testen)
- [Dokumentation](#dokumentation)
- [Status & was noch fehlt](#status--was-noch-fehlt)

---

## Was es ist

Statt „ein Server, ein Modell, eine `docker-compose.yml`" baut dieses Projekt einen
**modularen, auswählbaren AI-Inference-Stack**:

- erkennt GPUs automatisch (H100/H200/B200/B300/GB300, A100, RTX, AMD MI300X …) **oder** lässt
  Hardware manuell eingeben/simulieren
- wählt die **effizienteste Serving-Konfiguration** automatisch (max. parallele Nutzer)
- stellt **OpenAI-kompatible** Endpunkte über ein Gateway (LiteLLM) bereit
- bindet Web-UIs (Open WebUI, AnythingLLM …), RAG, einen abgesicherten **MCP-Gateway**,
  Auth (SSO), Monitoring und Multi-Tenancy an
- zeigt **vor** der Installation eine vollständige Vorschau und validiert Ressourcen +
  Kompatibilität
- exportiert denselben Plan als **Docker Compose** oder **Kubernetes/Helm**

> ⚠️ **Ehrlich zur Sicherheit:** „Vollständig abgesichert" lässt sich bei LLM/MCP nicht
> garantieren (Prompt Injection, Tool-Missbrauch, Datenabfluss). Dieses Projekt baut
> **Defense-in-Depth** — kein Sicherheitsversprechen. Siehe [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Schnellstart

> Ziel-Deployment: **Linux-GPU-Server** mit Docker + NVIDIA Container Toolkit.
> Auf Windows/macOS funktioniert der **Simulations-/Dry-Run-Modus** zum Entwickeln/Vorschauen.

Eine Datei, ein Befehl:

```bash
git clone <repo-url> ai-stack && cd ai-stack
./install.sh            # prüft Python/Docker, legt venv an, startet den Wizard
```

`install.sh` führt durch den Wizard und kann am Ende direkt starten. Manuell:

```bash
python -m installer                                   # interaktiver Wizard
python -m installer --simulate "8xH100" --dry-run     # ohne GPU nur Vorschau
cd output && docker compose up -d && ../scripts/healthcheck.sh .
```

---

## Wie es funktioniert (Pipeline)

```
Hardware (erkannt/simuliert/manuell)
      + Profil (minimal … enterprise)
      + Kataloge (Engines/Modelle/RAG/Auth/…)
      + deine Auswahl
            │
            ▼
   Recommendation  →  Auto-Tuning  →  Validierung  →  Vorschau  →  Rendering
   (Engine/Topo)     (max Durchsatz)  (VRAM/Ports/    (Services/    (compose ODER
                                       Kompatibilität)  Risiken)      k8s + Helm)
```

Alles Hardware-/Engine-/UI-/RAG-Wissen liegt **datengetrieben** in [`catalogs/`](catalogs/) —
neue GPUs/Engines = ein YAML-Eintrag. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Betriebsmodi

| Modus | Zweck |
|-------|-------|
| **Auto** | echte Hardware erkennen (NVML/nvidia-smi) und optimal vorschlagen |
| **Manuell** | GPUs/VRAM/RAM/Interconnect selbst eingeben |
| **Profil** | von einem bekannten Profil starten |
| **Experte** | jede Ebene einzeln wählen (Engine/Modell/RAG/MCP/Auth/Präzision) |
| **Simulation** | `--simulate "8xB300"` — Setup ohne die Hardware als Vorschau |

---

## Was alles auswählbar ist

| Ebene | Optionen |
|-------|----------|
| Serving-Engine | vLLM (default), SGLang, TGI, NVIDIA NIM, Ollama, llama.cpp |
| Modell | 45 kuratierte (Qwen/Llama/Mistral/Mixtral/DeepSeek/Gemma/Phi/Yi/Command-R/Falcon/Coder/Vision/Embeddings/Reranker/GGUF) + **HF-Live-Suche** + beliebige HF-ID / lokaler Pfad |
| Runtime | Docker Compose · Kubernetes/Helm (`--target kubernetes`) · CUDA / **AMD ROCm** / CPU |
| Web-UI | Open WebUI (default), AnythingLLM, LibreChat, Dify, Flowise |
| RAG | Qdrant/Weaviate/Milvus/pgvector/Chroma/**LEANN** + TEI-Embeddings + Reranker + Quantisierung (scalar/product/binary/**TurboQuant/TurboVec**) |
| MCP | abgesicherter Gateway + 11 Server (read-only Defaults bis dangerous, deny-by-default) |
| Auth | LiteLLM-Keys · Authelia · Authentik · Keycloak |
| Security | local_only · private_lan · public_secure · enterprise_zero_trust |
| Monitoring | Prometheus · Grafana · DCGM · node-exporter · cAdvisor · (Langfuse) |
| Endpunkte | beliebige OpenAI-kompatible Upstreams (OpenAI/Azure/Anthropic/Together/Groq/OpenRouter/custom) |
| Skills | Agent-Capability-Skills + MCP-Tool-Skills (`skills/`) |

---

## Profile

| Profil | Inhalt |
|--------|--------|
| `minimal` | vLLM + LiteLLM + Open WebUI, nur lokal |
| `production` | + Traefik TLS, Monitoring, Rate-Limits, Socket-Proxy |
| `routing` | Multi-Modell-Routing (fast/main/code hinter einem Gateway) |
| `rag` | + Qdrant + Embeddings + Reranker + AnythingLLM |
| `rag_efficient` | LEANN + TurboQuant + Reranker + Hybrid-Suche (effizientester RAG) |
| `agents_mcp` | + MCP-Gateway (read-only Defaults) + Skills |
| `multi_h100` | Multi-GPU getunt (auto Tensor/Pipeline-Parallel) |
| `multi_tenant` | Routing + Mandanten (Teams/Keys/Budgets/RAG-Collections) |
| `enterprise` | SSO (Authentik) + RAG + MCP + Langfuse + Zero-Trust |

---

## Performance: maximaler Durchsatz

Der Auto-Optimizer ([`installer/tuning.py`](installer/tuning.py)) wählt **ohne Zutun** die
durchsatzstärkste Konfiguration für deine Hardware:

- kleinste Tensor-Parallel-Größe, die das Modell fasst
- dann **so viele datenparallele Replicas wie GPUs da sind**, je an eine eigene GPU gepinnt;
  LiteLLM verteilt die Last → maximale parallele Nutzer
- **fp8-KV-Cache** (Hopper/Blackwell/Ada), Chunked-Prefill, Prefix-Caching, getunte
  `max_num_seqs`/`max_num_batched_tokens`

Beispiel: **8×H100 + 7B-Modell → 8 unabhängige Replicas auf GPU 0–7**. Steuerung über
`--optimize throughput|latency|balanced`. Gemessenes Feintuning danach via
`benchmark --autotune` (auf echter Hardware).

---

## Effizientes RAG

Profil `rag_efficient`: **LEANN** (speicherarmer Graph-Index) + **TurboQuant/TurboVec**
(Vektor-Kompression) + Hybrid-Suche (dense+BM25) + Reranker + Quellenangaben. LEANN/TurboQuant/
TurboVec sind als **overridable Images/Optionen** integriert (`${LEANN_IMAGE}`, mit
`verify_image`/`verify_integration`-Hinweisen) — reale Images setzt du auf dem GPU-Host.

---

## Endpunkte einfach anbinden

Jeder OpenAI-kompatible Upstream wird über dasselbe `/v1`-Gateway erreichbar:

```yaml
endpoints:
  - {name: gpt4o,  preset: openai,  model: gpt-4o}
  - {name: my-llm, api_base: https://host/v1, model: m, api_key_env: MY_KEY}
```

Presets: `list-endpoints`. Lokale Embeddings werden automatisch mit-exponiert.

---

## Skills & Erweiterbarkeit

- **Skills** (`skills/<name>/skill.yaml`): Typ `agent` (Capability/System-Prompt) oder `mcp`
  (Tool-Server, deny-by-default). Aktivieren via Profil `skills: [...]` oder Wizard. `list-skills`.
- **Plugins** (`plugins/<name>/plugin.yaml`): eigene Engines/Web-UIs/MCP-Server/Vector-DBs/
  Auth-Provider — gemergt in die Kataloge, ohne Core-Änderung.

Beides ist datengetrieben und fail-safe (defektes/deaktiviertes Manifest wird übersprungen).

---

## Sicherheit

Defense-in-Depth (Details: [`docs/SECURITY.md`](docs/SECURITY.md)): nur Reverse-Proxy
öffentlich · interne Netze · TLS/HSTS · Rate-Limits · **MCP deny-by-default** (gefährliche
Tools unter Public = Abbruch) · Docker-Socket-Proxy · Policy/RBAC + Mandantentrennung ·
Secrets nur in `.env` · Supply-Chain (Pin-Audit, Trivy/Grype-Scan, Syft-SBOM, cosign, Digest-
Pinning). **Keine Garantie** gegen Prompt-Injection/Tool-Missbrauch — das ist prinzipiell offen.

---

## Befehle

```bash
# Generieren
python -m installer --simulate "8xH100" --profile production
python -m installer --optimize throughput --profile production    # max. parallele Nutzer
python -m installer --profile rag_efficient                       # LEANN + TurboQuant
python -m installer --target kubernetes --profile enterprise      # K8s-Manifeste + Helm

# Planen / messen / prüfen
python -m installer plan --simulate "4xH100" --users 50           # Kapazität (Heuristik)
python -m installer benchmark --output output --autotune          # TTFT/Latenz/tokens-s
python -m installer eval --dataset configs/eval/example-golden.yaml
python -m installer status --output output                        # Admin-Überblick
python -m installer audit-images --output output                  # Image-Pinning

# Auflisten
python -m installer list-profiles | list-engines | list-endpoints | list-skills
```

Betrieb über `make`: `up`, `down`, `health`, `backup`, `restore`, `update`, `rollback`,
`bundle`, `bootstrap-tenants`, `scan`, `sbom`, `pin`, `verify-sigs`, `nccl-test`.

---

## Testen

- **Offline (ohne GPU):** `make test` → **40/40** Tests; inkl. **48-Kombinationen-Sweep**
  (Engine × Format × Runtime) + alle 9 Profile × {cuda, rocm} via `docker compose config`.
- **Auf echter Hardware:** vollständiger Verifikationsplan (Hardware-Matrix, Kombinationen,
  Performance-/Betriebs-/Security-Abnahme) in [`docs/TESTING.md`](docs/TESTING.md).

---

## Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architektur, Schichten, Datenfluss |
| [`docs/INSTALLER.md`](docs/INSTALLER.md) | Wizard, Modi, alle CLI-Befehle |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Sicherheitskonzept, Threat-Model, MCP-Hardening |
| [`docs/STRUCTURE.md`](docs/STRUCTURE.md) | Repo-Struktur & Modulverantwortung |
| [`docs/TESTING.md`](docs/TESTING.md) | Offline-Suite + On-Hardware-Verifikationsplan |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture Decision Records (20 ADRs) |
| [`docs/GAPS.md`](docs/GAPS.md) | Bekannte Lücken & Limitierungen (ehrlich) |
| [`ROADMAP.md`](ROADMAP.md) · [`CHANGELOG.md`](CHANGELOG.md) | Stufenplan · Änderungshistorie |

---

## Status & was noch fehlt

Stufe 1 ✅ · Stufe 2 ✅ · Stufe 3 ✅ (Parts 1–12). 40/40 Tests, 9 Profile valide.

Offen sind **nur** Punkte, die echte Hardware brauchen (gemessenes Engine-Auto-Tuning,
MIG-Geräte-Binding, Multi-Node-MPI/InfiniBand, fp4 auf Blackwell) oder bewusste additive
Follow-ups (Triton/TensorRT-LLM als wählbare Engines, K8s-Auth-Parität, IdP-Gruppen-RBAC).
Vollständige, ehrliche Liste: [`docs/GAPS.md`](docs/GAPS.md).
