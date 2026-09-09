# Plan: extract the validator engine into its own repo

**Goal.** `toolshed/validator/` becomes its own repository and its own published
package, `lint-trap` (importable as `lint_trap`). This repo consumes it back as
a pinned dependency of the `validate`, `pre-commit`, and `test` tools, exactly
the way it already consumes `toolshed` itself, and keeps only its two
repo-specific validators in `validators/`.

**Approach.** D8 item 1 in
`.agents/workspace/design/toolshed-design-decisions.md`, which D6 already
prepared for: the engine/repo-specific split exists, and the registry already
merges builtins with `[validators] paths`. Read D4 (`override_env`), D6, D7, and
D10 before starting -- this plan reuses all four.

**Status.** Not started.

**Prerequisite.** Done: toolshed is published at `github.com/chpatton013/toolshed`
(public), v0.1.0 is cut, and CI has run against it. The two-repo pin this plan
relies on -- `lint-trap` pinning nothing of toolshed's, and this repo later
pinning a tagged `lint-trap` release -- now has a real tag to resolve on both
sides, so there is no bootstrapping order problem left to work around.

**Sequencing rationale.** T1 front-loads the only real design risk: a rendered
wrapper that carries *two* overridable requirement groups has never been
rendered or run, and no test covers it. T2--T5 stand the new repo up while this
repo stays green on its own copy of the engine. T6 is the single commit that
deletes the copy and repoints the manifest, so this repo is never half-migrated.

---

## What is already clean

An import audit of the current tree, so no task has to redo it:

- Nothing under `toolshed/validator/**` imports `toolshed.manifest`,
  `toolshed.render`, `toolshed.lock`, or `toolshed.pin`. The engine's only
  in-repo imports are `toolshed.validator.{base,config,registry,runner,tools}`.
- The only edges from `validators/` into the engine are
  `from toolshed.validator.base import ValidationResult, Validator` in both
  files. That is the plugin contract, and it is the direction that is supposed
  to exist.
- `validators/manifest_sync.py` and `validators/manifest_pinned.py` import
  `toolshed.{lock,manifest,render}`. Those stay here; they are what makes them
  repo-specific.
- `pathspec` is declared as a `toolshed` runtime dependency but is used only by
  `toolshed/validator/config.py` and
  `toolshed/validator/validators/file_size.py`. It moves out with the engine;
  `jinja2` is the renderer's only remaining dependency.
- `.validator.toml`, the `[validators] paths` key, and the registry's
  builtin-then-configured merge need no schema change. Only the synthetic module
  prefixes in `registry.py` (`toolshed.validator.validators`,
  `toolshed.validator.external.<name>`) carry the old package name, and nothing
  asserts on them.

## The one trap

`[requirements.python-validators]` must survive the extraction as an explicit
group. It is tempting to delete it and pin `lint-trap[validators] @ git+...`,
letting the engine's extra carry black, pyupgrade, and yamllint. That breaks the
D4 escape hatch: an `override_env` replaces its group's specs wholesale, so
`LINT_TRAP_SOURCE=../lint-trap` renders `--with ../lint-trap`, which installs
the local path with no extras and every third-party-backed builtin fails to
import. The comment already on that group in `toolshed.toml` says exactly this;
keep the group and keep the packages named unconditionally.

**Fact-check (open question 2, below).** `black`, `pyupgrade`, and `yamllint`
already prove the general case: `[requirements.python-validators]` is nothing
but `packages = ["black", "pyupgrade", "yamllint"]`, three plain PyPI packages
that have never heard of toolshed, have no `toolshed.toml`, and render no `bin/`.
`RunnerTool._walk` in `toolshed/manifest.py` and the `uv-run.sh.j2` template
(`toolshed/templates/uv-run.sh.j2`) treat a `[requirements.<group>]` entry as
nothing more than a `--with <spec>` list handed to `uv run --no-project`; `uv`
resolves each spec (a PyPI name, a version pin, or a `git+https://...` URL) on
its own. Nothing in the manifest schema, the renderer, or `RunnerTool`
distinguishes "a toolshed-based project" from "any installable Python package."
The one place toolshed *is* special is `[requirements.toolshed]`'s
`override_env = "TOOLSHED_SOURCE"` -- and that is D4's bootstrapping trick, not
a toolshed-specific requirement of the manifest format. `lint-trap` can use the
identical pattern (`override_env = "LINT_TRAP_SOURCE"`) as a plain package with
no `toolshed.toml` of its own. This confirms the owner's assumption in open
question 2: `lint-trap` is a plain `uv`-installable package, and this repo
still gets to pin and override it exactly the way it pins `black` or `toolshed`
today -- "toolshed-managed" describes how a *consumer* pins the package, not a
property the package itself needs to have.

