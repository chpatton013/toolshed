# TODO

Agent-owned task list. New items arrive via `.agents/workspace/INBOX.md`
(user-owned) and get copied here (INBOX is read-only for the agent outside
`/inbox` and `/work`).

## Active

- **Publish the repo and cut v0.1.0.** Everything else is blocked behind this.
  `tools.toml` pins `toolshed @ git+https://github.com/chpatton013/toolshed@main`,
  which does not resolve yet, so `bin/`'s Python tools only work with
  `TOOLSHED_SOURCE` set. After the first push, re-pin that spec to a tag and
  confirm a wrapper works with the variable unset. Neither CI workflow has ever
  run.

## Completed

- Manifest, lockfile, renderer, pinning, validator suite, CI and release
  workflows, installer, docs. See `plans/toolshed-build.md`.

## Follow-up

Each of these comes from a "later" in the original plan's USER NOTEs, recorded as
decision D8 in `design/toolshed-design-decisions.md`. Each is large enough to
want its own plan.

- **Extract the validator engine into its own repo,** consumed back here as a
  pinned tool like any other. `toolshed/validator/` is already separate from the
  repo-specific `validators/`, and the registry already merges builtins with
  configured paths, so this is close to a move rather than a refactor.

- **Render foreign manifests.** `render --manifest <path>` so a project can define
  a tool it does not want to contribute here while reusing the renderer. Needs a
  companion story for resolving a tool across several bin directories, since a
  consumer would then have one bin/ from a release and another of its own.

- **Document reusing this repo's validators downstream.** The release already
  ships `toolshed-validators.tar.gz`; how a downstream manifest author wires it
  into `[validators] paths` is unwritten.

- **`render update`.** Check upstreams for newer releases and open a PR bumping
  `version` and re-pinning.

- **Generalize the validator suite further.** The port is faithful to chiiiirrus,
  including validators no file here exercises. Worth a pass once a second
  consumer exists to say what is genuinely general.
