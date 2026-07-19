---
description: Triage the inbox (like /inbox) then work the next tasks in .agents/workspace/TODO.md until Active is empty or you're blocked.
---

Do two phases in order.

## Phase 1 — triage the inbox
Perform the `/inbox` steps (see `.agents/commands/inbox.md`): read
`.agents/workspace/INBOX.md`, move each item under `## Items` into the `## Active` section
of `.agents/workspace/TODO.md` with a `[<date>-<rand>]` task id (date = the item's leading
`[YYYY-MM-DD]` if present, else today; rand = a short unique base36 token), then
clear the inbox `## Items` to `_None — cleared <YYYY-MM-DD>._`.

> Invoking this command authorizes that one inbox write. Outside this triage step
> `.agents/workspace/INBOX.md` stays read-only.

## Phase 2 — work the Active tasks
Then execute the tasks under `## Active` in `.agents/workspace/TODO.md`, top to bottom:

- Read `AGENTS.md` conventions and use the relevant **skill** for each task (`.agents/skills/...`).
  Prefer to delegate tasks to subagents so you can remain an orchestrator that
  the user can continue to interact with while the tasks are implemented.
  Verify subagent output before reporting its completion to the user.
- As each task completes: check it off / move it to a `## Done` section in
  `.agents/workspace/TODO.md`, and **commit** the work in logical steps with descriptive
  messages. Never stage `.agents/workspace/INBOX.md` content beyond the Phase-1 clear.
- Keep going until `## Active` is empty **or** a task needs the user's input or
  a decision you can't reasonably default — then **STOP and ask** rather than guess.
- Give a short progress note as you finish each task, and a summary at the end
  (what's done, what's left, anything awaiting the user).
