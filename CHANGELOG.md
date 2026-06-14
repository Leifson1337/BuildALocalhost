# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unreleased]

### Stufe 3 — Routing, K8s-Export, Betrieb, Plugins, Policy/Multi-Tenancy (in Arbeit)

#### Hinzugefügt (Policy-as-Code + Mandantenfähigkeit)
- `catalogs/roles.yaml` — Rollen→Rechte + Default-Policy
- `installer/policy.py` — baut zentrale Policy aus Rollen + Security-Limits + Mandanten
- `templates/policy.yaml.j2` → `configs/policy/policy.yaml` (für multi-tenant / auth-Profile)
- `profiles/multi_tenant.yaml` — Routing + Mandanten (Teams/Keys/Budgets/RAG-Collections)
- `scripts/bootstrap-tenants.sh` — legt LiteLLM-Teams/Keys/Budgets aus policy.yaml an
- Validator: Mandanten mit unbekannter Rolle / nicht-serviertem Modell = fatal
- Vorschau zeigt Mandanten; Smoke-Tests gesamt 23/23

#### Hinzugefügt (Supply-Chain-Security)
- `installer/supply_chain.py` — Image-Inventar + Pinning-Klassifikation (digest/version/mutable)
- CLI `audit-images` — listet Images + Pinning-Status, warnt bei mutablen Tags
- Validator: mutables Engine-Image = Warnung (fatal unter `enterprise_zero_trust`)
- `scripts/scan-images.sh` (Trivy→Grype) + `scripts/generate-sbom.sh` (Syft/CycloneDX),
  graceful wenn Tool fehlt; Makefile-Targets `audit-images`/`scan`/`sbom`
- Smoke-Tests gesamt 25/25

#### Hinzugefügt (Admin-Dashboard + Eval)
- Grafana-Overview-Dashboard (GPU/LLM/Spend/Container) provisioniert
- CLI `status` — Admin-Überblick (Services, Modelle, Image-Pinning, Mandanten, `docker compose ps`)
- `installer/evaluate.py` + CLI `eval` — Golden-Dataset-Runner (contains/equals/regex/not_contains),
  Pass-Rate + Latenz; Beispiel `configs/eval/example-golden.yaml`
- Langfuse (optional) als Observability-Service; im `enterprise`-Profil aktiviert
- Makefile-Targets `status`/`eval`; Smoke-Tests gesamt 27/27

#### Hinzugefügt (MIG + Multi-Node/NCCL)
- MIG-Erkennung: `mig_capable`/`mig_active` (Katalog + `nvidia-smi`), Hinweise in
  Recommendation + Vorschau; H100/H200 als MIG-fähig markiert
- K8s-Manifeste: `nodeSelector` (`<gpu>.present`) + Tolerations für GPU-Knoten
- NCCL-Test: `scripts/nccl-test.sh` (Single-Node Docker) + K8s-Job
  `output/k8s/nccl-test.yaml`; Makefile-Target `nccl-test`
- Smoke-Tests gesamt 29/29

#### Hinzugefügt (K8s-Parität)
- Kubernetes-Manifeste decken nun auch RAG (vectordb/embeddings/reranker),
  MCP-Gateway und Monitoring (Prometheus/Grafana/DCGM-DaemonSet) ab — Parität zu Compose
  (Auth-Provider auf K8s bleibt Follow-up). Enterprise rendert 30 K8s-Objekte
- Smoke-Tests gesamt 30/30

#### Hinzugefügt (Supply-Chain-Härtung + Plugin-Punkte)
- `supply_chain.pin_compose()` + `scripts/pin-images.sh`: löst Images auf Digests auf →
  `docker-compose.pinned.yml` (crane/buildx/docker manifest, graceful)
- `scripts/verify-signatures.sh`: cosign-Signaturprüfung (keyless OIDC), graceful
- Plugin-Erweiterungspunkte `vector_dbs` + `auth_providers` (Merge in rag/auth-Katalog)
- Makefile-Targets `pin`/`verify-sigs`; Smoke-Tests gesamt 31/31


#### Hinzugefügt
- **Multi-Modell-Routing**: `inference.models: [{name, role, model}]` rendert eine Engine je
  Modell hinter einem LiteLLM-Gateway; Profil `routing.yaml` (fast/main/code). Einzelmodell
  bleibt rückwärtskompatibel (Normalisierung). VRAM-Warnung bei gleichzeitigen Modellen
- **Kubernetes/Helm-Export** (`installer/k8s_renderer.py`, `--target kubernetes`): aus
  derselben ResolvedConfig → `output/k8s/manifests.yaml` (Multi-Doc) + Helm-Chart
  (Chart.yaml/values.yaml/templates). GPU-Resource `nvidia.com/gpu` bzw. `amd.com/gpu`
- Betriebs-Skripte: `backup.sh`, `restore.sh`, `update.sh` (Backup+Snapshot+Health-Gate),
  `rollback.sh`, `offline-bundle.sh` (create/import) + Makefile-Targets
- **Plugin-System** (`installer/plugins.py`, `plugins/`): Manifeste erweitern Engines/Web-UIs/
  MCP-Server ohne Core-Änderung; Beispiel-Plugin (deaktiviert); Schema-Doku
