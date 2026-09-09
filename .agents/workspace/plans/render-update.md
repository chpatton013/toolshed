# Plan: `render update`

**Goal.** `render update` checks the manifest's dotslash tools against upstream
releases, bumps `version` in `toolshed.toml` for every tool with an available
update, re-pins, and re-renders -- then writes a report of what happened
(current version, newest available, and outcome per tool) to stdout by default,
or to a file if `--report <path>` is given. A scheduled workflow that runs this
command and opens bump PRs is a deferred follow-up (see below), not part of
this plan.

**Approach.** Decision D8 item 4 in
`design/toolshed-design-decisions.md`. Constrained by D5 (`toolshed.toml` is
hand-edited, `toolshed.lock.toml` is machine-generated) and by the existing
`render pin` path, which this reuses rather than reimplements.

**Status.** Not started. The repo is published at
github.com/chpatton013/toolshed (public), v0.1.0 has been cut, and CI has run
successfully, so nothing blocks starting T1.

**Scope.** dotslash tools only. A `uv-run` tool's `requirement` specs are floors
that `uv` resolves at run time (D2), so there is no pinned version to bump; the
one exception is the `toolshed` group's `git+https` spec, which the release
process owns. PyPI checking is not in scope.

**Relationship to D8 item 5.** `ci.yml` already carries a `verify-pins` job that
re-downloads every pinned asset and diffs the lockfile, non-gating -- item 5 is
substantially done. It answers "do the pinned bytes still exist"; `render update`
answers "is there a newer version". They overlap only in the fetch layer, which
T1 factors out. Do not merge them into one job: a digest change on an unchanged
version is a supply-chain signal, and a bump must not be able to hide it.

**Sequencing rationale.** T1 carries all the design risk: every tool's release
tag has to be recoverable from its `url` template, and the GitHub releases API
has to expose those tags in a form the templates match. If that inference fails
for even one of the nine tools, the manifest needs a new schema key and T2-T4
change shape. Write-back (T3) comes before T4 because T4 composes the two
halves. T5 (the network end-to-end check) needs T4 done; T6 (docs) is last
because it documents the finished command.

---

## T1. Upstream discovery -- `toolshed/upstream.py`

A new module that answers, for one `DotslashTool`, "what versions does upstream
offer?" -- with no knowledge of pinning or manifests-on-disk.

Derive the source from `tool.url` rather than adding manifest keys, per D5's
one-line-bump goal:

- Match `https://github.com/{owner}/{repo}/releases/download/{rest}`. Anything
  else is an unsupported source: skip the tool with a stated reason, never an
  error.
- The tag template is `rest` minus its final path segment (asset filenames hold
  no `/`). Verify against every tool in `toolshed.toml`: `v{version}` (shfmt,
  shellcheck, gitleaks, yamlfmt), `{version}` (uv, taplo), `jq-{version}`,
  `bun-v{version}`, `%40biomejs/biome%40{version}` (biome).
- Percent-decode the tag template before matching, so biome's becomes
  `@biomejs/biome@{version}` -- what the API reports as `tag_name`.
- A tag template with no `{version}`, or with a per-platform placeholder in it,
  is unsupported. Skip with a reason.

This inference is the whole design: no `[tool.<name>.update]` schema table is
being added now. A tool hosting releases outside GitHub, or needing a filtered
tag set, would need one, but that stays deferred until such a tool actually
exists in the manifest.

Query `GET /repos/{owner}/{repo}/releases?per_page=100`, not
`/releases/latest`: biome's repo tags several products, and `latest` is by
publish date, so it can name a tag the template does not match. Drop drafts and
prereleases, then keep tags the inverted template matches, capturing `version`.

Send `Authorization: Bearer` from `GH_TOKEN` or `GITHUB_TOKEN` when either is
set. Unauthenticated is 60 requests/hour against a nine-request run, which is
fine locally and not in CI.

Factor `pin._fetch`'s urllib call into a shared helper this module and `pin.py`
both use. Keep the timeout and the `ManifestError`-on-failure behavior.

**Done when:** `tests/test_upstream.py` derives the expected owner/repo and tag
template for all nine dotslash tables in the real `toolshed.toml` (parametrized off
the committed file, so a new tool that breaks inference fails the suite), and
asserts unsupported-source and no-`{version}` cases report rather than raise. A
`TOOLSHED_TEST_NETWORK=1`-gated case queries shfmt's releases and asserts the
matched set contains `3.13.1`.

## T2. Version ordering and prerelease filtering

