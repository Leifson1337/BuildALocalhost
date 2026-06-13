#!/usr/bin/env bash
# Single-node NCCL all-reduce sanity test across the local GPUs (Docker).
# Validates GPU-to-GPU bandwidth before/around serving. Requires NVIDIA Container Toolkit.
# Usage: scripts/nccl-test.sh [NUM_GPUS]
set -euo pipefail

NGPUS="${1:-}"
if [ -z "$NGPUS" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    NGPUS="$(nvidia-smi --query-gpu=count --format=csv,noheader | head -1 | tr -d ' ')"
  else
    NGPUS=1
  fi
fi
echo "[nccl] testing all_reduce across $NGPUS GPU(s)"

IMG="nvcr.io/nvidia/pytorch:24.10-py3"
docker run --rm --gpus all --ipc=host "$IMG" bash -lc "
  if command -v all_reduce_perf >/dev/null 2>&1; then
    all_reduce_perf -b 8 -e 256M -f 2 -g $NGPUS
  else
    echo '[nccl] nccl-tests binary not present in image.'
    echo '       Build from https://github.com/NVIDIA/nccl-tests, or use a nccl-tests image.'
    exit 2
  fi
"
echo "[nccl] done."
