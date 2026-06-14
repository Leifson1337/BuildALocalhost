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
  vector_dbs:                   # merged into catalogs/rag.yaml -> vector_dbs
    - id: my-vdb
      name: My Vector DB
      image: registry/my-vdb:1.0
      internal_port: 6333
      volume: my_vdb_data
  auth_providers:               # merged into catalogs/auth.yaml -> providers
    - id: my-idp
      name: My IdP
      service: true
      image: registry/my-idp:1.0
      internal_port: 9000
      forward_auth: true
```

Entries are deduplicated by `id` (a plugin cannot override a built-in id). A malformed or
disabled plugin is skipped with a note, never a crash.

## Extension points

The loader handles all of: `engines`, `webuis`, `mcp_servers`, `vector_dbs`, `auth_providers`,
`model_sources`, `monitoring`, `deployment_targets`.

- `model_sources` → extra entries in the wizard's "Modellquelle" menu
  (`[{id, name}]`; chosen → prompts for a model id/path).
- `monitoring` → extra Prometheus scrape targets (`[{name, target}]`, e.g. `target: myexp:9100`).
- `deployment_targets` → discovered and listed (`list-plugins`) for custom renderers.

List everything discovered with `python -m installer list-plugins`.

See `installer/plugins.py` for the authoritative behaviour.