- Kapazitätsplaner (`installer/capacity.py`, CLI `plan`): heuristische Schätzung
  max. paralleler Requests/Durchsatzklasse aus VRAM × Workload
- Benchmark-Modul (`installer/benchmark.py`, CLI `benchmark [--autotune]`): misst TTFT,
  Latenz p50/p95/p99, tokens/s gegen das Gateway; Concurrency-Sweep
- Smoke-Tests gesamt 20/20 (Routing, K8s cuda/rocm, Plugins, Kapazität, Perzentile)

#### Geändert
- `compose_renderer`: pro-Modell-Services + parametrisierte Engine-Commands
- LiteLLM-Config/`.env`: pro-Modell `model_name` bzw. `MODEL_*`-Variablen
- ADR-0014..0016 ergänzt (K8s-Export, Multi-Modell, Plugins)

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

### Stufe 3 (Forts.) — Performance-Auto-Optimizer

- `installer/tuning.py` + `--optimize throughput|latency|balanced`: bestimmt die
  effizienteste Konfiguration (kleinste Tensor-Parallel-Groesse, dann max. datenparallele
  Replicas mit eigener GPU-Zuweisung, fp8-KV-Cache, getunte max_num_seqs/-batched-tokens)
- LiteLLM verteilt Last ueber Replicas (gleicher model_name); Compose nutzt device_ids,
  K8s setzt Deployment-replicas; UTF-8-Stdout abgehaertet
- Smoke-Tests gesamt 34/34

### Stufe 3 (Forts.) — Effizienter RAG (LEANN/TurboQuant/TurboVec)

- `catalogs/rag.yaml`: LEANN (low-storage Graph-Index, overridable ${LEANN_IMAGE}),
  Vektor-Quantisierung scalar/product/binary/turboquant/turbovec, Quality-Defaults
  (Hybrid-Suche, Reranking, Citations, Chunking)
- Profil `rag_efficient.yaml` (LEANN + TurboQuant + Reranker + Hybrid)
- `configs/rag/config.yaml` generiert; Validator-Warnung fuer externe/unverifizierte
  Methoden (verify_image/verify_integration), nicht fatal; faellt sauber zurueck
- Smoke-Tests gesamt 35/35

### Stufe 3 (Forts.) — Einfache Endpunkt-Anbindung

- `catalogs/endpoints.yaml`: Presets (OpenAI/Azure/Anthropic/Together/Groq/OpenRouter/
  remote vLLM/custom) + Standard-Gateway-Endpunkte
- Profil-Feld `endpoints: [...]` + Wizard-Schritt: beliebige OpenAI-kompatible Upstreams
  werden als zusaetzliche model_names ueber dasselbe Gateway erreichbar
- Lokales Embedding-Modell wird automatisch als Gateway-Endpunkt (`text-embedding`) exponiert
- API-Key-Platzhalter landen in der `.env`; CLI `list-endpoints`
- Smoke-Tests gesamt 36/36

### Stufe 3 (Forts.) — Skills-System (Agent + MCP)

- `installer/skills.py` + `skills/`: Skill-Manifeste (`skill.yaml`); Typen `agent`
  (Capability/System-Prompt) und `mcp` (Tool-Server, deny-by-default ueber den Gateway)
- Profil-Feld `skills: [names]` + Wizard-Schritt; Agent-Skills -> `configs/skills/skills.yaml`
  + System-Addendum, MCP-Skills aktivieren den Gateway und landen in den Policies
- MCP-Skills werden in den MCP-Katalog gemergt (dedupe); Beispiel-Skills + README;
  CLI `list-skills`; `agents_mcp` zeigt Skills
- Smoke-Tests gesamt 39/39

### Stufe 3 (Forts.) — Tests, Verifikationsplan & Doku

- Kombinations-Sweep `test_compatibility_matrix_sweep`: 6 Engines x 4 Formate x 2 Runtimes
  (48 Kombinationen) gegen die Kompatibilitaetsmatrix; Smoke-Tests gesamt 40/40
- `docs/TESTING.md`: Offline-Suite (Inventar) + On-Hardware-Verifikationsplan
  (Hardware-Matrix, Kombinationen, Performance-/Betriebs-/Security-Abnahme)
- `docs/GAPS.md`: ehrliche Liste bekannter Luecken/Limitierungen
- README vollstaendig neu: erklaert Architektur, Pipeline, Modi, Auswahl, Profile,
  Performance, RAG, Endpunkte, Skills, Security, Befehle, Tests, Status

### Stufe 3 (Forts.) — Additive Nachruestung

- Triton + TensorRT-LLM als waehlbare Engines (Kompatibilitaetsmatrix + 64-Kombi-Sweep)
- K8s-Auth-Paritaet: Authentik/Keycloak/Authelia auch als Kubernetes-Deployments
- Alle Plugin-Erweiterungspunkte: model_sources/monitoring/deployment_targets ergaenzt
  (Monitoring-Plugins -> Prometheus-Targets; `list-plugins` CLI)
- IdP-Gruppen-RBAC: `group_role_map` (Default + Profil-Override) in policy.yaml +
  Authelia-Regeln; Validator prueft unbekannte Rollen
- ADR-0021; Smoke-Tests gesamt 47/47; alle 9 Profile valide (compose + k8s)
