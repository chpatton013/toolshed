---
description: Triage .agents/workspace/INBOX.md — move items into .agents/workspace/TODO.md with task ids, then clear the inbox.
---

Process the contents of `workspace/INBOX.md` and incorporate them into
`workspace/TODO.md`. This is a triage-only command: move + id + clear. Do NOT
start doing the tasks themselves unless separately instructed.

Steps:

1. **Read `.agents/workspace/INBOX.md`.** For each item under `## Items`:
   - Add it to the `## Active` section of `.agents/workspace/TODO.md`, preserving
     its sub-bullets/detail. Group clearly-related sub-items under one task.
   - Prefix each new task with a unique **task id** in the form
     `[<date>-<rand>]`:
     - `<date>` — if the inbox item begins with a leading `[YYYY-MM-DD]` date,
       use that date; otherwise use **today's** date (`YYYY-MM-DD`).
     - `<rand>` — a short random token (4 lowercase base36 chars, e.g. `k7q2`),
       unique among task ids already present in `.agents/workspace/TODO.md`.
   - Suffix each new task with a readiness summary in the form
     `(**Complexity:** <complexity>. **Readiness:** <readiness>)`:
     - `<complexity>` — `Low`, `Medium`, or `High`, with an optional blurb about
       why it is complex. Only include a blurb if it would not otherwise be
       obvious.
     - `<readiness>` — `Ready`, `Blocked`, or `Deferred`, with an optional blurb about
       why it is blocked or deferred. Always include a blurb for `Blocked` and
       `Deferred`; never for `Ready`.
   - Example:
     ```
     - [ ] [2026-07-13-k7q2] Build the calibrated-feedback template (**Complexity:**
       Medium. **Readiness:** Blocked - waiting for user for template sections)
     ```

2. **Clear the inbox.** After every item has been moved into `.agents/workspace/TODO.md`,
   remove all bullets under `## Items` in `.agents/workspace/INBOX.md`, leaving the file's
   header and format guide intact and the `## Items` section empty with a
   placeholder like `_None — cleared <YYYY-MM-DD>._`.

   > Invoking this command is your explicit authorization to write to
   > `.agents/workspace/INBOX.md`. This is the ONLY situation in which the agent
   > may edit or clear `INBOX.md` — outside this command it is strictly
   > read-only (copy items into TODO.md and leave INBOX.md untouched).

3. **Report** a short summary: the task ids created and their one-line titles, and
   confirm the inbox was cleared.
