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
    import yaml
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
        # Throughput-optimal on 8xH100 with a 7B model: tp=1 + 8 data-parallel replicas.
        doc = yaml.safe_load(text)
        repl = [s for s in doc["services"] if s.startswith("inference-main-chat-")]
        assert len(repl) == 8, repl
        envtext = env.read_text(encoding="utf-8")
        assert "LITELLM_MASTER_KEY=sk-" in envtext
        assert "TENSOR_PARALLEL_SIZE=1" in envtext
        assert "MAX_NUM_SEQS=" in envtext and "KV_CACHE_DTYPE=fp8" in envtext


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


def test_skills_loader_discovers_agent_and_mcp():
    from installer import skills
    d = skills.discover()
    agent_names = [s["name"] for s in d["agent"]]
    assert "web-research" in agent_names and "code-review" in agent_names
    mcp_ids = [s["id"] for s in d["mcp_servers"]]
    assert "jira-mcp" in mcp_ids


def test_agent_skills_rendered_in_profile():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "agents_mcp")
    cfg = profile_builder.build(profile_name="agents_mcp", system=system,
                                recommendation=rec, goal="agents_mcp")
    assert [s["name"] for s in cfg.agent_skills] == ["web-research", "code-review"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        sk = (out / "configs" / "skills" / "skills.yaml")
        assert sk.exists()
        data = yaml.safe_load(sk.read_text(encoding="utf-8"))
        assert [s["name"] for s in data["skills"]] == ["web-research", "code-review"]


def test_mcp_skill_enables_gateway_and_policy():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "agents_mcp")
    # Start from a profile with MCP off; enabling an mcp skill must turn it on.
    cfg = profile_builder.build(profile_name="production", system=system, recommendation=rec,
                                goal="agents_mcp", overrides={"skills": ["jira-tool"]})
    assert cfg.mcp_enabled
    assert "jira-mcp" in cfg.data["mcp"]["servers"]
    issues = validators.validate(cfg, check_ports=False)
    assert not validators.has_fatal(issues)        # advanced tier, allowed
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        pol = yaml.safe_load((out / "configs" / "mcp" / "policies.yaml").read_text(encoding="utf-8"))
        assert any(s["id"] == "jira-mcp" for s in pol["servers"])


def test_custom_endpoints_into_litellm():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(
        profile_name="production", system=system, recommendation=rec, goal="high_throughput_chat",
        overrides={"endpoints": [
            {"name": "gpt4o", "preset": "openai", "model": "gpt-4o"},
            {"name": "myllm", "api_base": "https://host/v1", "model": "m", "api_key_env": "MY_KEY"},
        ]},
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        lc = yaml.safe_load((out / "configs" / "litellm" / "config.yaml").read_text(encoding="utf-8"))
        names = [m["model_name"] for m in lc["model_list"]]
        assert "gpt4o" in names and "myllm" in names
        gpt = next(m for m in lc["model_list"] if m["model_name"] == "gpt4o")
        assert gpt["litellm_params"]["model"] == "openai/gpt-4o"
        assert gpt["litellm_params"]["api_key"] == "os.environ/OPENAI_API_KEY"
        env = (out / ".env").read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=" in env and "MY_KEY=" in env


def test_rag_efficient_leann_turboquant():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "rag")
    cfg = profile_builder.build(profile_name="rag_efficient", system=system,
                                recommendation=rec, goal="rag")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        assert "vectordb" in doc["services"]
        assert "LEANN_IMAGE" in doc["services"]["vectordb"]["image"]   # overridable image
        ragcfg = yaml.safe_load((out / "configs" / "rag" / "config.yaml").read_text(encoding="utf-8"))
        assert ragcfg["vector_db"] == "leann"
        assert ragcfg["vector_quantization"] == "turboquant"
        assert ragcfg["retrieval"]["hybrid_search"] is True
        # validator flags external method (non-fatal)
        issues = validators.validate(cfg, check_ports=False)
        assert any(i.code == "rag.verify_image" for i in issues)
        assert not validators.has_fatal(issues)


