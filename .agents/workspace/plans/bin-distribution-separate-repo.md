# Bin Distribution — Separate Repository (`toolbox`)

> **Deliverable (a)** of the "auto-bootstrapping executable-distribution system"
> followup. This plan is written to be built **from scratch by an agent with no
> prior context** of the dotfiles repo or this session. It describes a new,
> standalone public repository (working name `chpatton013/toolbox` — the owner
> picks the final name) that produces a portable `bin/` directory and publishes
> it as release tarballs. Any consuming repo (the dotfiles repo, `chiiiirrus`,
> future projects) downloads a release, extracts it onto `PATH`, and immediately
> has a pinned, hash-verified, cross-platform toolbox.
>
> A sibling plan, `bin-distribution-in-repo.md`, builds the *same capability*
> directly inside the dotfiles repo instead. The trade-off comparison at the end
> of this doc is the decision point between the two.

USER NOTE: Let's name it toolshed, since toolbox is already taken by a popular
opensource tool.

## Goals

1. **One manifest, many executables.** A single declarative source of truth
   (`tools.toml`) lists every tool the toolbox ships. A renderer reads it and
   emits one executable per tool into `bin/`, each generated from a template
   chosen by the tool's *bootstrap method*.
2. **curl/wget is the only host prerequisite.** Everything else (the tool
   runtimes, the language interpreters they need) is fetched on demand by the
   generated executables themselves — never assumed pre-installed.
3. **Pinned + hash-verified.** Every prebuilt binary is pinned to an exact
   version and content digest so a provision is reproducible and tamper-evident.
4. **Cross-platform.** macOS + Linux, on both `aarch64` and `x86_64`. The same
   `bin/foo` file works on every target; per-platform resolution happens at run
   time.
5. **Publishable releases.** CI renders `bin/`, validates it, and publishes a
   release tarball a consumer can download + extract onto `PATH`. The same repo
   can also build-and-publish *artifacts* (e.g. a wezterm fork binary) and pin
   them back into `tools.toml`.
6. **Self-validating.** A ported file-validator suite + pre-commit hook keeps the
   manifest, the generated `bin/`, and the repo's own sources honest.

## Prior art this is distilled from

The design generalizes two patterns already proven in the owner's `chiiiirrus`
repo, where `bin/*` executables come in exactly two hand-written flavors:

