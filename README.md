# Hermes Capability Forge

Continuous capability engineering for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

Capability Forge improves Hermes from real work instead of maximizing tool count. It observes repeated friction, performs bounded research, chooses the smallest useful extension surface, verifies the change, dogfoods it, and promotes it only when evidence passes explicit gates.

## V0.3

V0.3 closes the loop from **observe** to **verified, reversible improvement**:

1. **`capability-forge` Skill** — decides whether to reuse, patch, or build a Skill, helper script, Plugin/Tool, or MCP.
2. **`capability-observer` Plugin** — records privacy-preserving operational telemetry from `post_tool_call`.
3. **`capability-maintainer` Skill / Blueprint** — weekly proposal-first maintenance from real evidence.
4. **Ownership Registry** — maps tool failures to an explicit owning capability without guessing.
5. **Eval + Promotion Gate** — capability-specific thresholds must pass before promotion.
6. **Baseline + Drift Guard** — compares current evidence with a trusted passing baseline.
7. **Guarded Patch + Rollback** — optional exact-text repair inside explicit allowlisted roots with SHA-256 concurrency checks and backups.

Hermes Curator remains responsible for its own skill lifecycle. Capability Forge adds cross-surface evidence and does not replace Curator or Hermes core.

## Architecture

```text
                        NORMAL HERMES WORK
                               |
                               v
                      Capability Forge
                               |
                reuse / skill / plugin / MCP
                               |
                               v
                         Verify + Dogfood
                               |
                               v
                      Capability Observer
                               |
                               v
                    events.jsonl + usage
                               |
                               v
                    capability_forge_report
                               |
                    explicit ownership map
                               |
                               v
                    Capability Maintainer
                         (weekly opt-in)
                               |
                KEEP / PATCH / INVESTIGATE /
                       RETIRE proposals
                               |
                       approved foreground work
                               |
                +--------------+--------------+
                |                             |
                v                             v
       capability_forge_gate          guarded patch preview
                |                             |
        PASS + no regression              opt-in apply
                |                             |
                +--------------+--------------+
                               v
                          test + dogfood
                               |
                               v
                    gate + baseline update
```

Core loop:

```text
OBSERVE -> RESEARCH -> DECIDE -> BUILD -> VERIFY -> DOGFOOD
        -> MAP OWNER -> EVAL -> COMPARE -> PROMOTE / ROLLBACK
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

Default: **reuse first, Skill second, code only when justified**.

## Install

Requires a current Hermes Agent release with plugin hooks, plugin tools, Skills Hub installs, and Blueprints.

### 1. Install the plugin

```bash
hermes plugins install JonusNattapong/hermes-capability-forge --enable
```

The plugin registers one hook and three tools:

- `capability_forge_report`
- `capability_forge_gate`
- `capability_forge_patch`

### 2. Install the Forge skill

```bash
hermes skills install JonusNattapong/hermes-capability-forge/skills/capability-forge
```

### 3. Install the weekly Maintainer blueprint

```bash
hermes skills install JonusNattapong/hermes-capability-forge/skills/capability-maintainer
```

The skill declares `every 7d` as a Hermes Blueprint. Hermes should add it as a **suggested** cron job. Installing the skill does not silently schedule it. Review and accept it through `/suggestions` when periodic maintenance is wanted.

Scheduled Maintainer runs are always proposal-first. They do not apply guarded patches or record new baselines automatically.

### 4. Optional builder skills

Reuse Hermes-native MCP helpers:

```bash
hermes skills install official/mcp/fastmcp
hermes skills install official/mcp/mcporter
```

## Telemetry and privacy

Observer writes sanitized events to:

```text
~/.hermes/capability-lab/events.jsonl
```

A typical event contains only operational metadata:

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

Telemetry failure is fail-open: normal Hermes work continues.

## Tool: `capability_forge_report`

The report analyzes a recent window, defaults to 7 days, and detects:

- repeated failures
- retry loops
- elevated failure rates
- high p95 latency
- high-use capabilities worth review
- Hermes skill usage when `.usage.json` contains it

It also resolves tool ownership through an explicit registry. If ownership is unknown or ambiguous, it stays unresolved rather than guessing.

Reports are optionally persisted under:

```text
~/.hermes/capability-lab/reports/
```

## Ownership Registry

User registry default:

```text
~/.hermes/capability-lab/capabilities.json
```

Override:

```bash
CAPABILITY_FORGE_REGISTRY=/path/to/capabilities.json
```

Start from [`data/capabilities.example.json`](data/capabilities.example.json).

Example:

```json
{
  "schema_version": 1,
  "capabilities": [
    {
      "id": "repo-inspector",
      "kind": "skill+plugin",
      "source": "JonusNattapong/repo-inspector",
      "tools": ["repo_scan", "repo_dependency_graph"],
      "tool_prefixes": [],
      "skills": ["repo-inspector"]
    }
  ]
}
```

Rules:

- exact tool ownership wins
- a narrow prefix may be used when a capability owns a stable namespace
- ambiguous matches are unresolved
- no LLM ownership guessing

## Tool: `capability_forge_gate`

Eval registry default:

```text
~/.hermes/capability-lab/evals.json
```

Override:

```bash
CAPABILITY_FORGE_EVALS=/path/to/evals.json
```

Copy [`data/evals.example.json`](data/evals.example.json) and define thresholds per capability:

```json
{
  "schema_version": 1,
  "capabilities": {
    "repo-inspector": {
      "min_calls": 20,
      "max_error_rate": 0.10,
      "max_retry_rate": 0.05,
      "max_unknown_rate": 0.10,
      "max_p95_duration_ms": 5000,
      "min_success_rate": 0.85,
      "drift": {
        "max_error_rate_increase": 0.05,
        "max_retry_rate_increase": 0.03,
        "max_p95_duration_ms_relative_increase": 0.50,
        "max_success_rate_drop": 0.05
      }
    }
  }
}
```

Gate statuses:

- `PASS`
- `FAIL`
- `INSUFFICIENT_EVIDENCE`
- `NO_PROFILE`

Only `PASS` is a promotion pass.

### Baselines

A trusted passing window can be recorded as a baseline:

```text
~/.hermes/capability-lab/baselines.json
```

`record_baseline` refuses non-passing evaluations. Later evaluations compare current metrics with the baseline and return `STABLE` or `REGRESSION` when drift thresholds exist; without drift thresholds the result is `NO_DRIFT_PROFILE` rather than pretending stability was proven.

Do not weaken thresholds merely to make a change pass.

## Tool: `capability_forge_patch`

Guarded patching is **disabled by default**.

To allow preview access, explicitly scope writable roots:

Linux/macOS:

```bash
export CAPABILITY_FORGE_PATCH_ROOTS=/srv/hermes-capabilities:/home/me/project/.hermes/skills
```

PowerShell:

```powershell
$env:CAPABILITY_FORGE_PATCH_ROOTS = "D:\Projects\hermes-capabilities;D:\Projects\myrepo\.hermes\skills"
```

To allow mutation and rollback:

```bash
export CAPABILITY_FORGE_ALLOW_PATCH=1
```

or PowerShell:

```powershell
$env:CAPABILITY_FORGE_ALLOW_PATCH = "1"
```

Patch guarantees:

- target must be inside an explicit allowed root
- regular UTF-8 text file only
- bounded file/replacement sizes
- current SHA-256 must match `expected_sha256`
- `old_text` must match exactly once
- preview is non-mutating
- apply creates a backup + manifest before atomic replacement
- rollback verifies the current patched hash before restoring
- rollback refuses a target changed after the patch

Patch records live under:

```text
~/.hermes/capability-lab/patches/<patch-id>/
```

Recommended foreground flow:

```text
evidence -> research -> eval plan -> patch preview
         -> explicit apply -> tests -> dogfood
         -> promotion gate -> keep OR rollback
