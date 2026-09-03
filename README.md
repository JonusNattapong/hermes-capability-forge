# Hermes Capability Forge

Continuous capability engineering for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

Instead of installing more tools for the sake of having more tools, Capability Forge watches real work for repeated friction, performs bounded research, chooses the smallest useful extension surface, verifies it, then dogfoods it on the task that justified building it.

## V0.1

This repository contains two cooperating components:

1. **`capability-forge` Skill** — the decision and engineering loop for deciding whether to reuse, patch, or build a Skill, helper script, Hermes Plugin/Tool, or MCP server.
2. **`capability-observer` Plugin** — a privacy-preserving `post_tool_call` observer that records only operational telemetry needed to evaluate real usage.

Hermes Curator remains responsible for its normal profile-local skill maintenance. Forge-created Git skills are intentionally versioned here and are not assumed to be auto-curated by Hermes.

## Architecture

```text
                    NORMAL HERMES WORK
                           |
                           v
                  +------------------+
                  | Capability Forge |
                  |   "what helps?"  |
                  +--------+---------+
                           |
              +------------+-------------+
              |            |             |
              v            v             v
            Skill        Plugin          MCP
          procedure    native logic   external API
              |            |             |
              +------------+-------------+
                           v
                      Verify/Test
                           |
                           v
                        Dogfood
                           |
                           v
                 Capability Observer
                           |
                           v
                ~/.hermes/capability-lab/
                      events.jsonl
                           |
                           v
                 evidence for patches
```

Core loop:

```text
OBSERVE -> RESEARCH -> DECIDE -> BUILD -> VERIFY -> DOGFOOD -> LEARN -> IMPROVE
```

## Decision rule

| Situation | Extension surface |
| --- | --- |
| Procedure, knowledge, repeatable workflow | Skill |
| Existing CLI works but commands are fragile/long | Skill + script |
| Precise deterministic logic | Hermes Plugin / Tool |
| Hermes lifecycle integration | Hermes Plugin |
| External API/service with several operations | MCP |
| Reusable across multiple agents/clients | MCP |
| Repo-specific workflow | Project-local Skill |
| Short durable preference/path/fact | Memory |
| One-off task | Build nothing |

The default is **reuse first, Skill second, code only when justified**.

## Install

Requires a current Hermes Agent version with plugin hooks and GitHub skill installs.

### 1. Install the observer plugin

```bash
hermes plugins install JonusNattapong/hermes-capability-forge --enable
```

The plugin registers no model-visible tools. It only subscribes to `post_tool_call`, so it does not inflate the normal tool schema.

### 2. Install the Forge skill

Direct GitHub install:

```bash
hermes skills install JonusNattapong/hermes-capability-forge/skills/capability-forge
```

Or subscribe to this repository as a skills tap:

```bash
hermes skills tap add JonusNattapong/hermes-capability-forge
hermes skills search capability-forge --source JonusNattapong/hermes-capability-forge
```

### 3. Optional: make new Forge skills Git-tracked

Clone this repo somewhere permanent and set:

```bash
export CAPABILITY_FORGE_HOME=/absolute/path/to/hermes-capability-forge
```

PowerShell:

```powershell
$env:CAPABILITY_FORGE_HOME = "D:\Projects\Github\hermes-capability-forge"
```

Merge the relevant sections from [`config/hermes.example.yaml`](config/hermes.example.yaml) into `~/.hermes/config.yaml`.

The example enables:

- `skills.create_dir: ${CAPABILITY_FORGE_HOME}/skills`
- `skills.guard_agent_created: true`
- `skills.write_approval: true`
- `capability-observer`
- Curator weekly/prune-only mode

Keep `write_approval: true` initially so agent-created/modified skills are staged for review instead of silently landing.

## Recommended builder capabilities

Capability Forge should reuse Hermes-native skills instead of reinventing MCP development helpers:

```bash
hermes skills install official/mcp/fastmcp
hermes skills install official/mcp/mcporter
```

Use FastMCP when building a Python MCP server and mcporter when inspecting/calling an existing MCP server from the terminal.

## Telemetry and privacy

Observer writes to:

```text
~/.hermes/capability-lab/events.jsonl
```

Each event may contain:

```json
{
  "schema_version": 1,
  "timestamp": "2026-09-03T04:00:00Z",
  "event": "tool_call",
  "tool": "terminal",
  "status": "success",
  "duration_ms": 42,
  "task_hash": "4b98...",
  "session_hash": "c314..."
}
```

Observer deliberately does **not** persist:

- prompts or user messages
- tool arguments
- tool results
- commands
- file contents
- URLs
- credentials/secrets
- raw task/session/turn IDs

Telemetry failure is fail-open: normal Hermes work continues even if Observer cannot write an event.

## Dogfood policy

Do not stop after an isolated test.

```text
research
  -> build v0
  -> isolated test
  -> resume the original real task
  -> use v0 normally
  -> observe evidence
  -> targeted patch
  -> continue work
```

A capability that is worse than the previous workflow should be reverted or disabled.

## Curator note

Hermes Curator has useful built-in usage telemetry, stale/archive transitions, backup and optional LLM consolidation. Keep `consolidate: false` initially and preview with:

```bash
hermes curator run --dry-run
```

Current Hermes behavior matters here: Curator's automatic management is scoped to skills it considers agent-created in the profile-local library, while hub-installed/external Git skills are not simply swept into the same lifecycle. This repo therefore treats Git history + Observer evidence as the source of truth for Forge-managed capabilities. A dedicated evidence-driven maintainer belongs in **V0.2**, after real telemetry exists.

## Development

No third-party Python runtime dependency is required by Observer.

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Roadmap

### V0.1

- [x] Capability Forge Skill
- [x] Privacy-preserving Observer plugin
- [x] Git-tracked skill layout
- [x] Safe example config
- [x] Tests
- [x] FastMCP/mcporter reuse guidance

### V0.2, only after telemetry exists

- [ ] Evidence summarizer
- [ ] Repeated-friction detector
- [ ] Weekly capability maintainer
- [ ] Patch proposals from real failures/latency/retries
- [ ] Lightweight eval cases for promoted capabilities
- [ ] Upstream drift checks only for active capabilities

### Explicitly not in V0.1

- autonomous internet-wide dependency scanning
- auto-merging or auto-deleting skills
- recording prompts/results for analytics
- modifying Hermes core
- creating MCP wrappers for trivial CLI operations

## Philosophy

**Real work is the benchmark.**

Research informs implementation. Tests establish a baseline. Dogfooding discovers reality. Usage evidence decides what survives.

## License

MIT
