# Agent Instructions — Phase 0 Spike

> Read this before touching anything under `spike/`. It governs how the
> **lead/orchestrating agent** in a DSH session must delegate work for this
> spike. Note: DSH has no built-in auto-loading convention for this filename
> — it is not magically injected into context. Whoever is acting as lead for
> this project must read it explicitly at the start of a session (or be
> pointed at it) and follow it.

## Hard rule: delegate only via `workflow`, pinned to the local model

The lead agent must **not** use the plain `subagent` tool for any delegated
work on this project. The plain `subagent` tool has no `provider`/`model`
parameter — it always runs on whatever the harness's current default model
is, which is not what we want here.

Instead, **all delegated work must go through the `workflow` tool**, using
its internal `agent(prompt, opts)` hook with an explicit override to the
local model:

```js
await agent(prompt, {
  label: "<short task label>",
  phase: "<phase title>",
  provider: "lmstudio",
  model: "qwen/qwen3.8-27b",
});
```

This applies even for what would otherwise be a single one-off delegation
(e.g. "run this one task") — wrap it in a minimal `workflow` call rather than
calling `subagent`/`subagent_fork` directly.

### Why
- Keeps all spike implementation work running on the local model (cost,
  privacy, or capacity reasons — local-first for this project).
- `workflow`'s `agent()` is the only tool surface in this harness that
  exposes a provider/model override; `subagent` and `subagent_fork` do not.

### Practical notes for the lead agent
- Each `workflow` call should be self-contained: pass the full task context
  in the prompt (the subagent/local model does not share this session's
  context), same as you would for a plain subagent.
- Prefer `run_in_background: true` for anything non-trivial so the lead can
  keep working/monitoring other tasks, then collect results with
  `job_output` / completion notices.
- If a delegated run needs to be stopped, kill the **job** (`job_kill` on the
  `workflow-N` job id) — there is no direct `interrupt_agent` handle into an
  `agent()` call running inside a workflow script.
- Keep each task's prompt scoped exactly the way `spike/tasks/*.md` files are
  written: self-contained, minimal context, explicit non-goals, explicit
  "write your summary to `tasks/<n>_<slug>.SUMMARY.md` when done" instruction.

## Everything else about process follows `spike/TASKBOARD.md`

`spike/TASKBOARD.md` remains the source of truth for task sequencing,
status, and dependencies. This file only overrides *how* the lead dispatches
work (workflow + local model, never plain subagent) — it does not change the
task breakdown, the task file format, or the summary-file convention.
