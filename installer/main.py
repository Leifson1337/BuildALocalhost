"""Wizard / CLI entrypoint (Typer).

Stage 1 implements: auto-detect + simulation + profile selection, recommendation, validation,
preview, render, and optional start. Manual/expert modes and the full interactive layer-by-layer
wizard land in Stage 2 (see ROADMAP.md). Wizard texts are German; code/comments English.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from installer import DEFAULT_OUTPUT_DIR, catalog, detect_gpus, preview, profile_builder
from installer import compose_renderer, validators
from installer.recommend import recommend

app = typer.Typer(add_completion=False, help="Universal AI Stack Builder")
console = Console()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    profile: str = typer.Option("production", "--profile", help="Basis-Profil (minimal|production|…)."),
    simulate: Optional[str] = typer.Option(None, "--simulate", help='Hardware simulieren, z.B. "8xH100".'),
    goal: str = typer.Option("high_throughput_chat", "--goal", help="Optimierungsziel."),
    model: Optional[str] = typer.Option(None, "--model", help="HF-Modell-ID oder lokaler Pfad."),
    output: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output", help="Ausgabeverzeichnis."),
    target: str = typer.Option("compose", "--target", help="Deployment-Ziel: compose | kubernetes."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Ohne Rückfragen."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Nur generieren, nicht starten."),
    no_validate: bool = typer.Option(False, "--no-validate", help="Validierung überspringen."),
    start: bool = typer.Option(False, "--start", help="Nach dem Rendern `docker compose up -d`."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (e.g. `list-profiles`) was requested

    console.print("[bold]Universal AI Stack Builder[/bold] — Stufe 2\n")

    from installer import wizard
    from installer.hardware import build_simulation

    interactive = not non_interactive
    overrides: dict = {}

    # 1) Mode + hardware
    if simulate:
        system = build_simulation(simulate)
        console.print(f"[cyan]Simulationsmodus:[/cyan] {simulate}")
        mode = "simulation"
    elif not interactive:
        system = detect_gpus.detect_system()
        mode = "auto"
    else:
        mode = wizard.select_mode("auto")
        if mode == "simulation":
            system = build_simulation(wizard.ask_simulation_spec())
        elif mode == "manual":
            system = wizard.ask_manual_hardware()
        else:  # auto / profile / expert all probe real hardware
            console.print("[cyan]Erkenne Hardware…[/cyan]")
            system = detect_gpus.detect_system()
            if not system.has_gpu:
                console.print("[yellow]Keine GPU erkannt.[/yellow] Wechsle in Simulation.")
                system = build_simulation(wizard.ask_simulation_spec())

    # 2) Goal + profile
    if interactive and not simulate:
        goal = wizard.select_goal(goal)
        profile = wizard.select_profile(profile)

    # 3) Recommendation
    rec = recommend(system, goal)

    # 4) Stack selections (engine/model/UI/security/auth [+ RAG/MCP in expert])
    if interactive and not simulate:
        sel_model, overrides = wizard.build_overrides(
            profile_name=profile, recommendation=rec, expert=(mode == "expert")
        )
        if sel_model:
            model = sel_model

    # 5) Resolve config
    cfg = profile_builder.build(
        profile_name=profile, system=system, recommendation=rec,
        model=model, goal=goal, overrides=overrides,
    )

    # 5) Validate (ports skipped on dry-run / simulation)
    issues = []
    if not no_validate:
        check_ports = not (dry_run or system.mode == "simulation")
        issues = validators.validate(cfg, check_ports=check_ports)

    # 6) Preview
    preview.show(cfg, issues)

    if validators.has_fatal(issues):
        console.print("\n[bold red]Abbruch:[/bold red] fatale Probleme gefunden. "
                      "Bitte beheben oder Auswahl ändern.")
        raise typer.Exit(code=2)

    # 7) Confirm
    if not non_interactive:
        if not _confirm("Konfiguration generieren?", default=True):
            console.print("Abgebrochen. Nichts geschrieben.")
            raise typer.Exit(code=0)

    # 8) Render
    written = compose_renderer.render(cfg, output)
    if target == "kubernetes":
        from installer import k8s_renderer
        written += k8s_renderer.render(cfg, output)
        console.print("[cyan]Kubernetes-Manifeste + Helm-Chart erzeugt (output/k8s/).[/cyan]")
    console.print(f"\n[green]Generiert[/green] ({len(written)} Dateien) in [bold]{output}[/bold]:")
    for p in written:
        console.print(f"  · {p.relative_to(output.parent) if output.parent in p.parents else p}")

    _print_next_steps(cfg, output)

    # 9) Optionally start
    if start and not dry_run:
        _docker_up(output)


@app.command("list-profiles")
def list_profiles() -> None:
    """Verfügbare Profile auflisten."""
    for name in catalog.available_profiles():
        prof = catalog.load_profile(name)
        console.print(f"[bold]{name}[/bold] — {prof.get('description', '')}")


@app.command("list-engines")
def list_engines() -> None:
    """Verfügbare Serving-Engines auflisten."""
    for eng in catalog.load_engines().get("engines", []):
        default = " [green](default)[/green]" if eng.get("default") else ""
        console.print(f"[bold]{eng['id']}[/bold]{default} — {eng.get('name')} "
                      f"[dim]({eng.get('api')})[/dim]")


@app.command("audit-images")
def audit_images(
    output: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output", help="Deployment-Verzeichnis."),
) -> None:
    """Image-Inventar + Pinning-Status (Supply-Chain). Warnt bei mutablen Tags."""
    from installer import supply_chain
    compose = output / "docker-compose.yml"
    if not compose.exists():
        console.print(f"[red]Keine docker-compose.yml in {output}[/red] — erst generieren.")
        raise typer.Exit(1)
    report = supply_chain.audit(compose)
    _sev = {"digest": "green", "version": "cyan", "mutable": "yellow"}
    for item in report["images"]:
        c = _sev.get(item["pin"], "")
        console.print(f"  [{c}]{item['pin']:8}[/{c}] {item['image']}")
    if report["mutable"]:
        console.print(f"\n[yellow]{len(report['mutable'])} mutable Tag(s)[/yellow] — "
                      "für Produktion auf Version/Digest pinnen:")
        for img in report["mutable"]:
            console.print(f"  · {img}")
        console.print("\nScan: scripts/scan-images.sh · SBOM: scripts/generate-sbom.sh")
    else:
        console.print("\n[green]Alle Images versions-/digest-gepinnt.[/green]")


@app.command("plan")
def plan(
    simulate: Optional[str] = typer.Option(None, "--simulate", help='Hardware, z.B. "4xH100".'),
    model: str = typer.Option("Qwen/Qwen2.5-7B-Instruct", "--model"),
    users: int = typer.Option(10, "--users", help="Gleichzeitige Nutzer."),
    prompt_tokens: int = typer.Option(1024, "--prompt-tokens"),
    output_tokens: int = typer.Option(512, "--output-tokens"),
    latency_target: float = typer.Option(5.0, "--latency-target", help="Sekunden."),
) -> None:
    """Kapazität schätzen (Heuristik — danach `benchmark` zur Messung)."""
    from installer import capacity
    from installer.hardware import build_simulation
    system = build_simulation(simulate) if simulate else detect_gpus.detect_system()
    wl = capacity.Workload(concurrent_users=users, avg_prompt_tokens=prompt_tokens,
                           avg_output_tokens=output_tokens, latency_target_s=latency_target)
    est = capacity.estimate(system, model, wl)
    console.print(f"\n[bold]Kapazitätsschätzung[/bold] — {est.model}")
    console.print(f"  VRAM gesamt:        {est.total_vram_gb} GB")
    console.print(f"  Gewichte (ca.):     {est.model_weights_gb} GB")
    console.print(f"  KV-Cache-Budget:    {est.kv_cache_budget_gb} GB")
    console.print(f"  pro Request (ca.):  {est.per_request_gb} GB")
    console.print(f"  max. parallel (ca.):{est.max_concurrent_requests}")
    console.print(f"  Durchsatzklasse:    {est.throughput_class}")
    console.print(f"  Ziel erreichbar:    {'ja' if est.meets_target else 'nein'}")
    for n in est.notes:
        console.print(f"  [dim]· {n}[/dim]")


@app.command("benchmark")
def benchmark_cmd(
    output: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output", help="Deployment-Verzeichnis (.env)."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Überschreibt Endpoint."),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    model: str = typer.Option("main-chat", "--model"),
    requests_total: int = typer.Option(50, "--requests"),
    concurrency: int = typer.Option(10, "--concurrency"),
    autotune: bool = typer.Option(False, "--autotune", help="Concurrency-Sweep."),
) -> None:
    """Gateway benchmarken (TTFT, Latenz p50/p95/p99, tokens/s). Stack muss laufen."""
    from installer import benchmark as bm
    if base_url is None or api_key is None:
        base_url, api_key = _read_endpoint(output, base_url, api_key)
    if not base_url or not api_key:
        console.print("[red]base-url/api-key fehlen[/red] (oder keine .env in --output).")
        raise typer.Exit(1)
    if autotune:
        best, results = bm.autotune(base_url=base_url, api_key=api_key, model=model)
        for r in results:
            console.print(f"  c={r.concurrency:>3}  tok/s={r.tokens_per_sec:>7}  "
                          f"TTFT p95={r.ttft_p95}s  lat p95={r.latency_p95}s  "
                          f"({r.successes}/{r.requests} ok)")
        console.print(f"\n[green]Beste Concurrency nach Durchsatz:[/green] {best}")
    else:
        r = bm.run(base_url=base_url, api_key=api_key, model=model,
                   requests_total=requests_total, concurrency=concurrency)
        console.print(f"\n[bold]Benchmark[/bold] ({r.successes}/{r.requests} ok, "
                      f"c={r.concurrency}, {r.wall_s}s)")
        console.print(f"  tokens/sec:  {r.tokens_per_sec}")
        console.print(f"  TTFT  p50/p95/p99:  {r.ttft_p50} / {r.ttft_p95} / {r.ttft_p99} s")
        console.print(f"  Latenz p50/p95/p99: {r.latency_p50} / {r.latency_p95} / {r.latency_p99} s")
        for n in r.notes:
            console.print(f"  [yellow]· {n}[/yellow]")


def _read_endpoint(output: Path, base_url: Optional[str], api_key: Optional[str]):
    """Derive base_url + api_key from a generated .env when not given explicitly."""
    env_file = output / ".env"
    vals: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    api_key = api_key or vals.get("LITELLM_MASTER_KEY")
    if base_url is None:
        domain = vals.get("API_DOMAIN")
        base_url = f"https://{domain}" if domain else "http://127.0.0.1:4000"
    return base_url, api_key


# --------------------------------------------------------------------------- interactive helpers

def _confirm(message: str, default: bool = True) -> bool:
    try:
        import questionary
        return bool(questionary.confirm(message, default=default).ask())
    except Exception:
        return default


# --------------------------------------------------------------------------- output helpers

def _print_next_steps(cfg, output: Path) -> None:
    console.rule("[bold]Nächste Schritte")
    console.print(f"  cd {output}")
    console.print("  docker compose pull")
    console.print("  docker compose up -d")
    console.print("  ../scripts/healthcheck.sh")
    if cfg.uses_traefik:
        console.print("\n[yellow]Hinweis:[/yellow] Setze Domains + ACME_EMAIL in der .env, "
                      "bevor du startest (TLS).")
    console.print("\n[dim]API-Keys & Passwörter stehen in der generierten .env "
                  "(nicht eingecheckt).[/dim]")


def _docker_up(output: Path) -> None:
    console.print("\n[cyan]Starte Stack…[/cyan]")
    try:
        subprocess.run(["docker", "compose", "pull"], cwd=output, check=True)
        subprocess.run(["docker", "compose", "up", "-d"], cwd=output, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]Start fehlgeschlagen:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print("[green]Stack gestartet.[/green]")


if __name__ == "__main__":
    app()