---

## T1. Name the repo, and prove a two-override wrapper works

No files move. The name is `lint-trap` (see Open questions -- resolved). Render
a scratch manifest -- outside the repo, or in a temp dir -- for a `uv-run` tool
whose `requirements` list two groups that each declare an `override_env`.

Confirm, with the wrapper run from a directory that is not the repo:

- both conditional blocks render, in declaration order, with the fixed
  `uv_args` seeding intact (bash 3.2 constraint);
- neither variable set resolves both pinned specs;
- one set and the other not resolves one of each;
- `uv run --with <local path>` of a package with extras does **not** install
  those extras, which is the finding that justifies keeping
  `python-validators`.

**Done when:** the four cases above are observed, and a test asserting the
two-group render is added to `tests/test_render.py`. That test belongs to this
repo permanently -- it covers the renderer, not the engine.

## T2. New repo skeleton

`lint-trap` is a plain Python package: no `toolshed.toml`, no rendered `bin/`, no
toolshed self-hosting. Just `pyproject.toml` (hatchling, `requires-python
>=3.11`,`dependencies = ["pathspec>=0.12"]`,`[project.optional-dependencies]
validators = ["black", "pyupgrade", "yamllint"]`),`.gitignore`, a stub
`README.md`, and the empty package directory (`lint_trap/`). Mirror this repo's
packaging choices (hatchling, dependency shape) rather than inventing new ones,
but there is no manifest, no renderer, and no dogfooding to set up.

**Done when:** `uv run --with . python -c "import lint_trap"` succeeds in the
new repo.

## T3. Move the engine modules

Copy `base.py`, `config.py`, `registry.py`, `runner.py`, `tools.py`,
`__main__.py`, `validators/`, and `precommit/` into the new package, rewriting
`toolshed.validator.` to `lint_trap.` throughout. Update the two synthetic
module prefixes in `registry.py`. Leave this repo's copy in place -- it stays
green until T6.

Rename the environment variable `tools.py` reads from `TOOLSHED_BIN_DIR` to
`LINT_TRAP_BIN_DIR` (see Open questions -- resolved, no backwards-compatible
fallback), and promote its docstring: it is now a documented cross-repo
contract with whatever renders the wrappers, not an internal detail. This is a
distinct variable from `LINT_TRAP_SOURCE` (T2/T6, the `override_env` that
redirects *which `lint-trap` package* gets installed): `LINT_TRAP_BIN_DIR`
tells `resolve_tool()` at runtime where to find the pinned binaries (`biome`,
`shellcheck`, ...) that subprocess-backed validators shell out to. The two
never appear in the same conditional and must not be conflated in code or
docs.

**Done when:** `python -m lint_trap --help` works in the new repo and
`all_validators()` returns all 24 builtins.

## T4. Move the engine's tests

Four files move as-is with imports rewritten:
`tests/test_registry.py`, `tests/test_validator_config.py`,
`tests/test_tool_resolution.py`, `tests/test_precommit_install.py`. Note that
`test_registry.py` embeds validator source as a string -- its `_EXTRA` fixture
needs the import rewritten too. `test_tool_resolution.py` also needs its
`TOOLSHED_BIN_DIR` references renamed to `LINT_TRAP_BIN_DIR`.

Five stay here: `test_manifest.py`, `test_render.py`, `test_lock.py`,
`test_pin.py`, and `test_repo_validators.py`. The last one tests
`validators/manifest_*.py` through the registry, so after T6 it imports the
engine as an external dependency -- which is a feature: it becomes this repo's
integration test against the extracted package.

`lint-trap` runs these four moved files with whatever plain-Python tooling it
chooses -- a `Makefile` target, `uv run pytest` or `uv run python -m unittest`,
a bare CI step -- with no toolshed-managed `test` tool of its own to render.

**Done when:** the new repo's suite passes (by whatever command its own dev
loop uses), and this repo's remaining suite still passes with the four files
deleted.

