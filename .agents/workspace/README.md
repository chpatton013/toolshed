# Workspace

This directory serves as the Agent's workspace. Anything that doesn't belong as
part of the project featured in this repository, but is worth persisting for the
sake of agentic development, should live here.

## What belongs here

- `followup/tasks.md` — the agent-owned development task list
- `followup/inbox.md` — drop box for new tasks/notes, moved into `tasks.md` by
  the `followup` skill (`/followup add:`/`triage:`/`next:`). See both files'
  headers for the write-ownership split.
- `MEMORY.md` — durable facts about developing in this repository worth
  remembering. Keep it short; it's a quick-reference, not an archive.
- `plans/` — plan documents for larger pieces of work
- `design/` — durable design decisions and rationale for this repository
- Scratch drafts, intermediate analyses, and experimental results that inform a
  task but are not the work itself.

## Persisting workspace content

Note that the git log can be made into a useful tool of past challenges and
decision making if we effectively capture intermediates and their associated
ideas in commits.

Prefer committing meaningful intermediates with a message explaining the idea
behind them, so the git log stays a useful record of our reasoning across time.
