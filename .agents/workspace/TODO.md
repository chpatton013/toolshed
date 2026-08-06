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
  releases, bumps `version` in `toolshed.toml`, re-pins, and re-renders, then
  reports what happened. See `plans/render-update.md`. Opening a PR from the
  result is a separate, deferred follow-up (below).

- **Extract the validator engine into its own repo (D8 item 1).**
  `toolshed/validator/` is now `lint-trap` (`chpatton013/lint-trap`), published
  and tagged at `v0.1.0`, consumed back here as a pinned `[requirements.lint-trap]`
  group the same way `toolshed` itself is pinned. See
  `plans/extract-validator-engine.md` and design decision D11.

## Follow-up

Each of these comes from a "later" in the original plan's USER NOTEs, recorded as
decision D8 in `design/toolshed-design-decisions.md`. Each is large enough to
want its own plan.

- **Render foreign manifests.** `render --manifest <path>` so a project can define
  a tool it does not want to contribute here while reusing the renderer. Needs a
  companion story for resolving a tool across several bin directories, since a
  consumer would then have one bin/ from a release and another of its own.

- **Document reusing this repo's validators downstream** now has two halves:
  `lint-trap` needs to document how a consumer points `[validators] paths` at
  its own directory (that's an in-repo mechanism now, not something this repo's
  docs can speak to); this repo's own release still ships
  `toolshed-validators.tar.gz`, and how a downstream manifest author wires
  *that* into their own `[validators] paths` is still unwritten here too.

- D8 item 5 (a CI job that re-downloads pinned assets and diffs the lockfile)
  is substantially done: `ci.yml`'s `verify-pins` job already does this,
  non-gating. It answers "do the pinned bytes still exist"; `render update`
  answers "is there a newer version" -- the two stay separate jobs on purpose.

- **A scheduled workflow that runs `render update` and opens bump PRs.**
  Deferred out of `render update`'s own plan; cadence and PR-batching are
  decisions for whoever picks this up.

- **Generalize the validator suite further.** Now `lint-trap`'s concern, not
  this repo's: the port is faithful to chiiiirrus, including validators no
  file here exercises. Worth a pass over there once a second consumer exists
  to say what is genuinely general.
