# Toolshed: design decisions

Input: an inherited plan, written in another repo, carrying 15 `USER NOTE`
amendments that override its own body. This note resolves each one into a
decision. The inherited plan and the build plan it produced are both retired; see
git history for either.

The owner is unavailable to approve these (headless run), so each decision below
records the reasoning and the alternative rejected. Anything the notes describe
as "eventually" or "one step farther" is captured as a follow-up rather than
built now.

## D1. Name

`toolshed` (note: `toolbox` is taken). Python package `toolshed`, repo
`chpatton013/toolshed`, release assets `toolshed-*`.

## D2. Requirements come from the manifest, not from files

**Note:** per-tool specificity is needed; named groups in `tools.toml`; tools
take a list of inline `requirement` and a list of referenced `requirements`
groups; render merges both into the uv invocation.

**Decision.** `tools.toml` grows a `[requirements.<group>]` table with a
`packages` list. A `uv-run` tool declares:

- `requirement = ["black", "pathspec>=0.12"]` — inline specs
- `requirements = ["python-dev"]` — group names, transitively resolved

The renderer merges inline-then-group (inline first, groups in declaration
order), de-duplicates while preserving order, and emits one `--with <spec>` per
resulting entry. No `requirements*.txt` files exist in the repo, so nothing a
generated executable needs lives in a sibling file.

Groups may reference other groups (`requirements = [...]` inside a group) so
that "related tools share a set of the same reqs" composes. Cycles are a
manifest error.

**Rejected:** keeping `requirements-dev.txt` and rendering `--with-requirements`
paths. That is what chiiiirrus does, and it only works because one shared
dependency set covers that whole repo.

## D3. No `$here` / `$repo_root` preamble

**Note:** the symlink-resolving preamble exists only because chiiiirrus's `bin/`
is off `PATH`. Prefer not packaging local dependency files. Remaining problem is
resolving *dependency tools* (`uv`, `bun`). Option 1: prepend our own directory
to `PATH`. Option 2: require the user to manage `PATH`. Leaning option 2 for
security, with option 1 acceptable if a wrapper manages the bin directory.

**Decision.** Rendered wrappers contain no path arithmetic at all. They resolve
their runner like this:

```bash
if [ -n "${TOOLSHED_BIN_DIR:-}" ] && [ -x "$TOOLSHED_BIN_DIR/uv" ]; then
  uv="$TOOLSHED_BIN_DIR/uv"
else
  uv="uv"
fi
```

Default is option 2: whatever `uv` the user's `PATH` resolves. Option 1 becomes
available only when something deliberately exports `TOOLSHED_BIN_DIR` — which is
exactly the "wrapper responsible for managing the location and contents of this
bin/ directory" the note allows. A wrapper opting in is a decision; a script
implicitly trusting its own directory is not, which is the vulnerability the
note flags.

Consequence: `bin/*` files become fully relocatable. A consumer can copy one
wrapper into `~/.local/bin` and it still works. That is what makes the federated
bin/ directories in D8 tractable.

## D4. Bootstrapping toolshed's own Python code

D2 and D3 remove local file references, but three of this repo's tools
(`render`, `validate`, `pre-commit`) execute *this repo's* Python package. Their
dependency spec cannot be a relative path without reintroducing what D3 removed.

**Decision.** A requirements group may declare `override_env`. The rendered
wrapper prefers that environment variable's value over the group's packages:

```bash
[requirements.toolshed]
packages = ["toolshed @ git+https://github.com/chpatton013/toolshed@main"]
override_env = "TOOLSHED_SOURCE"
```

renders to

```bash
if [ -n "${TOOLSHED_SOURCE:-}" ]; then
  uv_args+=(--with "$TOOLSHED_SOURCE")
else
  uv_args+=(--with "toolshed @ git+https://github.com/chpatton013/toolshed@main")
fi
```

Working on toolshed itself is then `TOOLSHED_SOURCE=. ./bin/validate`. CI sets
it too, so CI tests the tree under review rather than `main`. Released wrappers
with the variable unset resolve the pinned upstream spec.