```

Do not enable guarded patching on broad roots such as a home directory or filesystem root.

## Curator coexistence

Hermes Curator tracks skill usage and can manage the skills it considers agent-created. Current Hermes behavior distinguishes provenance: bundled/hub/manual/external skills do not all participate in telemetry or mutation the same way.

Capability Forge therefore treats Curator usage as supporting evidence, not a universal ownership/lifecycle oracle. It does not modify Hermes core and does not bypass Curator recovery behavior.

Recommended initial Curator posture:

```bash
hermes curator run --dry-run
```

Keep LLM consolidation conservative until the skill library is understood.

## Dogfood policy

Do not stop after isolated tests:

```text
research
  -> build v0
  -> isolated test
  -> resume original task
  -> use capability normally
  -> observe evidence
  -> targeted repair
  -> run gate
  -> compare baseline
  -> keep or rollback
```

A capability worse than the previous workflow should be reverted or disabled.

## Development

The runtime uses only Python standard-library dependencies.

Run tests:

```bash
python -m unittest discover -s tests -v
```

Validate syntax:

```bash
python -m compileall -q .
```

## Roadmap status

### V0.1

- [x] Capability Forge Skill
- [x] Privacy-preserving Observer
- [x] Git-tracked layout
- [x] Safe config example
- [x] FastMCP/mcporter reuse guidance

### V0.2

- [x] Evidence summarizer
- [x] Repeated-failure/retry/latency detector
- [x] Weekly Maintainer Blueprint
- [x] Proposal-first maintenance
- [x] Skill usage merge
- [x] Sanitized reports

### V0.3

- [x] Explicit capability ownership mapping
- [x] Capability-level failure attribution
- [x] Eval registry and promotion gates
- [x] Passing-only baseline recording
- [x] Baseline/drift comparison
- [x] Opt-in allowlisted exact-text patching
- [x] SHA-256 concurrency guard
- [x] Atomic apply + backup + rollback
- [x] Scheduled maintainer remains non-mutating
- [x] Integration and security tests

### Explicitly not automatic

- internet-wide dependency scanning
- LLM ownership guessing
- unattended scheduled patching
- auto-merging or auto-deleting skills
- recording prompts/results for analytics
- modifying Hermes core
- trivial MCP wrappers for functionality existing tools already handle

## Philosophy

**Real work is the benchmark.**

Research informs implementation. Tests establish a baseline. Dogfooding discovers reality. Ownership localizes the problem. Eval gates test whether a change deserves promotion. Baselines expose regressions. Reversible patches keep experimentation survivable.

## License

MIT