- **dotslash manifests** — a file whose shebang is `#!/usr/bin/env dotslash`
  followed by a JSON document describing, per platform, a release-asset URL, an
  archive `format`, the `path` to the binary inside the archive, a `size`, and a
  blake3 `digest`. dotslash (https://dotslash-cli.com) fetches, verifies, caches,
  and execs the real binary transparently. Used for prebuilt tools: `uv`, `bun`,
  `shfmt`, `shellcheck`, `biome`, `taplo`, `jq`, `gitleaks`, `rustfmt`,
  `yamlfmt`, `terraform`, etc.

  Example (`bin/uv`):

  ```
  #!/usr/bin/env dotslash

  {
    "name": "uv",
    "platforms": {
      "macos-aarch64": {
        "size": 20839135,
        "hash": "blake3",
        "digest": "fe05177d55ebc6455da370ac23ee9663ee970de73ea933b0f14d0668a5f7cadf",
        "format": "tar.gz",
        "path": "uv-aarch64-apple-darwin/uv",
        "providers": [
          { "url": "https://github.com/astral-sh/uv/releases/download/0.11.7/uv-aarch64-apple-darwin.tar.gz" }
        ]
      },
      "macos-x86_64": { ... },
      "linux-aarch64": { ... },
      "linux-x86_64": { ... }
    }
  }
  ```

- **runner wrappers** — a small bash script (with a symlink-resolving preamble)
  that `exec`s a language runner against an in-repo entrypoint. Used for tools
  written in Python/JS that need dependencies resolved on the fly. Example
  (`bin/validate`, condensed):

  ```bash
  #!/bin/bash --norc
  set -euo pipefail
  # ...resolve symlinks to find $here (the bin dir) and $repo_root...
  exec "$here/uv" run \
    --with-requirements "$repo_root/requirements-dev.txt" \
    python -m validator "$@"
  ```

  Note it calls `"$here/uv"` — the *toolbox's own* pinned uv (a dotslash file),
  not a system uv. Runner wrappers depend on prebuilt tools in the same `bin/`.

The new element (not present in `chiiiirrus`, where these files are all
hand-maintained) is the **manifest + renderer**: instead of hand-writing each
`bin/foo`, you declare it once in `tools.toml` and generate it. This makes
version bumps a one-line edit + `render`, and makes it trivial to add tools.

## Repository layout

```
toolbox/
  tools.toml                # THE manifest — every tool, its method + params
  render                    # the renderer executable (bash wrapper -> uv run)
  templates/                # one template per bootstrap method
    dotslash.json.j2
    uv-run.sh.j2
    bun-run.sh.j2
    passthrough             # (marker; passthrough tools aren't rendered)
  bin/                      # GENERATED — one executable per manifest tool
    uv                      # dotslash manifest (generated)
    bun
    shfmt
    validate                # uv-run wrapper (generated)
    pre-commit
    ...
    aws-node-shell          # passthrough (hand-written, committed as-is)
  toolbox/                  # the renderer + validator Python package
    __init__.py
    manifest.py             # parse + validate tools.toml
    render.py               # emit bin/* from templates
    pin.py                  # fetch assets, compute digests, update pins
    validators/             # ported file-validator suite (see below)
    runner.py
    registry.py
  entrypoints/              # runner-wrapper payloads (python modules / js)
    <tool>/...
  requirements.txt          # runtime deps for uv-run tools
  requirements-dev.txt      # dev/validator deps
  .validator.toml           # validator name -> include/exclude globs
  .github/workflows/
    ci.yml                  # render + validate on push/PR
    release.yml             # tag -> render, validate, tar, publish release
    build-artifacts.yml     # (optional) build wezterm fork etc., publish assets
  install.sh                # consumer-side installer (download + extract)
  README.md
  AGENTS.md
```

`bin/` is **committed** (generated-and-committed, like a lockfile) so a consumer
can also `git clone` + `PATH` without a render step, and so diffs are reviewable.
CI enforces that `bin/` is in sync with `tools.toml` (`render --check`).

## The manifest: `tools.toml`

One `[tool.<name>]` table per executable. `method` selects the template; the
remaining keys are method-specific. Keep the table list sorted by name (the
validator enforces this).

```toml
# ---- prebuilt binaries via dotslash ----------------------------------------
[tool.uv]
method  = "dotslash"
version = "0.11.7"
# {version}/{triple} substituted per platform from the tables below.
url     = "https://github.com/astral-sh/uv/releases/download/{version}/uv-{triple}.tar.gz"
format  = "tar.gz"
# path to the binary inside the archive; {triple} etc. substituted.
archive_path = "uv-{triple}/uv"
# platform -> substitution vars. Digests are filled by `render pin` (below),
# NOT hand-edited. Absent digests => "unpinned" (CI fails; pin first).
[tool.uv.platforms.macos-aarch64]  = { triple = "aarch64-apple-darwin" }
[tool.uv.platforms.macos-x86_64]   = { triple = "x86_64-apple-darwin" }
[tool.uv.platforms.linux-aarch64]  = { triple = "aarch64-unknown-linux-musl" }
[tool.uv.platforms.linux-x86_64]   = { triple = "x86_64-unknown-linux-musl" }

[tool.bun]
method  = "dotslash"
version = "1.3.12"
url     = "https://github.com/oven-sh/bun/releases/download/bun-v{version}/bun-{triple}.zip"
format  = "zip"
archive_path = "bun-{triple}/bun"
[tool.bun.platforms.macos-aarch64] = { triple = "darwin-aarch64" }
[tool.bun.platforms.macos-x86_64]  = { triple = "darwin-x64" }
[tool.bun.platforms.linux-aarch64] = { triple = "linux-aarch64" }
[tool.bun.platforms.linux-x86_64]  = { triple = "linux-x64" }

# ---- python tools via `uv run` ---------------------------------------------
[tool.validate]
method  = "uv-run"
module  = "validator"                      # python -m validator
requirements = ["requirements-dev.txt"]    # --with-requirements each of these

[tool.pre-commit]
method  = "uv-run"
module  = "validator.precommit"
requirements = ["requirements-dev.txt"]

# ---- node/js tools via `bun run` (or `bun x`) ------------------------------
[tool.somejs]
method  = "bun-run"
entry   = "entrypoints/somejs/main.ts"     # or: package = "prettier@3.3.0"

# ---- artifacts this repo builds itself (e.g. the wezterm fork) -------------
# Same shape as a dotslash tool, but its `url` points at THIS repo's own
# releases; build-artifacts.yml produces the asset and `render pin` fills digests.
[tool.wezterm]
method  = "dotslash"
version = "20260101-csi2031"
url     = "https://github.com/chpatton013/toolbox/releases/download/wezterm-{version}/wezterm-{triple}.tar.gz"
format  = "tar.gz"
archive_path = "wezterm/wezterm"
build   = "artifacts/wezterm"              # marks it as built-here (see below)
[tool.wezterm.platforms.macos-aarch64] = { triple = "macos-aarch64" }

# ---- hand-written scripts (not rendered) -----------------------------------
[tool.aws-node-shell]
method = "passthrough"                      # bin/aws-node-shell is committed as-is
```

**Platform keys** are the four dotslash platform strings the toolbox targets:
`macos-aarch64`, `macos-x86_64`, `linux-aarch64`, `linux-x86_64`. The renderer
maps the host's `uname -s`/`uname -m` to one of these; dotslash does the same at
run time.

USER NOTE: We need to make a change to the pattern of including requirements
files. I know you lifted that directly from chiiiirrus, but that only works
because there's a set of shared requirements that works for that entire repo. If
we're building a collection of generally available tools, we'll need to enable
much more specificity of requirements on a per-tool basis. Often related tools
share a set of the same reqs, so it makes sense for us to support a way to
define such a grouping and reference it in the tools where that's helpful.
Rather than reference separate files tracked in this repository, let's add a new
construct to tools.toml where we can define named requirements groups.
Individual uv-based tools should be able to specify a list of `requirement` for
inline dependencies, and a list of `requirements` for referenced group
dependencies. The render process should merge the two sources into a list of
arguments in the call to uv.

## The renderer: `render`

`render` is itself a `uv-run` wrapper (the same preamble pattern) that execs
`python -m toolbox.render`:

```bash
#!/bin/bash --norc
set -euo pipefail
# ...symlink-resolving preamble sets $here (bin dir) and $repo_root...
exec "$here/uv" run \
  --with-requirements "$repo_root/requirements-dev.txt" \
  python -m toolbox.render "$@"
```

`render` subcommands:

- `render` (default) — read `tools.toml`, and for each tool emit `bin/<name>`
  from `templates/<method>.*.j2`. `passthrough` tools are skipped (left as-is);
  their existence and executable bit are still validated. Rendered files get
  mode `0755`.
- `render --check` — render to a temp dir and diff against the committed `bin/`;
  exit non-zero on drift. CI uses this so a manifest edit without a re-render
  fails the build (the classic "generated file out of sync" guard).
- `render pin [tool...]` — for each dotslash/artifact tool, resolve every
  platform's `url`, download the asset, compute its `size` + blake3 `digest`, and
  write those back into a companion lockfile (`tools.lock.toml`). This is the one
  step that needs network + a trusted machine. It is the toolbox analogue of
  `chiiiirrus`'s hand-filled `size`/`digest` fields. Keeping digests in a
  separate `tools.lock.toml` keeps `tools.toml` hand-editable (versions only) and
  the lock machine-generated.
- `render add <name> --method dotslash --version X --url ...` — scaffold a new
  manifest entry (optional convenience).

### Per-method templates

**`templates/dotslash.json.j2`** — emits the dotslash shebang + JSON. Loops over
`platforms`, substituting `{version}`/`{triple}`/etc. into `url` and
`archive_path`, and pulling `size`/`digest` from the lockfile:

```jinja
#!/usr/bin/env dotslash

{
  "name": "{{ tool.name }}",
  "platforms": {
    {% for plat, vars in tool.platforms.items() %}
    "{{ plat }}": {
      "size": {{ lock[tool.name][plat].size }},
      "hash": "blake3",
      "digest": "{{ lock[tool.name][plat].digest }}",
      "format": "{{ tool.format }}",
      "path": "{{ tool.archive_path | sub(vars) }}",
      "providers": [ { "url": "{{ tool.url | sub(vars, tool.version) }}" } ]
    }{{ "," if not loop.last }}
    {% endfor %}
  }
}
```

(Emit through `biome format` — as `chiiiirrus`'s `dotslash` validator does — so
the JSON is canonically formatted and the `--check` diff is stable.)

**`templates/uv-run.sh.j2`** — emits the runner-wrapper bash. The symlink
preamble is verbatim boilerplate; only the `uv run` invocation is templated:

```jinja
#!/bin/bash --norc
set -euo pipefail
source="${BASH_SOURCE[0]}"
while [ -L "$source" ]; do
  dir="$(cd -P "$(dirname "$source")" && pwd)"
  source="$(readlink "$source")"
  [[ $source != /* ]] && source="$dir/$source"
done
here="$(cd -P "$(dirname "$source")" && pwd)"
repo_root="$(dirname "$here")"
exec "$here/uv" run \
{% for req in tool.requirements %}  --with-requirements "$repo_root/{{ req }}" \
{% endfor %}  python -m {{ tool.module }} "$@"
```

**`templates/bun-run.sh.j2`** — the same preamble, but `exec "$here/bun" run
"$repo_root/{{ tool.entry }}" "$@"` (or `bun x {{ tool.package }} "$@"`).

Adding a new bootstrap method = add a `templates/<method>.*.j2` + a branch in
`render.py` that knows which fields that method reads. The template set is the
extension point.

USER NOTE: The `$here` and `$repo_root` are a product of chiiiirrus's bin
directory not being on the PATH, and needing a way to resolve the file paths of
dependency tools and the requirements files. I'd prefer something more
generalized that didn't rely on packaging local dependency files. If we factor
in my earlier note about rendering out the requirements file contents into the
executables, then we are really just left with the dependency tool resolution,
which we can address in a couple of different ways:

1. Put this file's enclosing bin/ dir on the PATH in the preamble.
2. Require the user to manage their PATH, and potentially resolve that tool from the system if present.

I'm leaning towards (2) because (1) is a potential security vulnerability. But
maybe if there's a wrapper script responsible for managing the location and
contents of this bin/ directory, then (1) could be a safe and convenient
optional alternative.

## The validator suite (ported from `chiiiirrus`)

Port `chiiiirrus`'s `validator/` package near-verbatim; it is a clean, framework-
free file-validation engine:

- `toolbox/validators/*.py` — one class per validator, each a subclass of a
  `Validator` ABC with `name`, `check(file)`, optional `fix(file)`, `priority`,
  and a `Config`. Auto-discovered by `registry.py` (globs `validators/*.py`).
- `.validator.toml` — maps `[validator.<name>]` to `include_files` /
  `exclude_files` gitignore-style globs. `runner.py` fans work out across files
  (parallel), honoring the globs.
- `toolbox/__main__.py` — the `validate` CLI: `--fix`, `--dirty` (staged files
  only), `--profile`, file/dir args (dir args expand via `git ls-files`).
- `precommit.py` — the pre-commit entrypoint (`bin/pre-commit`); runs the suite
  in `--dirty --fix` mode on staged files, re-stages fixes.

Ship these validators (the ones relevant to a manifest+bin repo — a subset of
chiiiirrus's set, plus the manifest-specific ones):

| Validator | Target | Purpose |
| --- | --- | --- |
| `dotslash` | `bin/*` | biome-format the JSON body of dotslash manifests |
| `manifest-sync` | `tools.toml`, `bin/*` | **new**: assert `render --check` is clean (bin matches manifest) |
| `manifest-pinned` | `tools.lock.toml` | **new**: every dotslash/artifact tool has a digest for every target platform |
| `shellcheck`, `shfmt` | `bin/*` runner wrappers, `*.sh` | shell lint/format |
| `python-black`, `pyupgrade`, `python-*` | `*.py` | the renderer/validator sources |
| `taplo` | `*.toml` | format `tools.toml`/`.validator.toml` |
| `yamlfmt`, `yamllint` | `*.ya?ml` | the workflows |
| `keep-sorted` | `**` | keep the manifest tool list + `bin/` ordering sorted |
| generic | `**` | trailing-whitespace, trailing-newline, tabs, case-conflict, conflict-markers, file-size, filename-chars, unicode, executable-extension, symlink, gitleaks |

The `manifest-sync` and `manifest-pinned` validators are the new ones that make
the generated `bin/` trustworthy: you cannot merge a manifest change without the
corresponding `bin/` update, and you cannot ship an unpinned (un-hashed) tool.

USER NOTE: Copying the whole validator package into this repo is a good first
step while we're in the phase of standing things up, but I would like to
eventually pull the validator tool and the generally-useful validators into a
separate project that we track as an exported tool just like we do for our
wezterm fork. This repo should then have its own repo-specific validators
implemented in a validators/ directory, and we'll need the validator tool to be
runtime-configured to merge its set of builtin validators with the ones defined
in this repo.
USER NOTE: And extending this idea a little farther: when we start using the
tools in this repo in other projects, there might be situations where we need a
project-specific tool that we don't really want to incorporate into this shared
repository, but we do want to leverage the tool definition and rendering
capabilities of this repo. We should be able to invoke the render tool on
separate instances of a tools.toml spec file. Tying back into the earlier note
about managing dependency files for our tools with an exec wrapper, that wrapper
would need to seamlessly account for this federated bin/ directory complexity.
USER NOTE: And going one step farther than that; if we did all that, then users
of the tool renderer would also want to be able to incorporate the validators
defined by this repo. So we'll want to think about creating a separate release
artifact to enable that sort of integration.

## Release / publish flow

`.github/workflows/release.yml`, triggered on a `v*` tag (or manual dispatch):

1. Checkout.
2. `bin/uv` is already committed → `./render --check` (fail if `bin/` drifts).
3. `./validate` (whole-repo; fail on any finding).
4. `./validate` confirms all tools pinned (via `manifest-pinned`).
5. Build the tarball. The `uv-run` wrappers resolve `$repo_root` relative to
   `bin/`, so the tarball must preserve that layout and include everything they
   reference at run time (`toolbox/`, `requirements*.txt`, `entrypoints/`,
   `tools.toml`, `tools.lock.toml`). Simplest correct answer: **tar the whole
   repo minus `.git`** and let consumers put `bin/` on `PATH`.
6. Compute a `SHA256SUMS` for the tarball.
7. `gh release create` with the tarball + checksums attached.

USER NOTE: Based on the earlier note about not wanting to include dependencies
on sibling files, I think we don't have a strong reason to tar the entire
repository. We'll probably want to fork into different release artifacts: one
for just the rendered bin/ directory (potentially with entrypoints/ if that's
needed, but I haven't seen an explanation of what it would include to be sure),
one for the tools someone could use to package their own bin/ directory just for
their project, one for the validators this repo defines for users who are
defining their own tool definitions (maybe that should be included in the
release with the rendering tools?), etc.

**Artifact builds** (`.github/workflows/build-artifacts.yml`, optional/later):
for tools marked `build = "artifacts/<name>"` (e.g. the wezterm fork), a matrix
job builds the binary per platform, uploads it as a release asset under a
per-artifact tag (`wezterm-<version>`), then a maintainer runs `render pin
wezterm` locally (or a follow-up job does) to fill `tools.lock.toml` and commit.
This is how the toolbox "hosts the helpers for building the wezterm fork and
anything else the user wants to build + publish."

USER NOTE: I don't think this repo should be responsible for building releases
for projects that it references, unless those projects are actually tracked
within this repo. Our wezterm fork, for example, should be hosting its own
releases that we just reference. Potentially we might want to store the tools
used to build and publish those releases in this repo, but that would be the
case if the forked repo didn't already have existing dev tooling to do that
easily.

## How a consumer integrates

Two integration modes; a consumer picks one.

**Mode 1 — release tarball onto PATH (the headline use case).** Ship a small
`install.sh` (also hostable from the toolbox raw URL) that a consumer's own
bootstrap calls:

```bash
# install.sh <version> [dest]
#   Downloads toolbox-<version>.tar.gz + SHA256SUMS, verifies, extracts to
#   $dest (default ~/.local/share/toolbox/<version>), and prints the bin dir.
TOOLBOX_VERSION="${1:-latest}"
DEST="${2:-$HOME/.local/share/toolbox}"
base="https://github.com/chpatton013/toolbox/releases/download/$TOOLBOX_VERSION"
curl -fsSL "$base/toolbox-$TOOLBOX_VERSION.tar.gz" -o "$tmp/t.tgz"
curl -fsSL "$base/SHA256SUMS" -o "$tmp/sums"
( cd "$tmp" && shasum -a 256 -c --ignore-missing sums )   # verify
mkdir -p "$DEST/$TOOLBOX_VERSION"
tar xzf "$tmp/t.tgz" -C "$DEST/$TOOLBOX_VERSION" --strip-components=1
echo "$DEST/$TOOLBOX_VERSION/bin"                          # add this to PATH
```

The consumer adds the printed `bin` dir to `PATH` (in their shellrc, or a
symlink farm into `~/.local/bin`). From then on `uv`, `bun`, `shfmt`, `validate`,
etc. are all resolvable, self-fetching, and pinned. Because the tools self-fetch
via dotslash/uv on first run, the tarball itself is tiny (text manifests +
wrappers + the renderer/validator sources) — the heavy binaries download lazily
and cache under dotslash's cache dir.

USER NOTE: I like this script, but it will need to be generalized if we want to
enable customers to publish their own tools.

> **Prerequisite:** dotslash must be on the consumer's `PATH` for the dotslash
> manifests to be executable (the `#!/usr/bin/env dotslash` shebang). Two
> options: (a) the consumer's bootstrap installs the dotslash runtime first
> (fetch the release binary — it is the one tool that cannot itself be a dotslash
> file, chicken/egg); or (b) the toolbox tarball includes a `bin/.dotslash`
> runtime per platform and the runner wrappers exec it explicitly. Recommend
> (a): document "install dotslash, then run install.sh" — matching how
> `chiiiirrus` documents `scripts/bootstrap/dotslash.sh`.

USER NOTE: We could include a bootstrap script in this repo that simplifies
idempotent dotslash installation.

**Mode 2 — git submodule / vendored clone.** A consumer that wants to track the
toolbox at a git SHA adds it as a submodule and puts `toolbox/bin` on `PATH`
directly. No release needed; `render` is available for local bumps. Heavier
coupling; use only if the consumer wants to co-develop tools.

USER NOTE: I'm not personally a fan of git submodules, but other people should
be able to use this as a submodule if they want. We could also just support a
first-class usage pattern where a user has the repo checked out locally, whether
it be a submodule or not. That would give us the most flexibility.
USER NOTE: I like having both of these modes available based on how heavily
involved in tool development the user is. I can imagine there would be cases
where a user just wanted mode 1, just wanted mode 2, or wanted mode 1 for some
tools but mode 2 for others.

## Build order (for the implementing agent)

1. Create the repo skeleton + `AGENTS.md` (shell/py conventions: `#!/bin/bash
   --norc`, `set -euo pipefail`, the symlink preamble; sorted TOML tables).
2. Hand-write the seed `bin/uv` dotslash manifest (bootstrap chicken/egg: the
   renderer runs via `uv`, so `uv` must exist first). Everything else is
   generated.
   - USER NOTE: We can use the `uv` tool installed on the system instead.
3. Write `toolbox/manifest.py` (parse + schema-validate `tools.toml`).
4. Write the three templates + `toolbox/render.py` (`render`, `--check`, `pin`).
5. Populate `tools.toml` with the initial tool set (uv, bun, shfmt, shellcheck,
   biome, taplo, jq, yamlfmt, plus `validate`/`pre-commit`/`render` uv-run
   tools). `render pin` to fill `tools.lock.toml`. `render` to emit `bin/`.
6. Port the `validator/` suite + `.validator.toml`; add `manifest-sync` and
   `manifest-pinned` validators. `./validate --fix` until clean.
7. Add `ci.yml` (render --check + validate) and `release.yml`.
8. Write `install.sh` + README consumer docs.
9. (Later) `build-artifacts.yml` for the wezterm fork.

## Verification

- `./render && git diff --exit-code bin/` — rendering is idempotent and
  committed output matches.
- `./render --check` passes on a clean tree; deliberately bump a `version` in
  `tools.toml` without re-rendering → `--check` fails (drift caught).
- On a fresh machine with only curl + dotslash: run `install.sh`, add `bin/` to
  PATH, run `uv --version`, `shfmt --version`, `validate --help` — each
  self-fetches and runs. Confirms the tarball is self-contained.
  - USER NOTE: We can test on any machine simply by overriding PATH
- Remove a digest from `tools.lock.toml` → `manifest-pinned` fails → CI red.
- Corrupt a dotslash digest → the tool refuses to run (dotslash hash mismatch),
  proving tamper-evidence.

## Trade-offs vs. the in-repo version (deliverable b)

| Dimension | **Separate repo** (this plan) | **In dotfiles repo** (`bin-distribution-in-repo.md`) |
| --- | --- | --- |
| Reuse across projects | yes — `chiiiirrus`, dotfiles, future repos share one release | no — toolbox entangled with dotfiles; other repos can't easily consume it |
| Consumer coupling | Loose: download a versioned tarball, pin a version | Tight: the tooling *is* the dotfiles repo |
| Release/versioning | First-class: tagged releases, checksums, rollback | dotfiles has no release cadence today; you'd add one just for this |
| Bootstrap complexity | Consumer needs an extra fetch step (install.sh) before setup | Already present when the repo is cloned — zero extra fetch |
| Dev-hygiene CI | Two repos to wire CI into | One repo; directly satisfies the `dev-hygiene-ci.md` followup in place |
| Maintenance surface | A whole extra repo (its own CI, README, releases) | No new repo; fewer moving parts |
| wezterm-fork build hosting | Natural home; publishes reusable release assets | Possible, but bloats the dotfiles repo with build infra |
| Blast radius of a bad bump | Contained; consumers pin and upgrade deliberately | A bad render can break provisioning on next `git pull` |

**Recommendation heuristic:** choose the separate repo if the toolbox is meant to
serve *multiple* repos (the owner already has `chiiiirrus` doing the same thing
by hand — strong signal) and you want deliberate, versioned upgrades. Choose
in-repo if the toolbox is really only ever for the dotfiles machines and you
value one-clone-has-everything simplicity over reuse. The two are not mutually
exclusive forever: you can start in-repo (b) and later extract to a separate repo
(a) once a second consumer appears — the manifest + renderer + templates move
wholesale.

- USER NOTE: On bootstrap complexity: Even with a separate repo, the dotfiles
  bootstrap script could handle this auatomatically, so it shouldn't actually
  result in a more complicated user experience.

## Risks / open questions

- **dotslash runtime chicken/egg.** dotslash cannot be a dotslash file. The
  consumer (or `install.sh`) must fetch the dotslash release binary first. Decide
  whether `install.sh` also installs dotslash, or documents it as a prerequisite.
  - USER NOTE: Reuse the bootstrap pattern from dotfiles
- **`render pin` trust + network.** Digest computation downloads release assets;
  run it on a trusted machine and review the `tools.lock.toml` diff. Consider a
  CI job that re-downloads and asserts the committed digests still match upstream
  (detects upstream re-tags / supply-chain surprises).
- **Tarball completeness.** `uv-run` wrappers resolve `$repo_root` relative to
  `bin/`; the tarball must preserve that relative layout (recommend taring the
  whole repo minus `.git`). Verify a runner tool works from an extracted tarball,
  not just from a git checkout.
- **Naming.** `toolbox` is a placeholder; the owner picks the repo name. It
  affects the `url` for self-built artifacts and `install.sh`'s base URL.
- **Reconcile with `chiiiirrus`.** `chiiiirrus`'s `bin/` is hand-written; if the
  intent is for `chiiiirrus` to *consume* the toolbox, its bespoke `bin/aws-*`
  scripts (project-specific) stay local while the generic tools (`uv`, `bun`,
  `shfmt`, the validator suite) come from the toolbox release. Confirm which
  tools are "generic" (toolbox) vs "project-local" before migrating chiiiirrus.
- **Version-bump automation.** A future `update` command (or scheduled workflow)
  could check upstreams for newer releases and open a PR bumping `version` +
  re-pinning — mirrors the dotfiles repo's existing `update-source-versions`
  habit.
