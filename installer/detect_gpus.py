"""Host probing: GPU detection + Docker GPU check.

Side-effecting. Degrades gracefully: if NVML / nvidia-smi / docker are unavailable
(e.g. on the Windows dev box), returns a SystemProfile with no GPUs and a note, so the
caller can suggest simulation mode.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from installer import catalog
from installer.hardware import GPUProfile, SystemProfile


def detect_system() -> SystemProfile:
    """Auto-detect the current host. Never raises; collects notes on failure."""
    notes: list[str] = []
    gpus = _detect_nvidia_gpus(notes)
    interconnect = _detect_interconnect(notes) if len(gpus) > 1 else (
        gpus[0].interconnect if gpus else "unknown"
    )
    for g in gpus:
        g.interconnect = interconnect if g.count > 1 else g.interconnect
    if gpus:
        _detect_mig(gpus)

    profile = SystemProfile(
        mode="auto",
        gpus=gpus,
        cpu_cores=_cpu_cores(),
        ram_gb=_ram_gb(),
        storage_free_gb=_storage_free_gb(),
        driver_version=_driver_version(notes),
        docker_gpu_ok=_docker_gpu_ok(notes),
        notes=notes,
    )
    if not gpus:
        notes.append(
            "No NVIDIA GPU detected. Use --simulate \"8xH100\" (or similar) to preview a setup."
        )
    return profile


# --------------------------------------------------------------------------- NVML / nvidia-smi

def _detect_nvidia_gpus(notes: list[str]) -> list[GPUProfile]:
    gpus = _detect_via_nvml(notes)
    if gpus:
        return gpus
    return _detect_via_smi(notes)


def _detect_via_nvml(notes: list[str]) -> list[GPUProfile]:
    try:
        import pynvml  # type: ignore
    except Exception:
        return []
    try:
        pynvml.nvmlInit()
    except Exception as exc:  # driver not present
        notes.append(f"NVML init failed ({exc}); falling back to nvidia-smi.")
        return []
    try:
        count = pynvml.nvmlDeviceGetCount()
        by_model: dict[tuple, list[float]] = {}
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            name = name.decode() if isinstance(name, bytes) else name
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            vram = round(mem.total / 1024**3, 1)
            by_model.setdefault((name, vram), []).append(vram)
        gpus: list[GPUProfile] = []
        for (name, vram), items in by_model.items():
            entry = catalog.find_hardware_model(name) or {}
            gpus.append(
                GPUProfile(
                    vendor="nvidia",
                    model=name,
                    count=len(items),
                    vram_gb=vram,
                    interconnect="unknown",
                    architecture=entry.get("architecture"),
                    gpu_class=entry.get("class", "datacenter_mid"),
                    precision=list(entry.get("precision", ["bfloat16", "fp16"])),
                    authoritative=True,
                    mig_capable=bool(entry.get("mig_capable", False)),
                )
            )
        return gpus
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _detect_via_smi(notes: list[str]) -> list[GPUProfile]:
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    if not out:
        return []
    by_model: dict[tuple, int] = {}
    vram_for: dict[tuple, float] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        try:
            vram = round(float(parts[1]) / 1024, 1)
        except ValueError:
            continue
        key = (name, vram)
        by_model[key] = by_model.get(key, 0) + 1
        vram_for[key] = vram
    gpus = []
    for (name, vram), cnt in by_model.items():
        entry = catalog.find_hardware_model(name) or {}
        gpus.append(
            GPUProfile(
                vendor="nvidia",
                model=name,
                count=cnt,
                vram_gb=vram,
                architecture=entry.get("architecture"),
                gpu_class=entry.get("class", "datacenter_mid"),
                precision=list(entry.get("precision", ["bfloat16", "fp16"])),
                mig_capable=bool(entry.get("mig_capable", False)),
            )
        )
    return gpus


def _detect_mig(gpus: list[GPUProfile]) -> None:
    """Set mig_active on GPUs if `nvidia-smi` reports MIG mode enabled."""
    out = _run(["nvidia-smi", "--query-gpu=mig.mode.current", "--format=csv,noheader"])
    if not out:
        return
    if any("enabled" in line.lower() for line in out.splitlines()):
        for g in gpus:
            g.mig_active = True
            g.mig_capable = True


def _detect_interconnect(notes: list[str]) -> str:
    out = _run(["nvidia-smi", "topo", "-m"])
    if not out:
        return "unknown"
    text = out.upper()
    if "NV" in text and ("NVL" in text or "NV1" in text or "NV2" in text or "NV4" in text
                         or "NV6" in text or "NV8" in text or "NV12" in text or "NV18" in text):
        # Heuristic: NVLink/NVSwitch links present in topology matrix.
        return "nvswitch" if "NV18" in text or "NV12" in text else "nvlink"
    return "pcie"


# --------------------------------------------------------------------------- host resources

def _driver_version(notes: list[str]) -> Optional[str]:
    out = _run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    return out.splitlines()[0].strip() if out else None


def _cpu_cores() -> Optional[int]:
    import os
    return os.cpu_count()


def _ram_gb() -> Optional[float]:
    # Try psutil-free approach via /proc/meminfo (Linux); else None.
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = float(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except OSError:
        return None
    return None


def _storage_free_gb() -> Optional[float]:
    try:
        usage = shutil.disk_usage("/")
        return round(usage.free / 1024**3, 1)
    except OSError:
        return None


def _docker_gpu_ok(notes: list[str]) -> Optional[bool]:
    if not shutil.which("docker"):
        notes.append("docker CLI not found; cannot verify Docker GPU access.")
        return None
    # Cheap check: does `docker info` mention the nvidia runtime?
    out = _run(["docker", "info", "--format", "{{json .Runtimes}}"])
    if out and "nvidia" in out.lower():
        return True
    notes.append(
        "NVIDIA Docker runtime not detected in `docker info`. "
        "Install the NVIDIA Container Toolkit on the GPU host."
    )
    return False


def _run(cmd: list[str]) -> Optional[str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout
