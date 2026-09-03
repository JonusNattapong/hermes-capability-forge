---
name: capability-forge
description: >
  Continuously improve Hermes capabilities while doing real work. Use when a task
  reveals missing capability, repeated friction, an unreliable workflow, or an
  opportunity to create or improve a Skill, helper script, Hermes plugin/tool, or
  MCP server. Research existing solutions lightly before building, prefer reuse
  and patching over creating new components, verify changes, dogfood them on the
  current real task, and preserve useful lessons for future runs.
version: 0.2.0
metadata:
  hermes:
    tags:
      - self-improvement
      - skills
      - tools
      - mcp
      - research
      - dogfood
      - engineering
    category: autonomous-ai-agents
    related_skills:
      - capability-maintainer
---

# Capability Forge

Build capabilities only when real work demonstrates that they are useful.

The purpose is not to maximize installed tools, skills, plugins, or MCP servers.
The purpose is to reduce repeated friction, improve reliability, and make future
work easier.

## Core loop

**OBSERVE -> RESEARCH -> DECIDE -> BUILD -> VERIFY -> DOGFOOD -> LEARN -> IMPROVE**

Do not interrupt ordinary work merely to invent infrastructure.

When the `capability_forge_report` tool is available, use it before broad maintenance work or before creating a replacement for an unreliable existing capability. It provides sanitized evidence from real tool usage; treat missing telemetry as unknown, not proof of non-use.

## 1. Observe

While completing real work, notice:

- repeated commands, procedures, or research
- missing access to an external system
- recurring errors or workarounds
- repetitive result transformation
- fragile multi-step workflows
- missing validation or verification
- user corrections
- unnecessary tool calls
- incomplete or stale skills

Do not treat every inconvenience as a reason to create a capability. Prefer
evidence from actual usage.

## 2. Inspect existing capabilities first

Before creating anything:

1. inspect relevant installed skills
2. inspect available Hermes tools
3. inspect enabled plugins
4. inspect configured MCP servers
5. inspect project-local skills
6. search the Hermes skills catalog when appropriate

Prefer, in order:

1. use an existing capability unchanged
2. configure an existing capability
3. patch an existing skill
4. add a helper/reference to an existing skill
5. create a focused new skill
6. create a plugin/tool
7. create or integrate an MCP server

Do not create near-duplicate skills.

## 3. Light research

When implementation depends on technology, APIs, standards, current versions, or
community solutions, perform bounded web research before building.

Default research budget:

- official project documentation
- official repository/source
- 1-3 strong external/community sources only when they materially help

Research should answer:

- Does a good implementation already exist?
- What is the current recommended approach?
- What changed recently?
- What are common failure modes?
- Are there security or compatibility concerns?
- Is there a maintained CLI, SDK, Skill, Plugin, or MCP server to reuse?

Stop once there is enough evidence to implement safely. Do not turn small
engineering work into a literature review.

## 4. Choose the extension surface

| Need | Prefer |
| --- | --- |
| Procedure, knowledge, process | Skill |
| Existing CLI works but commands are complex | Skill + script |
| Deterministic logic or native execution | Hermes Plugin / Tool |
| Hermes lifecycle hooks | Hermes Plugin |
| External API/service with multiple operations | MCP |
| Capability shared by multiple agents/clients | MCP |
| Repo-specific workflow | Project-local skill |
| Short preference/path/fact | Memory |
| One-off task | Build nothing |

Keep reasoning and workflow in Skills. Keep deterministic mechanics in scripts or
tools. Do not wrap trivial terminal functionality in MCP.

## 5. Define success before building

Define a small set of observable criteria, for example:

- reduce a seven-step workflow to two steps
- eliminate a known recurring error
- produce structured deterministic output
- handle three representative tasks successfully
- expose only MCP operations required by the workflow
- cause no regression in ordinary Hermes usage

Avoid criteria such as "smarter" or "better".

## 6. Build the minimum useful version

Implement the smallest version that solves the current real problem. Prefer:

- focused interfaces
- narrow permissions
- small schemas
- explicit errors
- idempotent operations where practical
- timeouts for external operations
- structured outputs
- simple dependencies

Never put secrets in skill files or source code.

## 7. Verify

### Skill

Check trigger specificity, self-contained workflow, valid commands/paths,
references, failure cases, and verification instructions. Run representative
prompts when practical.

### Plugin / Tool

Check input validation, error handling, timeout behavior, missing configuration,
safe defaults, and basic tests.

### MCP

Check tool naming/descriptions, minimal schemas, validation, actionable failures,
permissions, destructive-operation separation, and representative multi-tool
workflows.

## 8. Dogfood on real work

After isolated verification, resume the original task and use the capability
normally. Observe:

- correct selection timing
- unnecessary calls
- argument quality
- output usefulness
- work reduction
- latency
- new failure modes
- user corrections

If it is worse than the previous approach, revert or disable it.

## 9. Learn during use

When real usage reveals a reusable lesson:

- patch Skills for procedural improvements
- update references when external behavior changes
- improve scripts for deterministic failures
- improve tool schemas/descriptions when selection is poor
- improve MCP boundaries when workflows require unnecessary calls

Prefer targeted patches. Do not encode one-off accidents as permanent rules.

## 10. Promotion, maintenance, and retirement

Promote a prototype only after successful representative use and known failure
modes are handled or documented. Periodically review active capabilities for
upstream changes, recurring failures, broken references, usage, and overlap.

Research maintenance changes only when an active capability has evidence of
upstream drift, repeated failure, or stale references. Avoid churn simply because
a newer version exists.

Archive or consolidate capabilities that are superseded, unused, duplicated,
dependent on abandoned software, or consistently more complex than valuable.
Preserve reusable lessons first.

## Operating principle

**Real work is the benchmark.**

Research informs implementation. Tests establish a baseline. Dogfooding discovers
reality. Usage evidence decides what survives.
