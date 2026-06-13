# Skills

Skills add capabilities to the stack. Drop a directory here with a `skill.yaml` manifest;
the installer discovers it (`installer/skills.py`). Two types:

- **agent** — a capability surfaced to the UI/agent layer (name, description, `instructions`
  system prompt, optional `uses` = MCP servers it relies on). Rendered into
  `configs/skills/skills.yaml` and a combined system addendum.
- **mcp** — wraps an MCP tool server (`server.id/package/tier/allowed_tools/...`). Merged into
  the MCP gateway as a **deny-by-default** server.

Enable skills per deployment via a profile field or the wizard:

```yaml
skills: [web-research, code-review, jira-tool]
```

- agent skills → added to the assistant's system prompt / UI capabilities.
- mcp skills → the MCP gateway is enabled and the skill's server is added to its policy.

## Manifest schema

```yaml
name: my-skill
type: agent          # agent | mcp
enabled: true
description: "..."
# agent:
instructions: |
  System-prompt / capability instructions.
uses: [web-search-proxy]
# mcp:
server:
  id: my-tool
  tier: advanced     # safe_default | advanced | dangerous_requires_confirmation
  package: "@scope/mcp-server-x"
  allowed_tools: [a, b]
  denied_tools: [c]
  require_confirmation: [write, external_http]
```

Disabled or malformed skills are skipped with a note, never a crash. MCP skills inherit all
gateway protections (deny-by-default, tier gating, audit, confirmation).
