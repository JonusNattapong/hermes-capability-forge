# Hermes Capability Forge

Continuous capability engineering for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

Instead of installing more tools for the sake of having more tools, Capability Forge watches real work for repeated friction, performs bounded research, chooses the smallest useful extension surface, verifies it, then dogfoods it on the task that justified building it.

## V0.2

This repository contains three cooperating components:

1. **`capability-forge` Skill** — the decision and engineering loop for deciding whether to reuse, patch, or build a Skill, helper script, Hermes Plugin/Tool, or MCP server.
2. **`capability-observer` Plugin** — a privacy-preserving `post_tool_call` observer that records only operational telemetry needed to evaluate real usage and exposes the deterministic `capability_forge_report` tool.
3. **`capability-maintainer` Skill / Blueprint** — a weekly, proposal-first review that triages evidence, researches only justified candidates, and hands approved changes back to Forge for dogfooding.

Hermes Curator remains responsible for its normal skill lifecycle. Forge adds cross-surface evidence for Skills, Plugin/Tools, MCPs, and other real-work friction without replacing Curator.

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
              events.jsonl + skill usage
                           |
                           v
              capability_forge_report
                           |
                           v
              Capability Maintainer
                (weekly blueprint)
                           |
                           v
              KEEP / PATCH / INVESTIGATE /
                 RETIRE proposals only
                           |
                     approved change
                           |
                           +----> Forge loop
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

The plugin subscribes to `post_tool_call` and registers one model-visible tool: `capability_forge_report`. The tool summarizes sanitized telemetry deterministically; it does not call an LLM or the web.

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

### 3. Install the weekly maintainer blueprint

```bash
hermes skills install JonusNattapong/hermes-capability-forge/skills/capability-maintainer
```

The skill declares `every 7d` as a Hermes Blueprint. Installation should create a **suggested** cron job, not silently schedule it. Review it with `/suggestions` and accept it only when you want periodic maintenance.

The maintainer is proposal-first: it can analyze and research justified candidates, but it does not auto-patch/delete capabilities.

### 4. Optional: make new Forge skills Git-tracked

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

Observer writes raw sanitized events to:

```text
~/.hermes/capability-lab/events.jsonl
```

`capability_forge_report` can also persist sanitized maintenance snapshots to:

```text
~/.hermes/capability-lab/reports/capability-report-<timestamp>.json
```

Reports combine recent Observer events with Hermes `~/.hermes/skills/.usage.json` when available. Missing skill usage is treated as unknown, not proof of non-use.

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

Current Hermes behavior matters here: Curator lifecycle rules depend on skill provenance and configuration, while hub-installed/manual/external skills are not all equivalent. Capability Maintainer therefore treats Hermes usage counters as supporting evidence, not a deletion oracle. V0.2 adds cross-surface maintenance proposals without replacing Curator or bypassing its recoverable lifecycle.

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

### V0.2

- [x] Evidence summarizer (`capability_forge_report`)
- [x] Repeated-failure / retry-loop / elevated-failure / latency / high-usage candidate detector
- [x] Weekly Capability Maintainer Blueprint
- [x] Proposal-first KEEP / PATCH / INVESTIGATE / RETIRE workflow
- [x] Hermes skill usage merge when `.usage.json` is available
- [x] Persisted sanitized maintenance reports
- [x] Upstream research policy limited to justified active candidates
- [x] Tests for report ranking, privacy, corrupted telemetry, and plugin registration

### V0.3 candidates

- [ ] Map tool failures to owning Skill/Plugin/MCP more precisely
- [ ] Capability-specific eval registry and promotion gates
- [ ] Optional guarded patch execution after explicit policy opt-in
- [ ] Baseline/drift comparison across maintenance windows

### Explicitly not in V0.2

- autonomous internet-wide dependency scanning
- unattended auto-patching, auto-merging, or auto-deleting skills
- recording prompts/results for analytics
- modifying Hermes core
- creating MCP wrappers for trivial CLI operations

## Philosophy

**Real work is the benchmark.**

Research informs implementation. Tests establish a baseline. Dogfooding discovers reality. Usage evidence decides what survives.

## License

MIT
