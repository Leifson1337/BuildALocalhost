# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unreleased]

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
