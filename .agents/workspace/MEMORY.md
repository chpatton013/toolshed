# MEMORY

Agent-owned list of reference memories. Durable facts about developing in this
repo worth remembering. Used for quick-reference, not as an archive.

## Facts

- Every tool in `bin/` that runs Python needs `TOOLSHED_SOURCE=.` until this repo
  is published, because `tools.toml` pins the `toolshed` package to a `git+https`
  URL that does not resolve yet. The pre-commit hook is installed with the
  variable seeded (`--env TOOLSHED_SOURCE=.`), so plain `git commit` works.

- `json.dumps(indent=2)` produces byte-identical output to `biome format` for
  dotslash manifests, verified against nine independently hand-written manifests.
  This is why the renderer does not shell out to biome, and why dotslash needs no
  template.

- macOS ships bash 3.2, where `"${arr[@]}"` on an empty array is an unbound
  variable error under `set -u`. Rendered wrappers therefore seed their argument
  array with fixed elements. Any new template must do the same.

- Run the suite through `./bin/test`, not a bare `python -m unittest`. Going
  through the rendered wrapper caught a test that silently inherited
  `TOOLSHED_SOURCE` from the ambient environment; direct invocation hid it.

- `design/toolshed-design-decisions.md` is the durable record of why the manifest
  schema and the wrapper preamble look the way they do. Its decisions resolve
  amendments the original plan carried, so the code alone does not explain them.

- Two override variables exist because two packages get pinned back:
  `TOOLSHED_SOURCE` for `toolshed` itself, `LINT_TRAP_SOURCE` for the validator
  engine (`lint-trap`, extracted per D11). A change to the engine now costs two
  releases to land here -- cut and tag `lint-trap`, then bump the pinned spec in
  this repo's `tools.toml` -- there is no way to exercise an unreleased engine
  change except by setting `LINT_TRAP_SOURCE` to a local checkout.