## T5. New repo CI, release, and v0.1.0

Since `lint-trap` is a plain package (open question 2, resolved), this is a
plain Python package release: a CI workflow that installs the package, runs its
tests, and lints it with whatever plain-Python tooling it picks (no
`render`/`validate`/`pin` step, because there is no manifest to render or
validate); a release workflow that builds and publishes the wheel to PyPI (or
tags a `git+https` source the way `toolshed` itself is currently pinned, if
publishing to PyPI is out of scope for v0.1.0).

**Done when:** the tag is published and, from an empty directory,
`uv run --with "lint-trap @ git+<url>@v0.1.0" python -m lint_trap --help` works
with no local checkout.

## T6. Repoint this repo, and delete the copy

One commit:

- delete `toolshed/validator/`;
- add `[requirements.lint-trap]` to `toolshed.toml` with `packages = ["lint-trap @
  git+<url>@v0.1.0"]` and `override_env = "LINT_TRAP_SOURCE"`, keeping
  `python-validators` (see The one trap);
- `[tool.validate]` becomes `module = "lint_trap"` with `requirements =
  ["python-validators", "lint-trap", "toolshed"]` -- it still needs `toolshed`
  because `validators/manifest_*.py` import it at registry load time;
- `[tool.pre-commit]` becomes `module = "lint_trap.precommit"`, same three
  groups;
- `[tool.test]` gains `lint-trap` for `test_repo_validators.py`;
- `[tool.render]` is unchanged -- the renderer never touched the engine;
- rewrite the two imports in `validators/*.py`;
- drop `pathspec` from `dependencies` and the `validators` extra from
  `[project.optional-dependencies]` in `pyproject.toml`;
- re-render `bin/`, and set both `TOOLSHED_SOURCE` and `LINT_TRAP_SOURCE` in
  `ci.yml` and `release.yml`.

**Done when:** `TOOLSHED_SOURCE=. LINT_TRAP_SOURCE=<path> ./validate` is clean,
`./bin/test` passes, `./render --check` is clean, and with both variables unset
`./validate` resolves both pinned specs and still runs.

## T7. Documentation

- `README.md`: the wheel row in the release table no longer says "and the
  validator engine"; the Validation section names the engine repo (`lint-trap`)
  and explains that `.validator.toml` configures a package this repo merely
  pins; the Tool resolution section's second paragraph describes a contract the
  engine implements.
- `.agents/AGENTS.md` (root `AGENTS.md` is a symlink to it): add
  `LINT_TRAP_SOURCE` to the two-variable dev loop, update the Layout block, and
  repoint "a validator that shells out to a new binary" -- a *builtin* now
  belongs in the other repo, while a repo-specific one still lands in
  `validators/`.
- `design/toolshed-design-decisions.md`: append D11 recording the extraction,
  the mutual pin, and why `python-validators` survives; mark D8 item 1 done.
- `MEMORY.md`: one fact -- two override variables (`TOOLSHED_SOURCE`,
  `LINT_TRAP_SOURCE`), why, and the two-release dance an engine change now
  costs.
- `followup/tasks.md`: move this item to Completed; hand the "generalize the
  validator suite further" follow-up to the new repo's own task list, and note
  that "document reusing this repo's validators downstream" now has two halves.

**Done when:** a reader who has never seen either repo can tell from
`README.md` alone which repo owns a given validator.

---

## Resolved design notes

**The `dotslash` builtin validator stays in the engine (`lint-trap`).** It
hardcodes `biome` as the formatter it checks/fixes against and, today, `bin/*`
in this repo is the only known producer of dotslash manifests anywhere -- so
it is not obviously general. Keep it as a `lint-trap` builtin anyway, so it
ships for free to any consumer that wants it; revisit moving it into this
repo's `validators/` later if it turns out to be too repo-specific in
practice. T3 moves `dotslash.py` with the rest of `validators/` unchanged.

### Critical files for implementation

- toolshed/validator/ (base.py, config.py, registry.py, runner.py, tools.py, **main**.py, validators/, precommit/)
- validators/manifest_sync.py
- validators/manifest_pinned.py
- toolshed.toml
- .validator.toml
- pyproject.toml
- tests/test_registry.py, test_validator_config.py, test_tool_resolution.py, test_precommit_install.py, test_repo_validators.py
