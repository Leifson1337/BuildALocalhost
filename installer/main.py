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
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Ohne Rückfragen."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Nur generieren, nicht starten."),
    no_validate: bool = typer.Option(False, "--no-validate", help="Validierung überspringen."),
    start: bool = typer.Option(False, "--start", help="Nach dem Rendern `docker compose up -d`."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (e.g. `list-profiles`) was requested

    console.print("[bold]Universal AI Stack Builder[/bold] — Stufe 1\n")

    # 1) Hardware: simulate or auto-detect
    if simulate:
        from installer.hardware import build_simulation
        system = build_simulation(simulate)
        console.print(f"[cyan]Simulationsmodus:[/cyan] {simulate}")
    else:
        console.print("[cyan]Erkenne Hardware…[/cyan]")
        system = detect_gpus.detect_system()
        if not system.has_gpu and not non_interactive:
            console.print(
                "[yellow]Keine GPU erkannt.[/yellow] Du kannst mit "
                '[bold]--simulate "8xH100"[/bold] eine Konfiguration als Vorschau erzeugen.'
            )

    # 2) Profile + goal selection (interactive unless suppressed)
    if not non_interactive and not simulate:
        profile = _select_profile(profile)
        goal = _select_goal(goal)

    # 3) Recommendation
    rec = recommend(system, goal)

    # 4) Resolve config
    cfg = profile_builder.build(
        profile_name=profile, system=system, recommendation=rec, model=model, goal=goal
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


# --------------------------------------------------------------------------- interactive helpers

def _select_profile(default: str) -> str:
    try:
        import questionary
    except Exception:
        return default
    choices = catalog.available_profiles()
    answer = questionary.select(
        "Welches Profil möchtest du installieren?",
        choices=choices,
        default=default if default in choices else choices[0],
    ).ask()
    return answer or default


def _select_goal(default: str) -> str:
    try:
        import questionary
    except Exception:
        return default
    from installer.recommend import GOALS
    choices = sorted(GOALS)
    answer = questionary.select(
        "Was ist das Hauptziel?",
        choices=choices,
        default=default if default in choices else "high_throughput_chat",
    ).ask()
    return answer or default


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