def test_tuning_maximizes_replicas():
    from installer import tuning
    system = build_simulation("8xH100")
    t = tuning.optimize(system, goal="many_users", model_vram_gb=18, optimize_for="throughput")
    assert t.tensor_parallel_size == 1          # 7B fits one H100
    assert t.data_parallel_replicas == 8        # one replica per GPU => max concurrency
    assert t.kv_cache_dtype == "fp8"            # Hopper => fp8 KV cache


def test_tuning_big_model_tensor_parallel():
    from installer import tuning
    system = build_simulation("8xH100")          # 640 GB
    t = tuning.optimize(system, goal="highest_quality", model_vram_gb=160, optimize_for="balanced")
    assert t.tensor_parallel_size == 8 and t.data_parallel_replicas == 1


def test_replicas_get_distinct_gpu_ids():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "many_users")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="many_users", optimize_for="throughput")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        repl = {k: v for k, v in doc["services"].items() if k.startswith("inference-main-chat-")}
        assert len(repl) == 8
        seen = set()
        for v in repl.values():
            ids = v["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"]
            assert len(ids) == 1
            seen.add(ids[0])
        assert len(seen) == 8                    # each replica pinned to a distinct GPU


def test_routing_multi_model():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="routing", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        svcs = doc["services"]
        for name in ("inference-fast-chat", "inference-main-chat", "inference-code"):
            assert name in svcs, f"missing {name}"
        litellm = (out / "configs" / "litellm" / "config.yaml").read_text(encoding="utf-8")
        for mn in ("fast-chat", "main-chat", "code"):
            assert f"model_name: {mn}" in litellm
        env = (out / ".env").read_text(encoding="utf-8")
        assert "MODEL_FAST_CHAT=" in env and "MODEL_CODE=" in env


