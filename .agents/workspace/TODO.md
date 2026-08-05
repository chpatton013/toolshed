# TODO

Agent-owned task list. New items arrive via `.agents/workspace/INBOX.md`
(user-owned) and get copied here (INBOX is read-only for the agent outside
`/inbox` and `/work`).

## Active

_Nothing currently active._

## Completed

- Manifest, lockfile, renderer, pinning, validator suite, CI and release
  workflows, installer, docs. See `plans/toolshed-build.md`.

- **Publish the repo and cut v0.1.0.** Pushed to
  `github.com/chpatton013/toolshed` (public), tagged and released `v0.1.0`
  (CI and the release workflow both passed), and re-pinned `tools.toml` to
  `toolshed @ git+https://github.com/chpatton013/toolshed@v0.1.0`. Confirmed
  `env -u TOOLSHED_SOURCE bin/validate --help` resolves the pinned tag over
  the network with no local checkout.

- **`render update` (D8 item 4).** Checks each dotslash tool's upstream GitHub
  releases, bumps `version` in `tools.toml`, re-pins, and re-renders, then
  reports what happened. See `plans/render-update.md`. Opening a PR from the
  result is a separate, deferred follow-up (below).

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

- D8 item 5 (a CI job that re-downloads pinned assets and diffs the lockfile)
  is substantially done: `ci.yml`'s `verify-pins` job already does this,
  non-gating. It answers "do the pinned bytes still exist"; `render update`
  answers "is there a newer version" -- the two stay separate jobs on purpose.

- **A scheduled workflow that runs `render update` and opens bump PRs.**
  Deferred out of `render update`'s own plan; cadence and PR-batching are
  decisions for whoever picks this up.

- **Generalize the validator suite further.** The port is faithful to chiiiirrus,
  including validators no file here exercises. Worth a pass once a second
  consumer exists to say what is genuinely general.