This is generic — any group can be overridable — so a downstream project
rendering its own tools gets the same escape hatch for its own package.

**Rejected:** `--with-editable` on a path baked into the wrapper (defeats D3);
publishing a wheel before anything works (chicken/egg with no releases yet).

## D5. Digests live in `tools.lock.toml`

Unchanged from the plan: `tools.toml` is hand-edited (versions, URLs),
`tools.lock.toml` is machine-generated (`size` + blake3 `digest` per platform).
Keeping them apart keeps a version bump a one-line edit.

Seed data: chiiiirrus's hand-maintained manifests carry verified digests for
`uv`, `bun`, `shfmt`, `shellcheck`, `biome`, `taplo`, `jq`, `gitleaks`,
`yamlfmt`. `render pin` recomputes them from upstream; agreeing with
chiiiirrus's values is a useful cross-check that the pinning code is correct.

Two shapes to support, both present in chiiiirrus: archived assets (`format` +
`archive_path` inside the archive) and raw binaries (no `format`; `path` is just
the cache filename dotslash writes).

## D6. Validator suite: engine vs. repo-specific validators

**Note:** copying the whole package is fine to stand things up, but the
generally-useful validators should eventually become their own project, with
this repo keeping repo-specific validators in a `validators/` directory and the
engine runtime-configured to merge builtins with them.

**Decision.** Build the split now — it is cheap and it is the shape the note
asks for:

- `toolshed/validator/` — engine (`base`, `config`, `registry`, `runner`,
  `precommit`) plus `toolshed/validator/validators/` for the generic builtins.
- `validators/` at the repo root — this repo's own validators
  (`manifest-sync`, `manifest-pinned`).
- `.validator.toml` grows a top-level `[validators] paths = ["validators"]`.
  The registry loads builtins, then each configured path, and rejects duplicate
  validator names.

Extracting the engine into a separate repo later then becomes a move, not a
refactor. Deferred to follow-up.

## D7. Release artifacts: split, don't tar the world

**Note:** with no sibling-file dependencies there is no reason to tar the whole
repo; fork into separate artifacts — the rendered `bin/`, the packaging tools,
the validators.

**Decision.** Three assets per release, plus `SHA256SUMS`. Asset names carry no
version, so `releases/latest/download/<asset>` resolves; the tag names the
install directory instead.

| Asset | Contents | Consumer |
| --- | --- | --- |
| `toolshed-bin.tar.gz` | `bin/` only | wants the tools on `PATH` (mode 1) |
| `toolshed-<version>-py3-none-any.whl` | `toolshed` package: renderer + validator engine + builtin validators + templates | renders its own `bin/` from its own `tools.toml`, and reuses the validator engine |
| `toolshed-validators.tar.gz` | `validators/` | wants this repo's manifest validators against its own manifest |

The wheel carries the validator *engine* because a consumer who renders their
own tools needs it to run anything; `validators/` ships separately because it is
repo-specific policy, not engine. `entrypoints/` from the original layout is
dropped — with D2/D3 no tool needs an in-repo payload file, so the directory
would be empty.

No `build-artifacts.yml`. **Note:** this repo should not build releases for
projects it merely references; the wezterm fork hosts its own releases and
`tools.toml` just points at them. A `build = ...` key would be dead weight, so
it is omitted.

## D8. Deferred to follow-ups

Each of these is a "later" in the notes, and each is large enough to warrant its
own plan:

1. ~~Extract the validator engine into its own repo, consumed as a pinned
   tool.~~ Done -- see D11.
2. `render --manifest <path>` against a foreign `tools.toml`, plus the exec
   wrapper that resolves a tool across federated bin directories.
3. Publish the validators so downstream manifest authors can reuse them (D7
   ships the artifact; the integration story is unwritten).
4. `render update` — check upstreams for newer versions and open a bump PR.
5. A CI job that re-downloads pinned assets and asserts digests still match,
   catching upstream re-tags.

