#!/usr/bin/env bash
# Universal AI Stack Builder — bootstrap (Linux/macOS).
# Checks prerequisites, creates a venv, installs installer deps, runs the wizard.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

info()  { printf '\033[36m[install]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[31m[error]\033[0m %s\n' "$*" >&2; }

# --- Python ---------------------------------------------------------------
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  error "Python 3 not found. Please install Python 3.10+."
  exit 1
fi
PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
info "Using $PY ($PYV)"

# --- Docker (optional but recommended) ------------------------------------
if command -v docker >/dev/null 2>&1; then
  info "Docker found: $(docker --version)"
  if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -qi nvidia; then
    info "NVIDIA Docker runtime detected."
  else
    warn "NVIDIA Container Toolkit not detected. GPU containers will fail until installed:"
    warn "  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/"
  fi
else
  warn "Docker not found. The installer can still generate configs (use --dry-run)."
fi

# --- venv + deps ----------------------------------------------------------
if [ ! -d ".venv" ]; then
  info "Creating virtual environment (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
info "Installing installer dependencies…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

# --- Run wizard -----------------------------------------------------------
info "Starting the wizard…"
exec python -m installer "$@"
