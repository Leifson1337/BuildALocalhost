"""Interactive wizard helpers (Stage 2).

Each function is guarded: if questionary is unavailable (or the user is non-interactive),
it returns the provided default. The wizard collects user choices into an `overrides` dict
that profile_builder merges onto the base profile.

Modes: auto | manual | profile | expert | simulation.
Wizard texts are German; code/comments English.
"""
from __future__ import annotations

from typing import Any, Optional

from installer import catalog, hf_search
from installer.hardware import SystemProfile, build_manual, build_simulation
from installer.recommend import GOALS, Recommendation


def _q():
    try:
        import questionary
        return questionary
    except Exception:
        return None


# --------------------------------------------------------------------------- mode + hardware

def select_mode(default: str = "auto") -> str:
    q = _q()
    if not q:
        return default
    choice = q.select(
        "Was möchtest du tun?",
        choices=[
            {"name": "Aktuelle Hardware erkennen und optimales Setup vorschlagen", "value": "auto"},
            {"name": "Hardware manuell eingeben", "value": "manual"},
            {"name": "Fertiges Profil auswählen", "value": "profile"},
            {"name": "Expertenmodus (jede Ebene einzeln)", "value": "expert"},
            {"name": "Setup simulieren (ohne Installation)", "value": "simulation"},
        ],
        default="auto",
    ).ask()
    return choice or default


def ask_simulation_spec(default: str = "8xH100") -> str:
    q = _q()
    if not q:
        return default
    spec = q.text('Hardware-Spec (z.B. "8xH100", "2xRTX4090", "8xB300", "8xMI300X"):',
                  default=default).ask()
    return spec or default


def ask_manual_hardware() -> SystemProfile:
    """Prompt for a full manual hardware profile. Falls back to a sane default off-TUI."""
    q = _q()
    if not q:
        return build_manual(vendor="nvidia", model="H100 SXM", count=1, vram_gb=80,
                            interconnect="pcie", ram_gb=128, storage_free_gb=1000)
    vendor = q.select("GPU-Hersteller?",
                      choices=["nvidia", "amd", "cpu", "custom"], default="nvidia").ask()
    model = q.text("GPU-Modell (z.B. H100 SXM, B300, MI300X, RTX 4090)?", default="H100 SXM").ask()
    count = int(q.text("Anzahl GPUs?", default="1").ask() or "1")
    vram = float(q.text("VRAM pro GPU (GB)?", default="80").ask() or "80")
    interconnect = q.select("GPU-Verbindung?",
                            choices=["pcie", "nvlink", "nvswitch", "infiniband", "unknown"],
                            default="pcie").ask()
    ram = float(q.text("System-RAM (GB)?", default="256").ask() or "256")
    storage = float(q.text("Freier Storage (GB)?", default="2000").ask() or "2000")
    return build_manual(vendor=vendor, model=model, count=count, vram_gb=vram,
                        interconnect=interconnect, ram_gb=ram, storage_free_gb=storage)


def select_goal(default: str = "high_throughput_chat") -> str:
    q = _q()
    if not q:
        return default
    choice = q.select("Was ist das Hauptziel?", choices=sorted(GOALS),
                      default=default if default in GOALS else "high_throughput_chat").ask()
    return choice or default


def select_profile(default: str = "production") -> str:
    q = _q()
    if not q:
        return default
    choices = catalog.available_profiles()
    choice = q.select("Welches Profil als Basis?", choices=choices,
                      default=default if default in choices else choices[0]).ask()
    return choice or default


# --------------------------------------------------------------------------- stack selections

def build_overrides(
    *,
    profile_name: str,
    recommendation: Recommendation,
    expert: bool,
) -> tuple[Optional[str], dict[str, Any]]:
    """Collect engine/model/UI/RAG/MCP/security/auth choices.

    Returns (model_or_none, overrides). In non-expert mode only the essentials are asked.
    """
    q = _q()
    if not q:
        return None, {}

    overrides: dict[str, Any] = {}

    # Engine
    engine = _select_engine(q, recommendation)
    if engine:
        overrides.setdefault("inference", {})["engine"] = engine

    # Model
    model = _select_model(q)

    # Web UIs
    uis = _select_webuis(q)
    if uis is not None:
        overrides.setdefault("web", {})["ui"] = uis

    # Security profile + auth
    sec_profile = _select_security(q)
    if sec_profile:
        overrides.setdefault("security", {})["profile"] = sec_profile
    auth = _select_auth(q, sec_profile)
    if auth:
        overrides.setdefault("web", {})["auth"] = auth

    if expert:
        _expert_rag(q, overrides)
        _expert_mcp(q, overrides, sec_profile)
        _expert_inference(q, overrides)

    return model, overrides


def _select_engine(q, rec: Recommendation) -> Optional[str]:
    engines = [e["id"] for e in catalog.load_engines().get("engines", [])]
    default = rec.primary_engine
    return q.select(
        f"Serving-Engine? (Empfehlung: {default})",
        choices=engines,
        default=default if default in engines else engines[0],
    ).ask()


