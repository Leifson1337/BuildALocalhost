# Universal AI Stack Builder

> Ein interaktiver **AI-Infrastructure-Builder** — kein starres Docker-Image, sondern ein
> Profil-Generator, der GPU-Hardware erkennt (oder simuliert), passende Inference-Stacks
> vorschlägt, eine vollständige Vorschau zeigt und daraus Docker Compose / Kubernetes /
> Bare-Metal-Konfigurationen erzeugt.

Sprache: Wizard & Kurz-Doku **Deutsch**, technische Referenz unter [`docs/`](docs/) **Englisch**.

---

## Was das ist

Statt „ein Server, ein Modell, eine `docker-compose.yml`" baut dieses Projekt einen
**modularen, auswählbaren AI-Inference-Stack**:

- erkennt NVIDIA-GPUs automatisch (H100/H200/B200/B300/… ) **oder** lässt Hardware manuell eingeben/simulieren
- schlägt Serving-Engine (vLLM, SGLang, TGI, NIM, Ollama, llama.cpp) passend zur Hardware vor
- stellt **OpenAI-kompatible** Endpunkte über ein Gateway (LiteLLM) bereit
- bindet Web-UIs (Open WebUI, AnythingLLM, …) an
- integriert RAG und einen **abgesicherten** MCP-Gateway-Layer (deny-by-default)
- bringt Monitoring (Prometheus/Grafana/DCGM) und Defense-in-Depth-Security mit
- zeigt **vor** der Installation eine vollständige Vorschau und validiert Ressourcen

> ⚠️ **Ehrlicher Hinweis zur Sicherheit:** „Vollständig abgesichert" lässt sich bei
> LLM-/MCP-Systemen nicht seriös garantieren. Prompt Injection, Tool-Missbrauch und
> Datenabfluss bleiben reale Risiken (vgl. OWASP LLM Top 10). Dieses Projekt baut deshalb
> **Defense-in-Depth** (Auth, Netzsegmentierung, Tool-Sandboxing, Rate Limits, Audit Logs,
> Secrets-Management, getrennte Rollen) — kein Sicherheitsversprechen. Siehe
> [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Status

Dieses Projekt wird **stufenweise und lauffähig** gebaut. Aktueller Stand siehe
[`ROADMAP.md`](ROADMAP.md) und [`CHANGELOG.md`](CHANGELOG.md).

| Stufe | Inhalt | Status |
|-------|--------|--------|
| **1** | Funktionierender Kern-Stack + Installer-Grundgerüst + Doku | ✅ fertig |
| **2** | Auswahl-Wizard, HF-Suche, RAG, MCP, Security-Profile, Auth-Auswahl, AMD ROCm | ✅ fertig |
| **3** | Routing, K8s/Helm + Parität, Backup/Update/Rollback, Offline, Plugins, Policy/Multi-Tenancy, Supply-Chain, Benchmark/Eval, MIG/NCCL | 🟢 weitgehend fertig |

---

## Schnellstart (Ziel-Workflow)

> Läuft auf **Linux-GPU-Servern**. Auf Windows/macOS nur zum Entwickeln/Testen
> (Simulationsmodus ohne echte GPU).

```bash
git clone <repo-url> ai-stack
cd ai-stack
./install.sh
```

Der Bootstrap (`install.sh`) prüft Python/Docker, legt ein venv an, installiert die
Installer-Abhängigkeiten und startet den Wizard:

```bash
python -m installer            # entspricht installer/main.py
```

### Ohne GPU lokal testen (Simulationsmodus)

```bash
python -m installer --simulate "8xH100"      # Hardware simulieren
python -m installer --dry-run                # nur generieren, nicht starten
```

---

## Projektstruktur

Siehe [`docs/STRUCTURE.md`](docs/STRUCTURE.md) für die vollständige Erklärung. Kurzüberblick:

```
ai-stack/
├── install.sh              # Bootstrap (Linux/macOS bash)
├── installer/              # Python-Installer (Wizard, Detection, Renderer)
├── catalogs/               # Datengetriebene Kataloge (Engines, Hardware, Modelle, …)
├── profiles/               # Vordefinierte Stack-Profile (minimal, production, …)
├── templates/              # Jinja2-Templates (compose, env, configs)
├── configs/                # Statische Konfig-Bausteine
├── docs/                   # Technische Referenz (EN) + Architektur/Security
└── output/                 # Generierte Deployments (nicht eingecheckt)
```

---

## Befehle (Überblick)

```bash
python -m installer --simulate "8xH100" --profile production   # generieren (Wizard/non-interactive)
python -m installer --target kubernetes --profile enterprise   # + K8s-Manifeste + Helm-Chart
python -m installer plan --simulate "4xH100" --users 50        # Kapazität schätzen
python -m installer status   --output output                  # Admin-Überblick
python -m installer audit-images --output output              # Image-Pinning prüfen
python -m installer benchmark --output output --autotune      # TTFT/Latenz/tokens-s messen
python -m installer eval --dataset configs/eval/example-golden.yaml   # Qualität/Regression
```

Betrieb über `make`: `backup`, `restore`, `update`, `rollback`, `bundle`,
`bootstrap-tenants`, `scan`, `sbom`, `pin`, `verify-sigs`, `nccl-test`, `health`.

## Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Gesamtarchitektur, Schichtenmodell, Datenfluss |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Sicherheitskonzept, Threat-Model, MCP-Hardening |
| [`docs/STRUCTURE.md`](docs/STRUCTURE.md) | Repo-Struktur & Modulverantwortlichkeiten |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture Decision Records (ADRs) |
| [`docs/INSTALLER.md`](docs/INSTALLER.md) | Wizard-Ablauf, Modi, Recommendation-Engine |
| [`ROADMAP.md`](ROADMAP.md) | Stufenplan & Feature-Tracking |
| [`CHANGELOG.md`](CHANGELOG.md) | Änderungshistorie |