A `latest_version(candidates, current)` in `toolshed/upstream.py`. Compare on a
tuple of integer segments split on `.`; a candidate with any non-numeric segment
counts as a prerelease and is dropped unless `--allow-prerelease`. Return the
maximum, or `None` when nothing exceeds `current`.

Prereleases stay opt-in behind that flag, disabled by default -- bun is the one
tool here that publishes canary builds, and nothing in this manifest wants them
without asking.

**Done when:** tests cover `3.9.0 < 3.13.1` (so ordering is not lexical), a
`1.3.12-canary` candidate dropped by default and kept with the flag, an upstream
that is behind the manifest reporting no update, and equal versions reporting no
update.

## T3. Write the version back -- `toolshed/upstream.py`

`rewrite_version(text, tool_name, version) -> str`: a surgical edit of the
`toolshed.toml` source. Find the `[tool.<name>]` header, then the first
`version = "..."` line before the next column-zero `[`, and replace only that
string. Raise `ManifestError` if either is absent.

No TOML round-trip: `tomllib` cannot write, and a writer would discard the
comments and taplo formatting that `validate` then demands back.

**Done when:** tests bump `shfmt` against the committed `toolshed.toml` and assert
the result differs by exactly one line, reparses, and yields the new version;
that bumping `biome` does not touch `[tool.bun]`; and that an absent tool or an
absent `version` key raises.

## T4. `render update`

Wire a subparser beside `pin` in `toolshed/render.py`: positional `tools`
(default: every dotslash tool), `--allow-prerelease`, `--json`, and
`--report <path>` (defaults to stdout).

For each named tool, in manifest order:

1. Discover upstream versions (T1) and pick the newest per `latest_version`
   (T2).
2. If there's an update: `rewrite_version` (T3) and write `toolshed.toml`, reload
   the manifest so the URL picks up the new version, then
   `pin_tools(manifest, lock_path, [name])`.
3. On any failure in step 2, restore the previous `toolshed.toml` text, leave the
   lockfile as it was, and record the tool as failed. Continue with the rest of
   the tools.

The rollback is the point of this task, not a nicety: upstream renames assets
across major versions, so a bump whose URL 404s must leave that tool's
`toolshed.toml` and lockfile state exactly as found, without blocking the other
tools in the same invocation.

After the loop, `write_bin` so `bin/` matches -- otherwise `manifest-sync` fails
the commit.

The report is one line per tool: current version, newest available (if any),
and one of `current`, `updated`, or `failed: <reason>`. `--json` emits the same
records. It's written to stdout by default, or to the `--report` path if given.
A major-version bump gets no special treatment -- it's just another line in the
report, current version to newest, same as a patch bump.

**Done when:** with a stubbed fetch, running `render update` changes one line of
`toolshed.toml`, the tool's four lock entries, and `bin/<tool>`; `./render --check`
is clean afterward; a stub that fails on one platform's download leaves that
tool's `toolshed.toml` and `toolshed.lock.toml` byte-identical to before while the
other tools still update, and the report marks it `failed: <reason>`;
`--report <path>` writes the same content to the file instead of stdout; and an
unknown tool name errors the way `render pin` does.

## T5. One end-to-end network check

A `TOOLSHED_TEST_NETWORK=1`-gated test that runs `render update` for a single
tool in a copy of the repo under `tmp_path` and asserts the lock digests it
writes match what `render pin` writes for the same version. This is the only
test that proves discovery, write-back, and pinning compose against real
upstreams. Document it in `AGENTS.md` beside the two existing network tests.

**Done when:** the test passes with the variable set and skips without it, and
`./bin/test` stays green in a network-free environment.

## T6. Documentation

- `README.md`: extend the bump-a-version paragraph with `render update` and
  `--report <path>`, and say it covers dotslash tools only.
- `AGENTS.md`: the new network test, and that `toolshed.toml` version lines are
  machine-rewritten so their formatting must stay on one line.
- `followup/tasks.md`: move the D8 item 4 entry to Completed, pointing at this
  plan. Note in the D8 item 5 entry that `ci.yml`'s `verify-pins` job already
  covers it. Add a one-line follow-up entry for the deferred scheduled workflow
  (see below).

**Done when:** a reader can bump every tool in the repo from the README alone.

---

## Follow-up (deferred)

A scheduled GitHub Actions workflow that runs `render update` on a cadence and
opens PRs for whatever it bumps is out of scope for this plan. Log it as a
one-line follow-up in `followup/tasks.md`; cadence and PR-batching are
decisions for whoever picks up that work.

### Critical files for implementation

- toolshed/upstream.py (new)
- toolshed/render.py
- toolshed/pin.py
- toolshed.toml
- tests/test_upstream.py (new)
