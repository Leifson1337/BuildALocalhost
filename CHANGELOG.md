# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unreleased]

### Stufe 2 — Auswahl-Wizard, RAG, MCP, Security, AMD

#### Hinzugefügt
- Voll interaktiver Wizard (`installer/wizard.py`) mit Modi Auto/Manuell/Profil/Expert/Simulation;
  Auswahl von Engine, Modell (kuratiert/HF-Suche/Custom/lokal), Web-UIs, Security-Profil, Auth,
  sowie RAG/MCP/Präzision im Expertenmodus
- HF-Live-Modellsuche (`installer/hf_search.py`) mit graceful Fallback (offline → Katalog)
- Neue Kataloge: `auth.yaml`, `security.yaml`, `rag.yaml`, `mcp_servers.yaml`, `compatibility.yaml`
- Erweiterte Modellliste (`models.curated.yaml`): diverse Familien (Qwen, Llama, Mistral,
  Mixtral, DeepSeek, Gemma, Phi, Yi, Command-R, Falcon, StarCoder, Codestral, InternVL, LLaVA,
  BGE/E5/Jina/Nomic/Arctic, GGUF-Builds, …)
- Kompatibilitätsmatrix-Prüfung (Engine × Format × Runtime × Präzision) in `validators.py`;
  GGUF-auf-vLLM = fatal, Präzision nach GPU-Architektur gated
- Lizenz-/Gated-Hinweise vor Download
- RAG-Stack: Vector-DB (Qdrant u.a.) + TEI-Embeddings + Reranker + AnythingLLM
- MCP-Gateway (mcpo) + generierte `policies.yaml` (deny-by-default, Tier-Gating, Audit,
  Confirmation); gefährliche Server unter Public-Profil = fatal
- Security-Profile (local_only/private_lan/public_secure/enterprise_zero_trust) steuern
  Bind/TLS/Exposition/Socket-Proxy
- Docker-Socket-Proxy (tecnativa) ersetzt direkten Socket-Mount (ADR-0009 abgeschlossen)
- Auth auswählbar: LiteLLM-Keys / Authelia (Forward-Auth) / Authentik (server+worker) /
  Keycloak; provider-spezifische Secrets + Configs
- **AMD ROCm** als First-Class-Runtime: `runtime_kind` (cuda/rocm/cpu), ROCm-Engine-Images,
  `/dev/kfd`-GPU-Zugriff, DCGM nur unter CUDA
- Neue Profile: `rag`, `agents_mcp`, `multi_h100`, `enterprise`
- 5 neue Smoke-Tests (gesamt 11/11); alle 6 Profile × {cuda, rocm} bestehen `docker compose config`

#### Geändert
- `compose_renderer` rendert zusätzlich `mcp/policies.yaml` und `authelia/configuration.yml`,
  wählt ROCm-Images und kopiert Grafana-Provisioning
- Vorschau zeigt Runtime, Auth, RAG, MCP

### Stufe 1 — Fundament & Kern-Stack

#### Hinzugefügt
- Git-Repo, Projektstruktur und `.gitignore`
- Dokumentationsfundament: `README.md`, `ROADMAP.md`, `docs/ARCHITECTURE.md`,
  `docs/SECURITY.md`, `docs/STRUCTURE.md`, `docs/DECISIONS.md`, `docs/INSTALLER.md`
- `install.sh` Bootstrap mit Python-/Docker-Checks und venv-Setup
- Python-Installer-Paket `installer/`:
  - `hardware.py` — Datenmodell `SystemProfile`/`GPUProfile`, Auto/Manuell/Simulation
  - `detect_gpus.py` — GPU-Erkennung via NVML/nvidia-smi mit Fallback
  - `catalog.py` — Loader für datengetriebene Kataloge
  - `recommend.py` — Recommendation-Engine (Hardware → Engine/Parallelität/Runtime)
  - `profile_builder.py` — Profil auflösen & mergen
  - `validators.py` — Pre-Flight-Validierung (VRAM/RAM/Storage/Ports/Docker/HF-Token)
  - `compose_renderer.py` — Jinja2-Rendering von `docker-compose.yml` + `.env`
  - `preview.py` — Vorschau-Ausgabe (Rich)
  - `main.py` — Wizard/CLI-Einstieg (Typer)
- Kataloge: `catalogs/serving_engines.yaml`, `hardware.yaml`, `webuis.yaml`,
  `models.curated.yaml`
- Profile: `profiles/minimal.yaml`, `profiles/production.yaml`
- Templates: `templates/docker-compose.yml.j2`, `env.j2`, `litellm.config.yaml.j2`,
  `prometheus.yml.j2`, `traefik-dynamic.yml.j2`
- `Makefile` mit Convenience-Targets
- Health-Check-Skript `scripts/healthcheck.sh`

---

> Frühere/zukünftige Stufen siehe [`ROADMAP.md`](ROADMAP.md).
