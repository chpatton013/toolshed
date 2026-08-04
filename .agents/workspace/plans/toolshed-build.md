# Plan: build toolshed

**Goal.** A standalone repo that renders a portable `bin/` of pinned,
hash-verified, self-fetching executables from one declarative manifest, and
publishes it as release artifacts.

**Approach.** `.agents/workspace/design/toolshed-design-decisions.md` (D1–D10).
That note resolves the `USER NOTE` amendments carried by the superseded
`bin-distribution-separate-repo.md`; read it before starting any task here.

**Status.** In progress.

**Sequencing rationale.** T1–T3 front-load the two assumptions everything else
rests on: that a wrapper with no path arithmetic can actually run (D3/D4), and
that we can reproduce upstream digests (D5). If either is wrong, the manifest
schema changes and later tasks are wasted. The validator port (T6–T8) is bulk
work with no design risk, so it comes after.

---

## T1. Repo skeleton and packaging

Create `pyproject.toml` making `toolshed` an installable package (hatchling,
`requires-python >=3.11` for `tomllib`), package-data the templates, `.gitignore`,
and the `toolshed/` package with `manifest.py`/`render.py` stubs.

**Done when:** `uv run --with . python -c "import toolshed"` succeeds.

## T2. Manifest parsing — `toolshed/manifest.py`

Parse and schema-validate `tools.toml` into frozen dataclasses:
`Manifest`, `Tool` (one per `method`), `RequirementsGroup`.

Covers D2: `[requirements.<group>]` with `packages`, optional nested
`requirements`, optional `override_env`. Group resolution is transitive,
order-preserving, de-duplicating, and raises on cycles and unknown names.

Covers D5: dotslash tools carry `version`, `url`, optional `format`,
`archive_path`, and a `platforms` table of substitution vars.

**Done when:** `tests/test_manifest.py` passes — group nesting, dedup order,
cycle detection, unknown-group error, unknown-method error, and the four-platform
requirement each have a case.

## T3. Templates and the renderer — `toolshed/render.py`

Three templates (Jinja2), rendered to mode 0755:

- `uv-run.sh.j2` — D3 runner resolution, D4 `override_env` branch, one `--with`
  per resolved requirement, `exec` into `python -m <module>`.
- `bun-run.sh.j2` — same runner resolution; `bun run <entry>` or `bun x <package>`.
- `dotslash.json.j2` — shebang + JSON, digests read from the lockfile.

`render` writes `bin/`; `render --check` renders to a temp dir and diffs,
exiting non-zero on drift. Unpinned dotslash tools are a render error.

**Done when:** `tests/test_render.py` passes, and a rendered `uv-run` wrapper
executes end-to-end from a directory that is not the repo — proving D3. Verify
with `TOOLSHED_SOURCE=$PWD`, `cd /tmp`, run the wrapper.

## T4. Pinning — `toolshed/pin.py`

`render pin [tool...]`: for every platform of every dotslash tool, download the
asset, record `size` + blake3 `digest` into `tools.lock.toml`. Idempotent;
writes sorted, stable TOML.

**Done when:** pinning `shfmt` and `uv` reproduces byte-identical
size/digest values to chiiiirrus's hand-maintained manifests (the D5
cross-check). A digest that disagrees means the code is wrong, not that upstream
moved — investigate before proceeding.

## T5. Seed the manifest and generate `bin/`

Populate `tools.toml` with `uv`, `bun`, `shfmt`, `shellcheck`, `biome`, `taplo`,
`jq`, `gitleaks`, `yamlfmt` (dotslash) and `render`, `validate`, `pre-commit`,
`test` (uv-run). `render pin` all of them, then `render`.

**Done when:** `./bin/shfmt --version` and `./bin/jq --version` self-fetch and
run; `./render --check` is clean; `git diff --exit-code bin/` after a re-render
is empty.

## T6. Port the validator engine — `toolshed/validator/`

Port `base`, `config`, `registry`, `runner`, `__main__`, `precommit/` from
chiiiirrus near-verbatim. Two changes: imports move to `toolshed.validator`, and
per D6 the registry accepts extra search paths so builtins merge with
repo-local validators.

**Done when:** `tests/test_registry.py` proves builtins load, an extra path's
validators load, and a duplicate name across the two raises.

## T7. Port the builtin validators

`toolshed/validator/validators/`: dotslash, biome, shellcheck, shfmt, taplo,
yamlfmt, yamllint, python-black, pyupgrade, python-filename, python-fstring,
python-shadow-import, keep-sorted, case-conflict, conflict-markers,
executable-extension, file-size, filename-chars, gitleaks, symlink, tabs,
trailing-newline, trailing-whitespace, unicode.

Drop rustfmt / terraform-fmt / ini / xml — no such files here, and each would
pull an unused pinned tool.

Subprocess-backed validators resolve their tool the same way D3 wrappers do
(`TOOLSHED_BIN_DIR`, else `PATH`) instead of hardcoding `repo_root/bin/<tool>`.

**Done when:** `./validate` runs the whole suite over the repo and every finding
is a real one.

## T8. Repo-specific validators — `validators/`

`manifest_sync.py` (assert `render --check` is clean) and `manifest_pinned.py`
(every dotslash tool has a digest for all four platforms). Wire
`[validators] paths = ["validators"]` into `.validator.toml`.

**Done when:** deleting a digest from `tools.lock.toml` makes `./validate` fail
with `manifest-pinned`; bumping a `version` without re-rendering fails with
`manifest-sync`. Both restored afterward.

## T9. Clean the tree

`./validate --fix` until clean, then `./bin/pre-commit --install`.

**Done when:** `./validate` exits 0 with no output.

## T10. CI and release workflows

`ci.yml`: matrix over macos/ubuntu — install dotslash, `render --check`,
`validate`, `test`, all with `TOOLSHED_SOURCE=.` per D4.
`release.yml`: on `v*` tag, build the three D7 assets plus `SHA256SUMS`, publish
with `gh release create`.

**Done when:** both files pass `validate` (yamllint/yamlfmt) and the asset names
match what `install.sh` fetches.

## T11. Consumer entry points

`scripts/bootstrap/dotslash.sh` (ported, idempotent) and a generalized
`install.sh` per D10 (`--repo`, `--version`, `--asset`, `--dest`,
`--no-dotslash`), verifying `SHA256SUMS` before extracting.

**Done when:** `install.sh --help` is accurate and shellcheck passes on both.

## T12. Documentation

`README.md` (what it is, consumer modes, adding a tool, bumping a version),
`AGENTS.md` (repo conventions), `.agents/AGENTS.md` (agent primer), and the D8
follow-ups recorded in `.agents/workspace/TODO.md`.

**Done when:** a reader can add a tool and cut a release from the README alone.
