# Inbox

A drop box for new tasks/notes without colliding with edits to `tasks.md`
(which lives alongside this file at `.agents/workspace/followup/tasks.md`).

**Contract:**

- **The user** appends new items here, any time, either by editing this file
directly or via `/followup add: <text>`.
- **The agent** only reads it, except for `/followup add:` (appends one item)
and `/followup triage:` (moves items into `.agents/workspace/followup/tasks.md`
and clears them here) — the only sanctioned writes to this file.

**Format:** one item per bullet, optionally timestamped. Prefix with `!` for
anything urgent enough to interrupt current work.

```
- [YYYY-MM-DD] <task or note>
- [YYYY-MM-DD] ! <urgent task or note>
```

## Items

- [2026-09-09] Coordinate the upstream Toolshed release required before Fleet can enable its role: rename the `render` executable to `toolshed`; move the current default action under the explicit `toolshed render` subparser/CLI shape; publish and pin an immutable release; and provide verified Linux x86_64 and arm64/aarch64 architecture-specific release artifacts/packages. Acceptance criteria: released CLI and install artifacts expose the Fleet-required `toolshed render` command and architecture behavior; compatibility or migration expectations are documented; tests cover the CLI shape and platform artifact/package selection; and release/install documentation identifies the pinned version and supported architectures.
