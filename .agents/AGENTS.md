# Working in this repo

See [README.md](../README.md) for what toolshed does and how the manifest works.
This file covers what you need to know to change it.

## Set TOOLSHED_SOURCE and LINT_TRAP_SOURCE

The rendered wrappers in `bin/` resolve `toolshed` and `lint-trap` (the
validator engine, a separate package) from pinned `git+https` URLs. Working
from this checkout, override both so `validate`, `pre-commit`, and `test`
exercise your working tree instead of the pinned tags:

```bash
TOOLSHED_SOURCE=. LINT_TRAP_SOURCE=<path-to-lint-trap-checkout> ./validate
```

`toolshed` and `test` only need `TOOLSHED_SOURCE`;  `LINT_TRAP_SOURCE` only
matters for tools that load the engine (`validate`, `pre-commit`) or exercise
it as a test dependency (`test_repo_validators.py`). Set both even after
publication when you want to exercise a working tree instead of a pinned
upstream. CI sets `TOOLSHED_SOURCE` for the same reason, but leaves
`LINT_TRAP_SOURCE` unset -- there is no local `lint-trap` checkout on the
runner, so CI exercises the pinned tag instead.

Install the git hook with the variable seeded, so an ordinary `git commit` works:

```bash
TOOLSHED_SOURCE=. ./bin/pre-commit --install --env TOOLSHED_SOURCE=.
```

## The loop

```bash
# regenerate bin/ after a manifest change
TOOLSHED_SOURCE=. ./bin/toolshed render
# unit tests
TOOLSHED_SOURCE=. LINT_TRAP_SOURCE=<path> ./bin/test
# the file-validation suite
TOOLSHED_SOURCE=. LINT_TRAP_SOURCE=<path> ./validate
```

Run `./bin/test` from the repo root. Its `args` hold relative paths.

Three tests skip unless `TOOLSHED_TEST_NETWORK=1` is set. Two download release
assets and compare the digests against known-good values, which is what proves
the pinning code is correct; run them after touching `toolshed/pin.py`. The
third runs `toolshed update` end to end in a `tmp_path` copy of the repo and
checks the lock digests it writes against a direct `toolshed pin` of the same
version; run it after touching `toolshed/upstream.py`.

## Releasing

`bash scripts/release.sh <version>` updates `pyproject.toml` and the
`toolshed.toml` self-pin, commits them, tags `v<version>`, and pushes both. The
workflow then verifies the tree and publishes the GitHub release. The tag,
wheel filename, and self-pin all come from the same argument; never hand-edit
the version and tag separately. Watch with `gh run watch --workflow release.yml
--exit-status`, then download the release and confirm the wheel is named
`toolshed-<version>-py3-none-any.whl` and its checksums verify.

Release tags are published and immutable. If a release went out wrong, clean up
its release and tag before reusing that version, or publish the next version.

## Conventions

- Shared agent context (instructions, house rules, prompts, skills) lives in
  `AGENTS.md` and `.agents/skills/`, never duplicated into a harness-specific
  directory (`.claude/`, `.cursor/`, `.github/`, `.opencode/`, `.pi/`, etc.) —
  those hold only symlinks back into `.agents/` or minimal import shims. Load
  the `agent-context` skill before creating, editing, or relocating any
  agent-facing instruction, rule, prompt, or config file.

**Shell.** `#!/bin/bash --norc` and `set -euo pipefail`. Accumulate command
arguments into an array seeded with fixed elements, never an empty one: macOS
ships bash 3.2, where expanding an empty array under `set -u` is an error.

**Python.** Formatted by black, upgraded by pyupgrade, targeting 3.11. Frozen
dataclasses for parsed manifest data. Domain errors raise `ManifestError` or
`RenderError` rather than returning sentinels.

**TOML.** Formatted by taplo. `toolshed.toml` tables stay sorted by name, which means
dotslash and uv-run tools interleave. Do not group them by method.

**Templates.** `toolshed/templates/*.j2` use `<< >>` for expressions and `<% %>`
for blocks. Shell is dense with `${...}`, and Jinja's default delimiters would
need escaping on nearly every line.

## Things that will trip you up

**Rendered wrappers must stay relocatable.** No `BASH_SOURCE`, no `readlink`, no
`$repo_root`. A wrapper resolves its runner from the environment or `PATH` and
nothing else. That is what lets a consumer mix tools from a release with tools
from a checkout, and `tests/test_render.py` asserts it. If a tool seems to need a
file beside it, put the dependency in the manifest instead.

**Dotslash JSON is serialized by `json.dumps`, not a template.** Its two-space
output is byte-identical to biome's, so `toolshed render --check` and the `dotslash`
validator cannot disagree about formatting. Adding a template for it would
reintroduce that possibility.

**A digest covers the asset as served** -- the archive, not the binary inside it
-- because that is what dotslash verifies before it unpacks anything.

**Editing `bin/` by hand achieves nothing.** `toolshed render` overwrites it and
`manifest-sync` fails the commit. Change `toolshed.toml`.

**The self-reference is a release bootstrap.** Candidate commits may use
`TOOLSHED_SOURCE=.` and retain the prior immutable package SHA. Publish the
candidate before repinning that SHA, then render and verify from outside the
checkout before publishing the final release. Never replace it with a tag.

**`toolshed update` rewrites a dotslash tool's `version = "..."` line with a plain
text search, not a TOML round-trip.** It expects that line inside the tool's own
`[tool.<name>]` table, as a single line reading `version = "<something>"`. Keep
it on one line; a version spread across a line continuation would not match.

**A validator that shells out to a new binary** belongs in `lint-trap`
(`chpatton013/lint-trap`) if it is general enough to ship as a builtin, or in
this repo's `validators/` if it is repo-specific (like `manifest-sync` and
`manifest-pinned`). Either way it needs that binary added to `toolshed.toml` and
the validator listed in `.validator.toml` here -- a validator with no table
there never runs.

## Layout

```
toolshed.toml         the manifest -- every tool and how to bootstrap it
toolshed.lock.toml    generated by `toolshed pin`; sizes and blake3 digests
bin/                  generated by `toolshed render`; committed like a lockfile
validate                 symlink into bin/; `bin/toolshed` is the renderer
toolshed/
  manifest.py         parse and schema-validate toolshed.toml
  lock.py             read and write toolshed.lock.toml
  render.py           emit bin/; the `toolshed` CLI, including `render` and `update`
  pin.py              download assets and compute digests
  upstream.py         check a dotslash tool's github releases for a newer version
  fetch.py            the one urllib call pin.py and upstream.py both use
  templates/          one per rendered method
validators/           this repo's own validators (manifest-sync, manifest-pinned);
                      the engine and its builtins live in lint-trap, pinned like
                      toolshed itself
tests/
scripts/bootstrap/    dotslash runtime installer
install.sh            consumer-side installer
```

`AGENTS.md` at the repo root is a symlink to this file.

## Workspace

`.agents/workspace/` holds material that supports development without belonging
to the project itself:

- `followup/tasks.md` — the task list, and `followup/inbox.md` where new items
  arrive. Managed via the `followup` skill (`/followup add:`/`triage:`/`next:`)
  rather than edited directly, though direct edits are always fine too.
- `MEMORY.md` — durable facts about developing in this repo worth remembering.
- `design/toolshed-design-decisions.md` — why the design is shaped the way it is.
  Read it before changing the manifest schema or the wrapper preamble. Most of its
  decisions exist to satisfy a constraint that is not obvious from the code.
- `plans/` — plan documents for larger pieces of work.
