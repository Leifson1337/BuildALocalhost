# Plugins

Plugins extend the data-driven catalogs **without modifying core code**. Drop a directory
here with a `plugin.yaml` manifest; the installer discovers it automatically
(`installer/plugins.py`) and merges its contributions into the relevant catalogs.

## Manifest schema

```yaml
name: my-custom-engine          # unique plugin name
type: inference_engine          # inference_engine | webui | mcp_server (informational)
enabled: true                   # false => ignored
requires:                       # advisory (not enforced yet)
  - nvidia_gpu
  - docker
provides:
  engines:                      # merged into catalogs/serving_engines.yaml -> engines
    - id: my-engine
      name: My Engine
      api: openai-compatible
      image: registry/my-engine:1.0
      default_port: 8000
      gpu: required
  webuis:                       # merged into catalogs/webuis.yaml -> webuis
    - id: my-ui
      name: My UI
      image: registry/my-ui:1.0
      internal_port: 3000
  mcp_servers:                  # merged into catalogs/mcp_servers.yaml -> servers
    - id: my-mcp
      tier: advanced
      package: "@scope/my-mcp"
```

Entries are deduplicated by `id` (a plugin cannot override a built-in id). A malformed or
disabled plugin is skipped with a note, never a crash.

## Planned extension points (Stage 3+)

The current loader handles `engines`, `webuis`, and `mcp_servers`. Future kinds:
`model_sources`, `vector_dbs`, `auth_providers`, `monitoring`, `deployment_targets`.

See `installer/plugins.py` for the authoritative behaviour.
