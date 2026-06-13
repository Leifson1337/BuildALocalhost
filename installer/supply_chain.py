"""Supply-chain security helpers (Stage 3).

Extracts the container images from a generated deployment and classifies how tightly each is
pinned. Mutable tags (`latest`, `main`, …) are a supply-chain risk: the same compose file can
silently pull different bits over time. Vulnerability scanning + SBOM are delegated to
scripts (Trivy/Grype/Syft); this module is the pure inventory/classification layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

MUTABLE_TAGS = {"latest", "main", "main-stable", "stable", "edge", "nightly", "dev"}


@dataclass
class ImagePin:
    image: str
    pin: str          # "digest" | "version" | "mutable"


def classify_pin(image: str) -> str:
    """digest (image@sha256:..), version (image:1.2.3), or mutable (image:latest / no tag)."""
    if "@sha256:" in image:
        return "digest"
    # Split off any registry:port/ prefix before locating the tag colon.
    name = image.rsplit("/", 1)[-1]
    if ":" not in name:
        return "mutable"          # no tag => implicit :latest
    tag = name.rsplit(":", 1)[-1]
    if tag.lower() in MUTABLE_TAGS:
        return "mutable"
    return "version"


def extract_images(compose_path: Path) -> list[str]:
    """Return the distinct image references from a rendered docker-compose.yml."""
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    images: list[str] = []
    for svc in (data.get("services") or {}).values():
        img = svc.get("image")
        if img and img not in images:
            images.append(img)
    return images


def pin_compose(compose_path: Path, digest_map: dict[str, str]) -> str:
    """Return compose YAML with each image replaced by image@sha256:<digest>.

    `digest_map` maps the current image ref -> digest (sha256:...). Images not in the map are
    left unchanged. Pure (string/YAML transform); resolving digests is the script's job.
    """
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    for svc in (data.get("services") or {}).values():
        img = svc.get("image")
        if not img or "@sha256:" in img:
            continue
        digest = digest_map.get(img)
        if digest:
            base = img.split("@", 1)[0]
            # Drop any tag; pin to digest.
            repo = base.rsplit(":", 1)[0] if ":" in base.rsplit("/", 1)[-1] else base
            svc["image"] = f"{repo}@{digest}"
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def audit(compose_path: Path) -> dict:
    pins = [ImagePin(img, classify_pin(img)) for img in extract_images(compose_path)]
    return {
        "images": [{"image": p.image, "pin": p.pin} for p in pins],
        "mutable": [p.image for p in pins if p.pin == "mutable"],
        "version": [p.image for p in pins if p.pin == "version"],
        "digest": [p.image for p in pins if p.pin == "digest"],
    }