def _select_model(q) -> Optional[str]:
    source = q.select(
        "Modellquelle?",
        choices=[
            {"name": "Kuratierte Liste", "value": "curated"},
            {"name": "Hugging Face Live-Suche", "value": "hf"},
            {"name": "Eigene HF-ID eingeben", "value": "custom"},
            {"name": "Lokaler Pfad", "value": "local"},
        ],
        default="curated",
    ).ask()

    if source == "curated":
        return _pick_curated(q)
    if source == "hf":
        return _pick_hf(q)
    if source == "custom":
        return q.text("HF-Modell-ID (org/model):").ask() or None
    if source == "local":
        return q.text("Lokaler Modellpfad (im Container /models/...):", default="/models/my-model").ask()
    return None


def _pick_curated(q) -> Optional[str]:
    cats = catalog.load_models().get("categories", {})
    category = q.select("Kategorie?", choices=list(cats.keys()),
                        default="chat_instruct").ask()
    suggestions = cats.get(category, {}).get("suggestions", [])
    choices = [
        {"name": f"{s['hf_id']}  (~{s.get('min_vram_gb','?')}GB"
                 f"{', gated' if s.get('gated') else ''})",
         "value": s["hf_id"]}
        for s in suggestions
    ]
    if not choices:
        return None
    return q.select("Modell?", choices=choices).ask()


def _pick_hf(q) -> Optional[str]:
    query = q.text("Suchbegriff (HF):", default="qwen2.5 instruct").ask()
    task = q.select("Aufgabe?",
                    choices=["text-generation", "image-text-to-text",
                             "feature-extraction", "text-classification"],
                    default="text-generation").ask()
    hits = hf_search.search(query or "", task=task, limit=25)
    if not hits:
        q.print("  Keine Treffer / offline — bitte HF-ID manuell eingeben.") if hasattr(q, "print") else None
        return q.text("HF-Modell-ID (org/model):").ask() or None
    choices = [
        {"name": f"{h.id}  (⬇{h.downloads or 0}{' · gated' if h.is_gated else ''})", "value": h.id}
        for h in hits
    ]
    return q.select("Treffer wählen:", choices=choices).ask()


def _select_webuis(q):
    cat = [w for w in catalog.load_webuis().get("webuis", [])]
    choices = [{"name": w["name"], "value": w["id"],
                "checked": bool(w.get("default"))} for w in cat]
    picked = q.checkbox("Welche Web-UIs?", choices=choices).ask()
    return picked if picked is not None else None


def _select_security(q) -> Optional[str]:
    profs = catalog.load_security().get("profiles", [])
    choices = [{"name": f"{p['name']}", "value": p["id"]} for p in profs]
    return q.select("Sicherheitsprofil?", choices=choices, default="public_secure").ask()


def _select_auth(q, sec_profile: Optional[str]) -> Optional[str]:
    rec_map = catalog.load_auth().get("recommended_by_security_profile", {})
    recommended = rec_map.get(sec_profile or "public_secure", [])
    providers = catalog.load_auth().get("providers", [])
    choices = [
        {"name": p["name"] + ("  (empfohlen)" if p["id"] in recommended else ""),
         "value": p["id"]}
        for p in providers
    ]
    default = recommended[0] if recommended else "litellm_keys"
    return q.select("Auth-Layer?", choices=choices, default=default).ask()


def _expert_rag(q, overrides: dict) -> None:
    if not q.confirm("RAG-Stack aktivieren (Vector-DB + Embeddings + Reranker)?",
                     default=False).ask():
        return
    rag_cat = catalog.load_rag()
    vdb = q.select("Vector-DB?", choices=[v["id"] for v in rag_cat["vector_dbs"]],
                   default="qdrant").ask()
    doc = q.select("Dokumenten-App?", choices=["anythingllm", "none"], default="anythingllm").ask()
    overrides["rag"] = {
        "enabled": True,
        "vector_db": vdb,
        "embeddings_model": rag_cat["embeddings"]["default_model"],
        "reranker_model": rag_cat["reranker"]["default_model"],
        "document_app": doc,
    }


def _expert_mcp(q, overrides: dict, sec_profile: Optional[str]) -> None:
    if not q.confirm("MCP-Gateway aktivieren (Tools für Agenten)?", default=False).ask():
        return
    servers = catalog.load_mcp().get("servers", [])
    allow_dangerous = (catalog.get_security_profile(sec_profile or "public_secure") or {}
                       ).get("allow_dangerous_mcp", False)
    choices = []
    for s in servers:
        tier = s.get("tier", "advanced")
        if tier == "dangerous_requires_confirmation" and not allow_dangerous:
            continue  # hidden unless the security profile allows it
        choices.append({"name": f"{s['id']}  [{tier}]", "value": s["id"],
                        "checked": tier == "safe_default"})
    picked = q.checkbox("MCP-Server (deny-by-default; nur Ausgewählte aktiv):",
                        choices=choices).ask()
    overrides["mcp"] = {"enabled": True, "servers": picked or []}


def _expert_inference(q, overrides: dict) -> None:
    dtype = q.select("Präzision (dtype)?",
                     choices=["bfloat16", "fp16", "fp8", "fp4"], default="bfloat16").ask()
    overrides.setdefault("inference", {})["dtype"] = dtype