## D9. dotslash prerequisite

dotslash cannot itself be a dotslash file. Port chiiiirrus's
`scripts/bootstrap/dotslash.sh` (idempotent: exits 0 if `dotslash` is already
resolvable) and have `install.sh` call it unless `--no-dotslash` is passed. The
note asks for exactly this rather than a documented manual prerequisite.

## D10. Consumer modes

Both modes stay first-class, and mixing them is supported: mode 1 is a release
tarball extracted onto `PATH`, mode 2 is a local checkout (submodule or not)
whose `bin/` goes on `PATH`. D3 is what makes mixing work — a wrapper does not
care where it sits, so a project can take most tools from a release and a few
from a checkout.

`install.sh` is generalized per the note: `--repo`, `--version`, `--asset`,
`--dest` all overridable, so someone publishing their own toolshed-rendered
tools can reuse the script unmodified.

## D11. Extracting the validator engine into `lint-trap`

D6 built the engine/repo-specific split so this extraction would be a move, not
a refactor; D8 item 1 named it as a follow-up. See
`plans/extract-validator-engine.md` for the sequencing.

**Decision.** `toolshed/validator/` became its own repository and package,
`lint-trap` (`chpatton013/lint-trap`, importable as `lint_trap`), published and
tagged at `v0.1.0`. This repo deleted its copy and now consumes `lint-trap`
back exactly the way it already consumed `toolshed` itself (D4): a
`[requirements.lint-trap]` group in `tools.toml` with
`override_env = "LINT_TRAP_SOURCE"`. `validators/manifest_sync.py` and
`validators/manifest_pinned.py` import `lint_trap.base` instead of
`toolshed.validator.base`; `tests/test_repo_validators.py` now exercises the
engine as an external dependency instead of an in-repo module.

The two repos pin nothing of each other going backward -- `lint-trap` has no
dependency on `toolshed` -- so there is no bootstrapping cycle, only the
ordinary "cut a `lint-trap` release, then re-pin it here" dance that any two
of this repo's dependencies already have.

**`[requirements.python-validators]` survives as its own explicit group**
rather than folding into `lint-trap[validators]`. The reasoning is D4's escape
hatch, restated for two overridable groups instead of one: `override_env`
replaces its group's packages wholesale, so pinning
`lint-trap[validators] @ git+...` and overriding it with
`LINT_TRAP_SOURCE=../lint-trap` would render `--with ../lint-trap` -- a local
path with no extras -- and every third-party-backed builtin (black,
pyupgrade, yamllint) would fail to import. Keeping `python-validators` as a
plain, always-resolved group means overriding `LINT_TRAP_SOURCE` only ever
swaps the engine, never the tools it shells out to. This also means the git
spec for `lint-trap` itself omits the `[validators]` extra: it would just
install black/pyupgrade/yamllint a second time.

**Consequence for CI.** `ci.yml` and `release.yml` keep `TOOLSHED_SOURCE: .`
(a local checkout is always present) but do not set `LINT_TRAP_SOURCE`: there
is no sibling `lint-trap` checkout on the runner, so CI resolves the pinned
`git+https` tag for the engine on every run. That is a feature, not a gap --
it is the thing that proves the pin is correct, the same role
`TOOLSHED_TEST_NETWORK=1` plays for `toolshed/pin.py`.

## Risks

- **Nothing is published yet.** The `git+https` spec in D4 points at a repo that
  does not exist, so `bin/validate` only works with `TOOLSHED_SOURCE` set. That
  is correct-but-inert until first push; tests must therefore set it.
- **`render pin` needs network and trust.** Unchanged from the plan: run it
  deliberately, review the lock diff.
- **blake3 is not in the stdlib.** Pinning needs the `blake3` package, which
  makes `render` depend on a wheel with a native component. Acceptable; it is
  only needed for `pin`, so the import is local to that path and plain `render`
  keeps working without it.
