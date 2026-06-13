"""Preview rendering.

Prints the full deployment plan before anything is written or started: hardware,
recommendation + alternatives, the resolved stack, ports/volumes, validation results,
and risks.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from installer.profile_builder import ResolvedConfig
from installer.validators import Issue

console = Console()

_SEV_STYLE = {"fatal": "bold red", "warning": "yellow", "info": "cyan"}


def show(cfg: ResolvedConfig, issues: list[Issue]) -> None:
    console.print()
    console.rule("[bold]AI Stack — Vorschau / Preview")
    _hardware(cfg)
    _recommendation(cfg)
    _stack(cfg)
    _network(cfg)
    _issues(issues)
    _risks(cfg)


def _hardware(cfg: ResolvedConfig) -> None:
    sys = cfg.system
    t = Table(title="Hardware", box=box.SIMPLE, show_header=True, header_style="bold")
    t.add_column("Eigenschaft")
    t.add_column("Wert")
    t.add_row("Modus", sys.mode)
    if sys.gpus:
        for g in sys.gpus:
            t.add_row("GPU", f"{g.count}× {g.model} @ {g.vram_gb} GB ({g.interconnect})")
        t.add_row("VRAM gesamt", f"{sys.total_vram_gb} GB")
    else:
        t.add_row("GPU", "[yellow]keine erkannt (CPU/Simulation)[/yellow]")
    t.add_row("CPU-Kerne", str(sys.cpu_cores or "—"))
    t.add_row("RAM", f"{sys.ram_gb} GB" if sys.ram_gb else "—")
    t.add_row("Storage frei", f"{sys.storage_free_gb} GB" if sys.storage_free_gb else "—")
    if sys.driver_version:
        t.add_row("NVIDIA-Treiber", sys.driver_version)
    console.print(t)
    for note in sys.notes:
        console.print(f"  [dim]· {note}[/dim]")


def _recommendation(cfg: ResolvedConfig) -> None:
    rec = cfg.recommendation
    t = Table(title="Empfehlung", box=box.SIMPLE, header_style="bold")
    t.add_column("Aspekt")
    t.add_column("Wert")
    t.add_row("Primäre Engine(s)", ", ".join(rec.primary_engines))
    t.add_row("Alternativen", ", ".join(rec.advanced_engines))
    t.add_row("Präzision", ", ".join(rec.precision))
    t.add_row("Tensor parallel", str(rec.tensor_parallel_size))
    t.add_row("Pipeline parallel", str(rec.pipeline_parallel_size))
    t.add_row("Data-parallel Replicas", str(rec.data_parallel_replicas))
    t.add_row("Runtime", rec.runtime)
    console.print(t)

    if rec.alternatives:
        at = Table(title="Varianten", box=box.MINIMAL, header_style="bold")
        at.add_column("Variante")
        at.add_column("Engine")
        at.add_column("Begründung")
        for alt in rec.alternatives:
            at.add_row(alt.name, alt.engine, alt.rationale)
        console.print(at)


def _stack(cfg: ResolvedConfig) -> None:
    inf = cfg.data["inference"]
    t = Table(title="Geplanter Stack", box=box.SIMPLE, header_style="bold")
    t.add_column("Komponente")
    t.add_column("Auswahl")
    t.add_row("Profil", cfg.profile_name)
    t.add_row("Runtime", cfg.runtime_kind)
    t.add_row("Engine", inf["engine"])
    t.add_row("Modell", cfg.model)
    t.add_row("dtype", str(inf.get("dtype")))
    t.add_row("max_model_len", str(inf.get("max_model_len")))
    t.add_row("GPU mem util", str(inf.get("gpu_memory_utilization")))
    t.add_row("Gateway", cfg.data.get("gateway", {}).get("type", "—"))
    t.add_row("Web-UI", ", ".join(cfg.data.get("web", {}).get("ui", []) or ["—"]))
    t.add_row("Auth", cfg.auth_provider_id)
    if cfg.rag_enabled:
        rd = cfg.data.get("rag", {})
        t.add_row("RAG", f"{rd.get('vector_db')} + {rd.get('embeddings_model')} "
                         f"+ reranker ({rd.get('document_app')})")
    if cfg.mcp_enabled:
        t.add_row("MCP", ", ".join(cfg.data.get("mcp", {}).get("servers", []) or ["—"]))
    t.add_row("Monitoring", "ja" if cfg.monitoring_enabled else "nein")
    t.add_row("Reverse Proxy", cfg.data.get("web", {}).get("reverse_proxy", "—"))
    t.add_row("Security-Profil", cfg.security_profile_id)
    console.print(t)


def _network(cfg: ResolvedConfig) -> None:
    web = cfg.data.get("web", {})
    lines = []
    if cfg.uses_traefik:
        domains = web.get("domains", {}) or {}
        lines.append("Öffentliche Ports: 80, 443 (nur Traefik)")
        for key, dom in domains.items():
            lines.append(f"  {key}: https://{dom or '<nicht gesetzt>'}")
    else:
        expose = web.get("expose", {}) or {}
        bind = cfg.data.get("security", {}).get("bind", "127.0.0.1")
        if expose.get("open_webui_port"):
            lines.append(f"Open WebUI:  http://{bind}:{expose['open_webui_port']}")
        if expose.get("litellm_port"):
            lines.append(f"LiteLLM API: http://{bind}:{expose['litellm_port']}/v1")
    console.print(Panel("\n".join(lines) or "—", title="Endpunkte / Ports", border_style="blue"))


def _issues(issues: list[Issue]) -> None:
    if not issues:
        console.print(Panel("[green]Keine Probleme gefunden.[/green]", title="Validierung"))
        return
    t = Table(title="Validierung", box=box.SIMPLE, header_style="bold")
    t.add_column("Schwere")
    t.add_column("Code")
    t.add_column("Meldung")
    for i in issues:
        style = _SEV_STYLE.get(i.severity, "")
        t.add_row(f"[{style}]{i.severity}[/{style}]", i.code, i.message)
    console.print(t)


def _risks(cfg: ResolvedConfig) -> None:
    msg = (
        "[bold]Sicherheitshinweis:[/bold] „Vollständig abgesichert“ ist bei LLM/MCP nicht "
        "garantierbar (Prompt Injection, Tool-Missbrauch, Datenabfluss). Dieser Stack baut "
        "Defense-in-Depth — siehe docs/SECURITY.md."
    )
    console.print(Panel(msg, border_style="red", title="Risiken"))
