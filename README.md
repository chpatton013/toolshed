# toolshed

Declare a set of command-line tools once, get a portable `bin/` directory that
fetches and verifies them on demand.

A single manifest (`tools.toml`) lists every tool. `render` turns it into one
executable per tool in `bin/`. Put that directory on `PATH` and the tools work:
prebuilt binaries download themselves through [dotslash](https://dotslash-cli.com)
against a pinned content digest, and Python tools resolve their dependencies
through `uv` at first run. Nothing is installed ahead of time, and every download
is checked against a digest recorded in `tools.lock.toml`.

The host needs `curl` and the dotslash runtime. Everything else arrives on
demand.

## Install

```bash
# Downloads the latest bin/ tarball, verifies it, installs the dotslash runtime,
# and prints the directory to add to PATH.
export PATH="$(bash install.sh):$PATH"
```

`install.sh` takes `--repo`, `--version`, `--asset`, and `--dest`, so it also
installs releases published by anyone else using toolshed. Run
`bash install.sh --help` for the details.

To skip the installer and track a checkout instead, clone this repo and put its
`bin/` on `PATH`. Both work, and they mix: because a rendered executable holds no
reference to its own location, you can take most tools from a release and a few
from a checkout.

## Release assets

| Asset | Contents | Use it when |
| --- | --- | --- |
| `toolshed-bin.tar.gz` | `bin/` | You want the tools on `PATH`. |
| `toolshed-<version>-py3-none-any.whl` | The renderer | You want to render your own `bin/` from your own manifest. |
| `toolshed-validators.tar.gz` | `validators/` | You want this repo's manifest checks against your own manifest. |
| `SHA256SUMS` | Checksums for the above | Always. `install.sh` verifies against it. |

## Tools

`bin/` currently ships `biome`, `bun`, `gitleaks`, `jq`, `shellcheck`, `shfmt`,
`taplo`, `uv`, and `yamlfmt` as pinned binaries, plus `render`, `validate`,
`pre-commit`, and `test` as Python entry points.

## The manifest

Each `[tool.<name>]` table produces `bin/<name>`. `method` decides the shape:

### `dotslash` — a prebuilt binary

```toml
[tool.shfmt]
method = "dotslash"
version = "3.13.1"
url = "https://github.com/mvdan/sh/releases/download/v{version}/shfmt_v{version}_{asset}"

[tool.shfmt.platforms]
linux-aarch64 = { asset = "linux_arm64" }
linux-x86_64 = { asset = "linux_amd64" }
macos-aarch64 = { asset = "darwin_arm64" }
macos-x86_64 = { asset = "darwin_amd64" }
```

`{version}` and the per-platform keys substitute into `url`. All four platforms
are required, because one rendered file has to work everywhere and dotslash picks
the entry at run time.

For an archive, add `format` (`tar.gz`, `zip`, `gz`) and `archive_path`, the path
to the binary inside it. Omit both for a raw binary download.

### `uv-run` — a Python entry point

```toml
[tool.validate]
method = "uv-run"
module = "toolshed.validator"
requirement = ["some-package>=1.0"]        # inline specs
requirements = ["python-validators"]       # named groups
```

The rendered wrapper passes every resolved spec to `uv run --with`. Declare
reusable sets as groups:

```toml
[requirements.python-validators]
packages = ["black", "pyupgrade", "yamllint"]
```

Groups may nest through their own `requirements` key. Specs resolve inline-first,
then by group, keeping declaration order and collapsing duplicates.

Add `args` for fixed arguments the module always needs. A path in `args` resolves
against the working directory, which makes that tool repo-local rather than
relocatable.

### `bun-run` — a JavaScript entry point

Set `entry` for a local script or `package` to run a published package through
`bun x`.

### `passthrough` — hand-written

`render` leaves the file alone but still checks that it exists and is executable.

## Adding a tool

```bash
# 1. Add the [tool.<name>] table to tools.toml.
# 2. Download the assets and record their digests.
./render pin <name>
# 3. Generate bin/<name>.
./render
# 4. Confirm the tree is consistent.
./validate
```

Bumping a version is the same, minus step 1's table: change `version`, re-pin,
re-render.

`render pin` needs network access and decides what bytes every consumer will
execute. Run it deliberately and read the `tools.lock.toml` diff.

`render update` does the version-bump half of that loop for you, for dotslash
tools only (a `uv-run` tool's `requirement` specs are floors `uv` resolves at
run time, so there is no version to check). It checks each named tool's
upstream GitHub releases (every dotslash tool, if none are named), and for
each one with a newer release: bumps `version` in `tools.toml`, re-pins, and
re-renders. It prints a report -- current version, newest available, and
`current`, `updated`, or `failed: <reason>` -- to stdout, or to a file with
`--report <path>`. A tool whose failure leaves nothing else to roll back (an
unsupported source, a network error, an asset that 404s after the bump) is
left exactly as it was found; the rest of the run continues.

```bash
./render update              # check and bump every dotslash tool
./render update shfmt taplo   # just these two
./render update --report bump-report.txt
```

## Why `bin/` is committed

`bin/` is generated and committed, like a lockfile. A consumer can clone and use
it with no render step, and a version bump shows up as a reviewable diff. The
`manifest-sync` validator fails if the two ever disagree, so the committed output
cannot drift from the manifest.

## Validation

`./validate` runs a file-validation suite over the repo. `--fix` applies the
fixes it can, `--dirty` limits it to staged files.

```bash
./bin/pre-commit --install --env TOOLSHED_SOURCE=.
```

installs it as a git pre-commit hook. `--env` seeds a variable the hook needs;
see [AGENTS.md](AGENTS.md) for why this repo needs that one.

The engine behind `validate` and `pre-commit` is
[`lint-trap`](https://github.com/chpatton013/lint-trap), a separate package
this repo pins like any other dependency (see `[requirements.lint-trap]` in
`tools.toml`). `.validator.toml` configures that package: it maps each
validator to the files it covers. Two validators are specific to this repo and
live in `validators/`:

- `manifest-sync` — `bin/` matches `tools.toml`.
- `manifest-pinned` — every dotslash tool has a digest for all four platforms.

Point `[validators] paths` at your own directory to add more. They merge with
`lint-trap`'s builtins, and a name collision is an error rather than a silent
shadow.

## Tool resolution

A rendered wrapper looks for its runner (`uv` or `bun`) in this order:

1. `$TOOLSHED_BIN_DIR`, if a wrapper managing a bin directory set it.
2. `PATH`.

It never looks in its own directory. A script that runs whatever sits beside it
executes anything that can be written there.

Validators that shell out to a pinned binary follow a contract `lint-trap`
implements: check `$LINT_TRAP_BIN_DIR`, then the repo's own `bin/`, then
`PATH`. A repo pins tools so every checkout formats code the same way, so
those pins win over a different version already on `PATH`.
