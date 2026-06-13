# Roadmap & Feature-Tracking

Dieses Projekt wird **stufenweise** gebaut. Jede Stufe ist für sich lauffähig und getestet,
bevor die nächste beginnt. Abgehakte Punkte sind implementiert; offene sind geplant.

Legende: ✅ fertig · 🟡 in Arbeit · ⚪ geplant

---

## Stufe 1 — Funktionierender Kern-Stack + Installer-Grundgerüst 🟡

Ziel: Ein lauffähiger Single-Node-Stack und ein Installer-Skelett, das Hardware erkennt,
ein Profil auflöst und daraus eine valide `docker-compose.yml` + `.env` erzeugt.

- [x] Repo-Struktur & Git-Init
- [x] Dokumentationsfundament (Architektur, Security, Struktur, Decisions, Installer)
- [x] `install.sh` Bootstrap (Python-/Docker-Checks, venv, Deps)
- [x] Hardware-Datenmodell (`SystemProfile`, `GPUProfile`) + Simulationsmodus
- [x] GPU-Detection (nvidia-smi / NVML mit graceful Fallback)
- [x] Kataloge: serving_engines, hardware, webuis, kuratierte Modelle
- [x] Recommendation-Engine (Hardware → Engine/Parallelität/Runtime)
- [x] Profile: `minimal`, `production`
- [x] Compose-Renderer (Jinja2) → `docker-compose.yml` + `.env`
- [x] Kern-Services: Traefik, vLLM, LiteLLM, Open WebUI, Postgres, Redis
- [x] Monitoring: Prometheus, Grafana, DCGM-Exporter, node-exporter, cAdvisor
- [x] Vorschau-Ausgabe vor Installation
- [x] Validatoren (VRAM/RAM/Storage/Ports/Docker-GPU/HF-Token)
- [x] Health-Check-Skripte + Makefile
- [ ] End-to-End-Test auf echtem GPU-Host (durch Nutzer; hier nur Simulation testbar)

## Stufe 2 — Auswahlbasierter Installer 🟡

- [x] Voll interaktiver TUI-Wizard (alle Modi: Auto / Manuell / Profil / Expert / Simulation)
- [x] Live-Hugging-Face-Modellsuche + Kategorie-Filter (graceful Fallback offline)
- [x] Modell-Kompatibilitätsmatrix (Engine × Format × Runtime × Präzision)
- [x] Lizenz-/Gated-Prüfung vor Download
- [x] RAG-Stack (Qdrant/Weaviate/Milvus/pgvector/Chroma + TEI-Embeddings + Reranker, AnythingLLM)
- [x] MCP-Gateway-Layer + Policies (deny-by-default, Audit, Confirmation, Tier-Gating)
- [x] Security-Profile (local_only / private_lan / public_secure / enterprise_zero_trust)
- [x] Docker-Socket-Proxy statt direktem Socket-Mount
- [x] Auth auswählbar: LiteLLM-Keys / Authelia / Authentik / Keycloak
- [x] AMD ROCm: Runtime-Erkennung + ROCm-Engine-Images + GPU-Zugriff (/dev/kfd)
- [x] Neue Profile: rag, agents_mcp, multi_h100, enterprise
- [ ] End-to-End-Test auf echter Hardware (durch Nutzer; hier nur Simulation)
- [ ] Authentik/Keycloak Realm-/Flow-Bootstrap-Automatisierung (aktuell manuell)

## Stufe 3 — Produktionsplattform 🟡

- [x] Multi-Modell-Routing (fast/main/code…) — `routing.yaml`, eine Engine je Modell hinter LiteLLM
- [x] Kubernetes-/Helm-Export aus denselben Profilen (`--target kubernetes`)
- [x] Backup/Restore (Postgres-Dump, Volumes, Configs, .env)
- [x] Update-/Rollback-System (Backup + Image-Snapshot + Health-Gate + Rollback)
- [x] Offline/Air-Gapped-Bundle (`docker save`/`load` + Deployment)
- [x] Plugin-System (engines/webuis/mcp_servers; deny built-in override)
- [x] Benchmark-Modul (tokens/s, TTFT, p50/p95/p99) + Concurrency-Auto-Tuning (`benchmark`)
- [x] Kapazitätsplaner (Nutzer × Prompt-/Antwortlänge → Schätzung) (`plan`)
- [ ] Engine-seitiges Auto-Tuning (max_num_seqs/gpu_mem_util — braucht Engine-Restart)
- [x] Rollen-/Rechtesystem + Mandantenfähigkeit (`roles.yaml`, `multi_tenant.yaml`, Teams/Keys/Budgets)
- [x] Policy-as-Code (zentrale `policy.yaml` + `bootstrap-tenants.sh`)
- [x] Image-/Supply-Chain-Security: Pinning-Audit (`audit-images`) + Scan (Trivy/Grype) + SBOM (Syft)
- [ ] Signaturprüfung (cosign) + Hash-Pinning automatisch
- [ ] MIG-Unterstützung, Multi-Node/Cluster, NCCL-Test
- [x] Admin-Überblick: Grafana-Overview-Dashboard + `status`-CLI
- [x] Eval-/Qualitätsmodul: Golden-Dataset-Runner (`eval`) + Langfuse (optional, enterprise)
- [ ] K8s-Parität für RAG/MCP/Auth/Monitoring (Compose bereits vollständig)
- [ ] Plugin-Erweiterungspunkte: model_sources/vector_dbs/auth_providers/deployment_targets

---

## Offene Fragen an den Nutzer (werden vor Umsetzung geklärt, nicht spekuliert)

Diese Punkte werden erfragt, sobald die jeweilige Stufe sie berührt:

1. **Domains/TLS:** Welche Domain(s) für `api.`, `webui.`, `grafana.`? ACME-E-Mail?
2. **Default-Modelle:** Konkrete HF-Modell-IDs als Standard pro Kategorie?
3. **Auth-Provider:** Authentik, Keycloak, Authelia oder nur LiteLLM-Keys?
4. **Multi-Node:** Realistisch geplant oder vorerst nur Single-Node?
5. **AMD ROCm / CPU-only:** Schon in Stufe 2/3 oder später?
6. **Air-Gapped:** Echte Anforderung oder „nice to have"?

> Diese Liste wird in [`docs/DECISIONS.md`](docs/DECISIONS.md) fortgeschrieben.
