"""Smoke tests for the Stage 1 pipeline.

Runs the full pure path (simulate -> recommend -> build -> validate -> render) without a GPU
or Docker. Executable directly (`python tests/test_smoke.py`) or via pytest.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer import compose_renderer, profile_builder, validators  # noqa: E402
from installer.hardware import build_simulation  # noqa: E402
from installer.recommend import recommend  # noqa: E402


def _pipeline(profile: str, sim: str, goal: str):
    system = build_simulation(sim)
    rec = recommend(system, goal)
    cfg = profile_builder.build(profile_name=profile, system=system, recommendation=rec, goal=goal)
    issues = validators.validate(cfg, check_ports=False)
    return system, rec, cfg, issues


def test_simulation_parses_count_and_model():
    system = build_simulation("8xH100")
    assert system.total_gpu_count == 8
    assert system.total_vram_gb == 640.0
    assert system.primary_gpu.model.lower().startswith("h100")


def test_recommend_h100_uses_tensor_parallel():
    system = build_simulation("4xH100")
    rec = recommend(system, "high_throughput_chat")
    assert rec.primary_engine == "vllm"
    assert rec.tensor_parallel_size == 4   # nvswitch default for H100 SXM
    assert rec.runtime == "docker_compose"


def test_recommend_consumer_low_vram_warns():
    system = build_simulation("1xRTX4090")
    rec = recommend(system, "development")
    assert any("VRAM" in w for w in rec.warnings)


def test_production_render_writes_files():
    _, _, cfg, issues = _pipeline("production", "8xH100", "high_throughput_chat")
    assert not validators.has_fatal(issues), [i.message for i in issues if i.severity == "fatal"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        written = compose_renderer.render(cfg, out)
        compose = out / "docker-compose.yml"
        env = out / ".env"
        assert compose.exists() and env.exists()
        text = compose.read_text(encoding="utf-8")
        assert "litellm" in text and "inference" in text
        assert "dcgm-exporter" in text          # monitoring on for production
        assert "traefik" in text                # reverse proxy on
        envtext = env.read_text(encoding="utf-8")
        assert "LITELLM_MASTER_KEY=sk-" in envtext
        assert "TENSOR_PARALLEL_SIZE=8" in envtext


def test_minimal_render_no_traefik_no_monitoring():
    _, _, cfg, _ = _pipeline("minimal", "1xRTX4090", "development")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        compose_renderer.render(cfg, out)
        text = (out / "docker-compose.yml").read_text(encoding="utf-8")
        assert "traefik" not in text
        assert "dcgm-exporter" not in text
        assert "127.0.0.1:" in text             # localhost-bound port mapping


def test_vram_insufficient_is_fatal():
    # 72B model needs ~160GB; a single 24GB GPU must fail validation.
    system = build_simulation("1xRTX4090")
    rec = recommend(system, "highest_quality")
    cfg = profile_builder.build(
        profile_name="minimal", system=system, recommendation=rec,
        model="Qwen/Qwen2.5-72B-Instruct", goal="highest_quality",
    )
    issues = validators.validate(cfg, check_ports=False)
    assert validators.has_fatal(issues)
    assert any(i.code == "vram.insufficient" for i in issues)


def test_all_profiles_render_cuda_and_rocm():
    import yaml
    from installer import catalog
    for profile in catalog.available_profiles():
        for sim in ("8xH100", "8xMI300X"):
            system = build_simulation(sim)
            rec = recommend(system, "high_throughput_chat")
            cfg = profile_builder.build(profile_name=profile, system=system,
                                        recommendation=rec, goal="high_throughput_chat")
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "o"
                compose_renderer.render(cfg, out)
                doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
                assert "services" in doc and doc["services"], f"{profile}/{sim} empty"


def test_amd_runtime_and_image():
    system = build_simulation("8xMI300X")
    assert system.runtime_kind == "rocm"
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    ctx = compose_renderer.build_context(cfg)
    assert "rocm" in ctx["engine_image"].lower()
    # No DCGM exporter on ROCm.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        text = (out / "docker-compose.yml").read_text(encoding="utf-8")
        assert "dcgm-exporter" not in text
        assert "/dev/kfd" in text


def test_gguf_on_vllm_is_fatal():
    system = build_simulation("1xRTX4090")
    rec = recommend(system, "development")
    cfg = profile_builder.build(profile_name="minimal", system=system, recommendation=rec,
                                model="bartowski/Qwen2.5-7B-Instruct-GGUF", goal="development")
    issues = validators.validate(cfg, check_ports=False)
    assert any(i.code == "compat.format" and i.severity == "fatal" for i in issues)


def test_dangerous_mcp_fatal_on_public():
    system = build_simulation("8xH100")
    rec = recommend(system, "agents_mcp")
    cfg = profile_builder.build(
        profile_name="agents_mcp", system=system, recommendation=rec, goal="agents_mcp",
        overrides={"mcp": {"enabled": True, "servers": ["shell-full"]}},
    )
    issues = validators.validate(cfg, check_ports=False)
    assert any(i.code == "mcp.dangerous" and i.severity == "fatal" for i in issues)


def test_socket_proxy_replaces_raw_socket():
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        text = (out / "docker-compose.yml").read_text(encoding="utf-8")
        # public_secure profile enables docker_socket_proxy.
        assert "docker-socket-proxy" in text


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
