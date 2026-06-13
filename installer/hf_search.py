"""Hugging Face live model search (Stage 2).

Thin wrapper around huggingface_hub. Degrades gracefully: if the library or network is
unavailable, returns an empty list and a note, so the wizard falls back to the curated
catalog. Also exposes a gated/license probe.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelHit:
    id: str
    downloads: int | None
    likes: int | None
    gated: bool | str | None

    @property
    def is_gated(self) -> bool:
        return bool(self.gated) and self.gated not in ("false", "False", False)


def search(query: str, task: str = "text-generation", limit: int = 30) -> list[ModelHit]:
    """Search the HF Hub by free text + task, sorted by downloads.

    Returns [] on any failure (offline, missing lib) — caller should fall back.
    """
    try:
        from huggingface_hub import HfApi
    except Exception:
        return []
    try:
        api = HfApi()
        models = api.list_models(
            search=query or None,
            task=task or None,
            sort="downloads",
            direction=-1,
            limit=limit,
        )
        hits: list[ModelHit] = []
        for m in models:
            hits.append(
                ModelHit(
                    id=m.id if hasattr(m, "id") else getattr(m, "modelId", str(m)),
                    downloads=getattr(m, "downloads", None),
                    likes=getattr(m, "likes", None),
                    gated=getattr(m, "gated", None),
                )
            )
        return hits
    except Exception:
        return []


def probe_gated(model_id: str) -> bool | None:
    """Best-effort: is the model gated? None if it cannot be determined offline."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(model_id)
        return bool(getattr(info, "gated", False))
    except Exception:
        return None


# Map our wizard categories to HF tasks for filtering.
CATEGORY_TASK = {
    "chat_instruct": "text-generation",
    "reasoning": "text-generation",
    "code": "text-generation",
    "small_fast": "text-generation",
    "multimodal_vision": "image-text-to-text",
    "embeddings": "feature-extraction",
    "reranker": "text-classification",
}
