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

## Stufe 2 — Auswahlbasierter Installer ⚪

- [ ] Voll interaktiver TUI-Wizard (alle Modi: Auto / Manuell / Profil / Expert / Simulation)
- [ ] Live-Hugging-Face-Modellsuche + Kategorie-Filter
- [ ] Modell-Kompatibilitätsmatrix (Engine × Modell × Quantisierung × VRAM)
- [ ] Lizenz-/Gated-Prüfung vor Download
- [ ] RAG-Stack (Qdrant + Embeddings + Reranker, AnythingLLM)
- [ ] MCP-Gateway-Layer + Policies (deny-by-default, Audit, Confirmation)
- [ ] Security-Profile (local_only / private_lan / public_secure / enterprise_zero_trust)
- [ ] Docker-Socket-Proxy statt direktem Socket-Mount
- [ ] SSO/Auth (Authentik/Keycloak) optional

## Stufe 3 — Produktionsplattform ⚪

- [ ] Multi-Modell-Routing (fast/main/code/reasoning/vision/embeddings)
- [ ] Benchmark- & Auto-Tuning-Modul (tokens/s, TTFT, p50/p95/p99)
- [ ] Kapazitätsplaner (Nutzer × Prompt-/Antwortlänge → Schätzung)
- [ ] Rollen-/Rechtesystem + Mandantenfähigkeit
- [ ] Policy-as-Code (zentrale Policy-Datei)
- [ ] Backup/Restore (DBs, Vector-DB, Keys, Configs, Dashboards)
- [ ] Update-/Rollback-System (Versionspins, Canary, Rollback)
- [ ] Offline/Air-Gapped-Bundle (Images + Modelle vorab)
- [ ] Image-/Supply-Chain-Security (Scanning, SBOM, Signaturen)
- [ ] Kubernetes-/Helm-Export aus denselben Profilen
- [ ] MIG-Unterstützung, Multi-Node/Cluster, NCCL-Test
- [ ] Plugin-System (engines/webuis/mcp/model_sources/…)
- [ ] Admin-Dashboard
- [ ] Eval-/Qualitätsmodul (Langfuse, Golden Datasets, Regression)

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