def test_single_model_backward_compatible():
    # Single GPU => one replica => unsuffixed service name (backward compatible).
    system = build_simulation("1xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    import yaml
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        assert "inference-main-chat" in doc["services"]


def test_k8s_export_multidoc_valid():
    import yaml
    from installer import k8s_renderer
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="routing", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        k8s_renderer.render(cfg, out)
        manifests = out / "k8s" / "manifests.yaml"
        assert manifests.exists()
        docs = list(yaml.safe_load_all(manifests.read_text(encoding="utf-8")))
        kinds = [d.get("kind") for d in docs if d]
        assert "Namespace" in kinds and "Ingress" in kinds
        deploy_names = [d["metadata"]["name"] for d in docs
                        if d and d.get("kind") == "Deployment"]
        for n in ("inference-fast-chat", "inference-main-chat", "inference-code", "litellm"):
            assert n in deploy_names, f"missing deployment {n}"
        # GPU resource present on an inference deployment.
        text = manifests.read_text(encoding="utf-8")
        assert "nvidia.com/gpu" in text
        # Helm chart files exist.
        assert (out / "k8s" / "helm" / "routing" / "Chart.yaml").exists()
        assert (out / "k8s" / "helm" / "routing" / "values.yaml").exists()


def test_k8s_rocm_resource_key():
    from installer import k8s_renderer
    system = build_simulation("8xMI300X")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        k8s_renderer.render(cfg, out)
        text = (out / "k8s" / "manifests.yaml").read_text(encoding="utf-8")
        assert "amd.com/gpu" in text and "nvidia.com/gpu" not in text


def test_plugin_loader_skips_disabled():
    from installer import plugins
    d = plugins.discover()
    assert {"engines", "webuis", "mcp_servers", "vector_dbs", "auth_providers"} <= set(d.keys())
    # The shipped example plugin is disabled => must not appear.
    assert "aphrodite" not in [e["id"] for e in d["engines"]]


def test_plugin_extension_points_present():
    from installer import plugins
    d = plugins.discover()
    for kind in ("engines", "webuis", "mcp_servers", "vector_dbs", "auth_providers",
                 "model_sources", "monitoring", "deployment_targets"):
        assert kind in d


def test_plugin_monitoring_targets_render():
    # The prometheus template must emit plugin-contributed scrape targets.
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from installer import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    out = env.get_template("prometheus.yml.j2").render(
        profile_name="x", plugin_scrape_targets=[{"name": "myexp", "target": "myexp:9100"}])
    assert "myexp" in out and "myexp:9100" in out


def test_catalog_merge_is_safe_without_plugins():
    from installer import catalog
    engines = [e["id"] for e in catalog.load_engines().get("engines", [])]
    assert "vllm" in engines  # built-ins still present after plugin merge


def test_capacity_estimate_h100():
    from installer import capacity
    system = build_simulation("4xH100")        # 320 GB VRAM
    est = capacity.estimate(system, "Qwen/Qwen2.5-7B-Instruct",
                            capacity.Workload(concurrent_users=10))
    assert est.max_concurrent_requests > 10
    assert est.meets_target
    assert est.throughput_class in ("high", "medium")


def test_capacity_infeasible_small_gpu():
    from installer import capacity
    system = build_simulation("1xRTX4090")      # 24 GB
    est = capacity.estimate(system, "Qwen/Qwen2.5-72B-Instruct",
                            capacity.Workload(concurrent_users=50))
    assert est.throughput_class == "infeasible"
    assert not est.meets_target


def test_benchmark_percentiles_pure():
    from installer.benchmark import percentiles
    vals = [float(i) for i in range(1, 101)]    # 1..100
    p = percentiles(vals)
    assert p[50] <= p[95] <= p[99]
    assert percentiles([]) == {50: 0.0, 95: 0.0, 99: 0.0}


def test_multi_tenant_policy_render():
    import yaml
    from installer import policy as policy_mod
    system = build_simulation("8xH100")
    rec = recommend(system, "agents_mcp")
    cfg = profile_builder.build(profile_name="multi_tenant", system=system,
                                recommendation=rec, goal="agents_mcp")
    assert cfg.tenancy_enabled and cfg.policy_enabled
    pol = policy_mod.build_policy(cfg)
    ids = [t["id"] for t in pol["tenants"]]
    assert ids == ["team-research", "team-support", "svc-integrations"]
    # api_only role expands to main-chat only.
    svc = next(t for t in pol["tenants"] if t["id"] == "svc-integrations")
    assert svc["allow_models"] == ["main-chat"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        polfile = out / "configs" / "policy" / "policy.yaml"
        assert polfile.exists()
        loaded = yaml.safe_load(polfile.read_text(encoding="utf-8"))
        assert loaded["multi_tenant"] is True
        assert len(loaded["tenants"]) == 3


def test_policy_rejects_unknown_role():
    system = build_simulation("4xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(
        profile_name="multi_tenant", system=system, recommendation=rec, goal="high_throughput_chat",
        overrides={"tenancy": {"enabled": True,
                               "tenants": [{"id": "bad", "roles": ["does_not_exist"]}]}},
    )
    issues = validators.validate(cfg, check_ports=False)
    assert any(i.code == "policy.tenant" and i.severity == "fatal" for i in issues)


def test_policy_emitted_for_public_secure_without_tenancy():
    system = build_simulation("4xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    assert cfg.policy_enabled and not cfg.tenancy_enabled
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        assert (out / "configs" / "policy" / "policy.yaml").exists()


def test_supply_chain_classify_pin():
    from installer.supply_chain import classify_pin
    assert classify_pin("postgres:16") == "version"
    assert classify_pin("vllm/vllm-openai:v0.6.6") == "version"
    assert classify_pin("ghcr.io/open-webui/open-webui:main") == "mutable"
    assert classify_pin("redis") == "mutable"            # no tag => latest
    assert classify_pin("nginx@sha256:abc123") == "digest"
    assert classify_pin("registry:5000/app:1.2.3") == "version"


def test_supply_chain_pin_compose():
    import yaml
    from installer import supply_chain
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        compose = out / "docker-compose.yml"
        digest_map = {"postgres:16": "sha256:" + "a" * 64}
        pinned = supply_chain.pin_compose(compose, digest_map)
        data = yaml.safe_load(pinned)
        imgs = [s.get("image") for s in data["services"].values()]
        assert any(i and i.startswith("postgres@sha256:") for i in imgs)
        # untouched images keep their tag
        assert any(i == "redis:7" for i in imgs)


def test_supply_chain_audit_on_rendered():
    from installer import supply_chain
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="production", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        report = supply_chain.audit(out / "docker-compose.yml")
        assert report["images"]
        # open-webui:main + litellm:main-stable are mutable in the catalog.
        assert any("open-webui" in m for m in report["mutable"])


def test_eval_scoring_pure():
    from installer.evaluate import score, summarize, CaseResult
    assert score({"type": "contains", "value": "Hallo"}, "Sage Hallo Welt")
    assert score({"type": "equals", "value": "4"}, "  4 ")
    assert score({"type": "regex", "value": r"\b4\b"}, "Antwort: 4.")
    assert score({"type": "not_contains", "value": "ERROR"}, "alles gut")
    assert not score({"type": "contains", "value": "x"}, "y")
    assert not score({"type": "unknown"}, "anything")   # fail closed
    rep = summarize([CaseResult("a", True, 0.1), CaseResult("b", False, 0.3)])
    assert rep.total == 2 and rep.passed == 1 and rep.pass_rate == 0.5


def test_langfuse_rendered_in_enterprise():
    import yaml
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="enterprise", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        assert "langfuse" in doc["services"]
        env = (out / ".env").read_text(encoding="utf-8")
        assert "LANGFUSE_NEXTAUTH_SECRET=" in env


def test_k8s_parity_enterprise():
    import yaml
    from installer import k8s_renderer
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="enterprise", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        k8s_renderer.render(cfg, out)
        docs = list(yaml.safe_load_all((out / "k8s" / "manifests.yaml").read_text(encoding="utf-8")))
        names = {(d.get("kind"), d["metadata"]["name"]) for d in docs if d}
        for n in ("vectordb", "embeddings", "reranker"):
            assert ("Deployment", n) in names, f"missing RAG {n}"
        assert ("Deployment", "mcp-gateway") in names
        assert ("Deployment", "prometheus") in names
        assert ("DaemonSet", "dcgm-exporter") in names


def test_k8s_auth_parity():
    import yaml
    from installer import k8s_renderer
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    # enterprise uses Authentik.
    cfg = profile_builder.build(profile_name="enterprise", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        k8s_renderer.render(cfg, out)
        text = (out / "k8s" / "manifests.yaml").read_text(encoding="utf-8")
        docs = [d for d in yaml.safe_load_all(text) if d]
        deploys = {d["metadata"]["name"] for d in docs if d.get("kind") == "Deployment"}
        assert {"authentik-server", "authentik-worker"} <= deploys
        assert "AUTHENTIK_SECRET_KEY" in text
    # Keycloak via override.
    cfg2 = profile_builder.build(profile_name="production", system=system, recommendation=rec,
                                 goal="high_throughput_chat", overrides={"web": {"auth": "keycloak"}})
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg2, out)
        k8s_renderer.render(cfg2, out)
        docs = [d for d in yaml.safe_load_all((out / "k8s" / "manifests.yaml").read_text(encoding="utf-8")) if d]
        deploys = {d["metadata"]["name"] for d in docs if d.get("kind") == "Deployment"}
        assert "keycloak" in deploys


def test_mig_capability_detected_h100():
    system = build_simulation("8xH100")
    assert system.mig_capable is True
    assert system.mig_active is False        # simulation never enables MIG
    rec = recommend(system, "high_throughput_chat")
    assert any("MIG-capable" in w for w in rec.warnings)


def test_k8s_node_selector_and_nccl():
    import yaml
    from installer import k8s_renderer
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    cfg = profile_builder.build(profile_name="multi_h100", system=system,
                                recommendation=rec, goal="high_throughput_chat")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        k8s_renderer.render(cfg, out)
        manifests = (out / "k8s" / "manifests.yaml").read_text(encoding="utf-8")
        assert "nvidia.com/gpu.present" in manifests
        assert "tolerations" in manifests
        nccl = out / "k8s" / "nccl-test.yaml"
        assert nccl.exists()
        doc = yaml.safe_load(nccl.read_text(encoding="utf-8"))
        assert doc["kind"] == "Job"


def test_triton_engines_selectable():
    import yaml
    from installer import catalog
    ids = [e["id"] for e in catalog.load_engines()["engines"]]
    assert "triton_vllm" in ids and "triton_tensorrt_llm" in ids
    system = build_simulation("8xH100")
    rec = recommend(system, "high_throughput_chat")
    # safetensors model on Triton+TRT-LLM (cuda) renders; model-repo note is info, not fatal.
    cfg = profile_builder.build(profile_name="production", system=system, recommendation=rec,
                                goal="high_throughput_chat",
                                overrides={"inference": {"engine": "triton_tensorrt_llm"}})
    issues = validators.validate(cfg, check_ports=False)
    assert any(i.code == "engine.model_repository" for i in issues)
    assert not validators.has_fatal(issues)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o"
        compose_renderer.render(cfg, out)
        doc = yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
        svc = next(k for k in doc["services"] if k.startswith("inference-main-chat"))
        assert "tritonserver" in doc["services"][svc]["command"]


def test_compatibility_matrix_sweep():
    """Sweep engine x model-format x runtime; the validator's verdict must match the matrix,
    and every non-fatal combination must render valid compose YAML."""
    import yaml
    from installer import catalog
    engines = [e["id"] for e in catalog.load_engines()["engines"]]
    # One representative model per inferred kind.
    models = {
        "safetensors_default": "Qwen/Qwen2.5-7B-Instruct",
        "gguf": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "awq": "some-org/Qwen2.5-7B-Instruct-AWQ",
        "gptq": "some-org/Qwen2.5-7B-Instruct-GPTQ",
    }
    compat = catalog.load_compatibility()["engine_format_support"]
    checked = 0
    for sim, runtime in (("8xH100", "cuda"), ("8xMI300X", "rocm")):
        system = build_simulation(sim)
        rec = recommend(system, "high_throughput_chat")
        for eid in engines:
            support = compat.get(eid, {})
            for kind, model_id in models.items():
                cfg = profile_builder.build(
                    profile_name="minimal", system=system, recommendation=rec,
                    model=model_id, goal="high_throughput_chat",
                    overrides={"inference": {"engine": eid}},
                )
                issues = validators.validate(cfg, check_ports=False)
                codes = {i.code for i in issues if i.severity == "fatal"}
                fmt_bad = kind in (support.get("not") or [])
                rt_bad = runtime not in (support.get("runtimes") or ["cuda"])
                # Validator must flag incompatible format/runtime as fatal.
                if fmt_bad:
                    assert "compat.format" in codes, f"{eid}/{kind}/{runtime} should fail format"
                if rt_bad and runtime == "rocm":
                    assert "compat.runtime" in codes, f"{eid}/{runtime} should fail runtime"
                # Compatible combos must render valid YAML.
                if not fmt_bad and not rt_bad:
                    assert not validators.has_fatal(issues), \
                        f"{eid}/{kind}/{runtime} unexpectedly fatal: {codes}"
                    with tempfile.TemporaryDirectory() as tmp:
                        out = Path(tmp) / "o"
                        compose_renderer.render(cfg, out)
                        yaml.safe_load((out / "docker-compose.yml").read_text(encoding="utf-8"))
                checked += 1
    assert checked == len(engines) * len(models) * 2


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
