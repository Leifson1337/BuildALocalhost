"""Hardware data model + builders.

`SystemProfile` is the single representation of the target machine, regardless of whether it
was auto-detected, manually entered, or simulated. This module is pure; the side-effecting
probe lives in detect_gpus.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from installer import catalog

Interconnect = Literal["pcie", "nvlink", "nvswitch", "infinity_fabric", "infiniband", "unknown"]
Mode = Literal["auto", "manual", "simulation"]


@dataclass
class GPUProfile:
    vendor: str               # nvidia | amd | cpu | custom
    model: str
    count: int
    vram_gb: float
    interconnect: Interconnect = "unknown"
    architecture: Optional[str] = None
    gpu_class: Optional[str] = None          # datacenter_high | consumer | ...
    precision: list[str] = field(default_factory=list)
    authoritative: bool = True               # False => catalog estimate, not measured

    @property
    def total_vram_gb(self) -> float:
        return round(self.count * self.vram_gb, 2)


@dataclass
class SystemProfile:
    mode: Mode
    gpus: list[GPUProfile] = field(default_factory=list)
    cpu_model: Optional[str] = None
    cpu_cores: Optional[int] = None
    ram_gb: Optional[float] = None
    storage_free_gb: Optional[float] = None
    network: Optional[str] = None
    driver_version: Optional[str] = None
    docker_gpu_ok: Optional[bool] = None     # None = unknown (e.g. simulation)
    notes: list[str] = field(default_factory=list)

    # --- derived ---
    @property
    def total_gpu_count(self) -> int:
        return sum(g.count for g in self.gpus)

    @property
    def total_vram_gb(self) -> float:
        return round(sum(g.total_vram_gb for g in self.gpus), 2)

    @property
    def primary_gpu(self) -> Optional[GPUProfile]:
        return self.gpus[0] if self.gpus else None

    @property
    def has_gpu(self) -> bool:
        return any(g.vendor in ("nvidia", "amd") and g.count > 0 for g in self.gpus)

    @property
    def gpu_class(self) -> str:
        if not self.gpus:
            return "cpu_only"
        return self.primary_gpu.gpu_class or "consumer"

    @property
    def runtime_kind(self) -> str:
        """GPU runtime family used to pick container images: cuda | rocm | cpu."""
        if not self.gpus:
            return "cpu"
        vendor = self.primary_gpu.vendor
        if vendor == "amd":
            return "rocm"
        if vendor == "nvidia":
            return "cuda"
        return "cpu"


# --------------------------------------------------------------------------- builders

def gpu_from_catalog(model_query: str, count: int) -> GPUProfile:
    """Build a GPUProfile from the hardware catalog (used for simulation/manual)."""
    entry = catalog.find_hardware_model(model_query)
    if entry is None:
        entry = catalog.custom_fallback_gpu()
        model_name = model_query or entry.get("model", "Custom GPU")
    else:
        model_name = entry["model"]
    return GPUProfile(
        vendor=entry.get("vendor", "custom"),
        model=model_name,
        count=count,
        vram_gb=float(entry.get("vram_gb", 24)),
        interconnect=_default_interconnect(entry, count),
        architecture=entry.get("architecture"),
        gpu_class=entry.get("class"),
        precision=list(entry.get("precision", [])),
        authoritative=bool(entry.get("authoritative", True)),
    )


def _default_interconnect(entry: dict, count: int) -> Interconnect:
    if count <= 1:
        return "pcie"
    return entry.get("default_interconnect", "unknown")


_SIM_RE = re.compile(r"^\s*(\d+)\s*x?\s*(.+?)\s*$", re.IGNORECASE)


def build_simulation(spec: str) -> SystemProfile:
    """Parse a simulation string like '8xH100', '2xRTX4090', 'GB300NVL72'.

    Falls back to count=1 if no leading count is present.
    """
    spec = spec.strip()
    match = _SIM_RE.match(spec)
    if match and match.group(1):
        count = int(match.group(1))
        model_query = match.group(2)
    else:
        count = 1
        model_query = spec
    gpu = gpu_from_catalog(model_query, count)
    notes = [f"Simulated hardware from spec '{spec}'."]
    if not gpu.authoritative:
        notes.append(
            f"VRAM for {gpu.model} is a catalog estimate, not measured — verify on real hardware."
        )
    # Reasonable simulated host resources scaled to GPU count.
    return SystemProfile(
        mode="simulation",
        gpus=[gpu],
        cpu_model="Simulated CPU",
        cpu_cores=max(16, gpu.count * 12),
        ram_gb=max(64, gpu.count * 128),
        storage_free_gb=max(500, gpu.count * 1000),
        network="unknown",
        docker_gpu_ok=None,
        notes=notes,
    )


def build_manual(
    *,
    vendor: str,
    model: str,
    count: int,
    vram_gb: float,
    interconnect: Interconnect,
    ram_gb: float | None = None,
    storage_free_gb: float | None = None,
    cpu_model: str | None = None,
    network: str | None = None,
) -> SystemProfile:
    """Build a SystemProfile from explicit manual input (Stage 2 wizard)."""
    catalog_entry = catalog.find_hardware_model(model)
    gpu = GPUProfile(
        vendor=vendor,
        model=model,
        count=count,
        vram_gb=vram_gb,
        interconnect=interconnect,
        architecture=(catalog_entry or {}).get("architecture"),
        gpu_class=(catalog_entry or {}).get("class", "consumer"),
        precision=list((catalog_entry or {}).get("precision", ["bfloat16", "fp16"])),
        authoritative=True,
    )
    return SystemProfile(
        mode="manual",
        gpus=[gpu],
        cpu_model=cpu_model,
        ram_gb=ram_gb,
        storage_free_gb=storage_free_gb,
        network=network,
        docker_gpu_ok=None,
        notes=["Manually entered hardware."],
    )
