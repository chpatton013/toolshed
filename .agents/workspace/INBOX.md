# Inbox

A write-only drop box for the user to queue up new tasks/notes without colliding
with edits to `TODO.md` (which lives alongside this file at
`.agents/workspace/TODO.md`).

**Contract:**
- **The user** appends new items here, any time — the only writer to this file.
- **The agent** only reads it; items are moved into `.agents/workspace/TODO.md`
  via the `/inbox` and `/work` commands (the only sanctioned writes to this
  file).

**Format:** one item per bullet, optionally timestamped. Prefix with `!` for
anything urgent enough to interrupt current work.

```
- [YYYY-MM-DD] <task or note>
- [YYYY-MM-DD] ! <urgent task or note>
```

## Items

_None._
