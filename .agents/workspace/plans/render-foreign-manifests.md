# Plan: a module system for toolshed manifests

**Goal.** A `toolshed.toml` becomes a *module*: it declares its own tools and
requirements groups, and it may declare dependencies on other modules and select
tools out of them under names of its choosing. `render [manifest]` renders one
`bin/` from the whole import graph, so a project can assemble a toolchain from
somebody else's manifest plus a few tools of its own without contributing
anything upstream and without copying tables between files. Name collisions
between two imported modules are resolved in the manifest, by aliasing, before
anything is rendered.

**Approach.** Decision D8 item 2 in
`.agents/workspace/design/toolshed-design-decisions.md`, expanded from
"`--manifest <path>`" into the module system that question was really asking
for. Read D2, D3, D4 and D10 first:

- D2 (requirements live in the manifest, never in a sibling file) is why an
  imported tool can be made self-contained at all -- everything it needs is
  parseable text in the module that defines it.
- D3 (no path arithmetic in rendered output) is why a module graph is a
  *render-time* concept only. Import sources are resolved and their contents
  baked into `bin/` when `render` runs; no rendered file learns that it came
  from an imported module, or where that module lived.
- D4 (`override_env`) has to survive an import: a downstream module importing
  this repo's `render` tool must still get a wrapper that honors
  `TOOLSHED_SOURCE`.
- D10 (two consumer modes, and mixing them) is the boundary of the module
  system. Aliasing resolves collisions *within one render*. Across two
  independently rendered `bin/` directories on one `PATH`, `PATH` order still
  decides, and that stays true (T7).

**Status.** Not started, and nothing blocks it. The repo is published at
github.com/chpatton013/toolshed (public), v0.1.0 is tagged and released, CI and
the release workflow have both run, and `toolshed.toml` pins
`toolshed @ git+https://github.com/chpatton013/toolshed@v0.1.0`, so a foreign
module can drive the released `bin/render` with no local checkout.

**Sequencing rationale.** T1 is the path layer, and it comes first because every
later task needs to know where a manifest's lock and `bin/` are without being
told: once lock and bin default to siblings of the manifest, "render a manifest
that lives elsewhere" stops being a special case and the module tasks can assume
it. T2--T4 build the grammar, then the graph, then the merge, in that order
because each is separately testable and only T4 touches how tools reach the
renderer. T5 is locks, which is where the design has the most room to be wrong
and so gets its own task rather than riding along in T4. T6--T7 are the
collision surface, which is policy rather than mechanism and stays independent
of everything above it.

---

## What is already true

Worth knowing before starting, so no one re-discovers it:

- `toolshed/render.py` derives all three paths from one `--root` in `_paths()`:
  `root/toolshed.toml`, `root/toolshed.lock.toml`, `root/bin`. There is no cwd
  assumption beyond `--root`'s default. T1 replaces this wholesale.
- Nothing in `toolshed/manifest.py` interprets a value as a filesystem path
  relative to the manifest. Requirements are package specs (D2); `url`,
  `archive_path`, `module`, `package` are all location-free. `import`'s `source`
  will be the first manifest key that *is* a path, so it is also the first key
  that has to be resolved relative to the file it was read from.
- `parse_manifest` takes text, not a path, and rejects unknown top-level keys
  against `frozenset({"tool", "requirements"})`. Module loading needs a
  path-aware entry point above it; keep the text-level parser for one module in
  isolation, since that is what makes T2 testable without a filesystem.
- Requirements groups are already resolved through `Manifest.requirements` by
  name, with cycle detection in `RunnerTool._detect_cycle` and order-preserving
  de-duplication in `_resolve`. T4 reuses all of it by namespacing imported
  group names rather than by flattening specs.
- Group names never appear in rendered output. `render_tool` passes only
  resolved specs and `override_env` variable names to the templates, so an
  internal namespaced group name cannot leak into `bin/`.
- Two keys resolve against the *working directory* at run time, not against the
  manifest: `uv-run` `args` (documented in the README as making a tool
  repo-local) and `bun-run` `entry`. This repo's `test` tool relies on it
  (`args = ["discover", "-s", "tests", "-t", "."]`). Importing such a tool into
  another module does not change the semantics, which means an imported tool
  with `args` is only usable from a directory that satisfies them. That is a
  docs problem (T8).
- `templates/uv-run.sh.j2` guards its runner with
  `[ -x "$TOOLSHED_BIN_DIR/uv" ]` and falls back to `PATH`. That guard is what
  makes mixing work: a consumer can point `TOOLSHED_BIN_DIR` at their own
  `bin/`, which has no `uv` in it, and the wrapper still finds a release's `uv`
  on `PATH`. Nothing asserts it today. T7 does.
- The lock is keyed by tool name only (`[tool."<name>"."<platform>"]`), with no
  notion of where a tool was declared. T5 is where that meets renaming.
- Making the manifest validators (`manifest-sync`, `manifest-pinned`,
  `toolshed/validator/tools.py`) work against a non-default layout is **not** in
  this plan. That is tracked with the validator-engine extraction.

## Vocabulary

Fixed for the rest of this document, and for the docs in T8:

- **module** -- one `toolshed.toml`. It defines tools and requirements groups, and
  may import other modules.
- **root module** -- the module named on the `render` command line. Its `[paths]`
  decide where the lock and `bin/` are; every other module in the graph
  contributes definitions only.
- **import alias** -- the symbolic name a module gives an import
  (`[import.<alias>]`). Local to the importing module, and never visible in
  rendered output.
- **local name** -- the name a tool holds in the importing module's tool set,
  and therefore the filename it takes in `bin/`. Equal to the tool's own name
  unless renamed.
- **exports** -- the tool names a module makes available to an importer.

---

## T1. Paths come from the manifest, and the CLI is a positional

Replace `_paths(root)` with a frozen `RenderPaths` dataclass
(`manifest`, `lock`, `bin_dir`, all absolute) and a resolver. Three layers, in
increasing precedence:

1. **Defaults, from the manifest's location.** `lock` is the manifest's name
   with its final `.toml` replaced by `.lock.toml` (`toolshed.toml` ->
   `toolshed.lock.toml`, so one directory can hold two manifests without their
   locks colliding). `bin_dir` is `bin` beside the manifest.
2. **The manifest's own declaration.** A new top-level table:

   ```toml
   [paths]
   lock = "toolshed.lock.toml"
   bin = "bin"
   ```

   Either key may be relative -- resolved against the directory holding the
   manifest that declared it, never against the working directory -- or
   absolute. Both keys are optional; the table is optional. Add `paths` to the
   top-level allowed keys and give it a `_PATHS_KEYS` frozenset like
   `_GROUP_KEYS`, so a typo is an error rather than silence.
3. **CLI flags.** `--lock <path>` and `--bin <path>`, resolved against the
   working directory like any other command-line path.

Only the **root** module's `[paths]` is read. An imported module's `[paths]` is
ignored, not an error: a module that is also rendered standalone will have one,
and importing it must not drag its output locations along.

The CLI surface becomes:

```
render [manifest] [--lock PATH] [--bin PATH] [--check] [--no-shadow]
render [manifest] [--lock PATH] pin [tools...]
```

- `manifest` is positional. A file is used as-is; a directory is joined with
  `toolshed.toml`. Default `.`, so bare `render` in a repo root behaves as today.
- `--root` is gone. No sugar, no deprecation shim: pre-1.0, and its only
  consumer is this repo's own `bin/render`, whose behavior the new default
  already covers.

**Argparse trap, and the fix.** An optional positional on the root parser
*before* a subparser does not work: `render pin jq` makes argparse bind `pin` to
`manifest` and then fail on `jq` with an invalid-choice error. Split `argv`
before parsing -- scan for the first token that is not a flag or a flag's value,
and if it names a subcommand, no manifest was given. Keep that in one small
helper with its own test; do not attempt to express it in argparse.

Error messages must name the resolved absolute path. With a foreign module the
reader can no longer assume it is this repo's own file.

**Done when:** `render /elsewhere/foo.toml` writes `/elsewhere/bin/` reading
`/elsewhere/foo.lock.toml`; `render /elsewhere` resolves
`/elsewhere/toolshed.toml`; a `[paths]` table with `lock = "config/toolshed.lock.toml"`
and `bin = "tools/bin"` puts both there; the same manifest rendered with `--bin
out/` puts `bin/` in `out/` and leaves the lock where `[paths]` said; an absolute
`[paths] bin` is honored unchanged; an unknown key under `[paths]` is a
`ManifestError`; `render pin jq`, `render . pin jq`, and `render sub/ pin` all
parse as intended; `--root` is rejected as an unknown flag; a missing manifest
reports the absolute path it looked for; and this repo's `./render` and
`./render --check` still behave exactly as before with no `[paths]` table added
to `toolshed.toml`.

## T2. The `[import.<alias>]` grammar

Grammar and validation only -- no loading, no merging. `parse_manifest` learns a
third top-level table and returns it on `Manifest`:

```toml
[import.upstream]
source = "vendor/toolshed/toolshed.toml"
tools = ["jq", "shfmt", "uv"]
rename = { jq = "upstream-jq" }
```

- `source` (required) is a path to a module. Relative resolves against the
  directory holding the manifest that declared it; absolute is allowed. A
  directory is joined with `toolshed.toml`, same rule as the CLI positional.
  Filesystem paths only in this plan -- see Open questions 1.
- `tools` (required, non-empty) lists the tool names to import. Nothing is
  imported implicitly: an import with no `tools` is an error, not a wildcard.
- `rename` (optional) maps a name in `tools` to the local name it takes. A key
  absent from `tools` is an error, so `tools` stays the single answer to "what
  does this import bring in".
- `[import]` keys are sorted by alias, like `[tool]` and `[requirements]`
  (`_require_sorted`).

Represent it as a frozen `Import` dataclass (`alias`, `source`, `tools`,
`rename`) and add `imports: dict[str, Import]` to `Manifest`. Validate within
one module: unknown keys, empty `tools`, a duplicate entry in `tools`, a
`rename` key not in `tools`, two `rename` values that collide with each other,
and a rename value that collides with a locally defined tool name. All raise
`ManifestError` naming the alias.

`source` is stored as written, unresolved. Resolution needs the manifest's own
path, which `parse_manifest` does not have; that belongs to T3.

**Done when:** `tests/test_manifest.py` covers each error above by message, a
well-formed `[import]` table round-trips into `Manifest.imports`, a manifest
with no `[import]` table yields an empty dict, and the existing manifest tests
still pass unchanged.

## T3. Load the module graph

A new `toolshed/module.py`: given the root manifest path, produce the ordered
list of `(Import, Manifest, pathlib.Path)` the root depends on, transitively.

- `load_module_graph(path)` resolves and normalizes every `source` (absolute,
  symlinks resolved) and walks depth-first in declaration order.
- **Cycles are a `ManifestError`** naming the chain of resolved paths, in the
  spirit of `RunnerTool._detect_cycle`'s message. A module importing itself is
  the degenerate case and must report the same way.
- **Diamonds parse once.** Cache parsed modules by resolved absolute path, so A
  importing both B and C, which both import D, reads D once. Each import site
  still applies its own `tools` selection and `rename`.
- **A module's exports are every tool name in its own resolved tool set** --
  what it defines plus what it imports, under their local names there. That is
  what makes a curated bundle module possible: a module whose whole content is
  imports is still importable. See Open questions 3.
- An imported module is validated only as far as the import needs. A name in
  `tools` that the module does not export is a `ManifestError` naming the alias,
  the missing name, and the resolved source path. A tool the module defines but
  nobody imported is never rendered, and never has to be pinned or even
  renderable.
- A missing or unreadable `source` reports the resolved absolute path and the
  alias that asked for it.

**Done when:** `tests/test_module.py` covers a two-level chain, a diamond
(asserting the shared module parses once, via a counting loader or a spy), a
direct cycle, an indirect three-module cycle, a self-import, a missing `source`
file, and a `tools` entry the source does not export -- each error message
naming both the alias and the resolved path.

## T4. Merge the graph into one tool set

Also in `toolshed/module.py`: `resolve_manifest(path) -> Manifest`, the function
`render` calls in place of `load_manifest`. It returns an ordinary `Manifest`
whose `tools` dict is the whole graph flattened, so `write_bin`, `check_bin`, and
every template stay untouched.

Per import, in declaration order:

- Take the selected tools from the imported module's resolved tool set, rebind
  each to its local name, and record its **origin** -- the resolved path of the
  module that *defined* it and the name it holds there. Add that as an optional
  `origin` field on `Tool`, `None` for a locally defined tool. T5 needs it for
  lock lookup, and the error messages in this task need it to be legible.
- **Requirements groups are module-private.** An imported `uv-run` tool keeps
  its `requirements` list, but every group name in it is rewritten to an
  internal namespaced form, and the defining module's groups are copied into the
  merged `Manifest.requirements` under those namespaced names. Consequences
  worth stating plainly: two modules may both define a `python-dev` group with
  no collision and no need to alias anything; an importer cannot reference an
  imported group by name; and D4's `override_env` survives an import untouched,
  because `overridable_requirements` walks the same structure it always did. Use
  a separator that cannot appear in a hand-written group name in the merged
  manifest, and assert in a test that no namespaced name reaches rendered text.
- **A collision is a `ManifestError`,** naming both claimants by origin and
  suggesting `rename`. This is the whole point of aliasing: two modules that
  each define `jq` must produce two distinct filenames in one `bin/`, and the
  author says which. A local definition does not silently win over an import;
  the author drops it from `tools` or renames one of the two.
- **One exception:** the same origin (same defining module path, same source
  name) arriving twice under the same local name de-duplicates silently. That is
  the diamond case, and both paths would render byte-identical text.
- **Importing a `passthrough` tool is an error.** Nothing renders a passthrough
  file; it is a hand-written file expected to exist in the rendering module's
  `bin/`, which an import cannot supply. Say so in the message.
- The importer cannot override an imported tool's fields. Selection and renaming
  are the only operations. See Open questions 4.

Sanity check the invariant D3 rests on while here: nothing in the merged tool set
carries the resolved source path of the module it came from anywhere that can
reach a template. `origin` is render-time metadata.

**Done when:** a tmpdir graph where two modules each define `jq` fails with a
message naming both origins, and passes once one is renamed; the renamed tool
renders to `bin/upstream-jq`; a `uv-run` tool imported from a module whose
requirements group carries `override_env` renders the same conditional block it
renders in its own module; two modules' identically named requirements groups
both resolve correctly in one render; importing a `passthrough` tool errors; a
diamond that reaches the same tool twice renders one file; and a test asserts no
rendered text in the merged case contains any module's directory, any import
alias, any namespaced group name, or the string `toolshed.toml`.

## T5. Locks across a module graph

Only the root module's lock file is written, and it is the only lock the CLI's
`--lock` names. But an imported dotslash tool needs a pin, and its pins already
exist in its own module's lock, reviewed by whoever maintains that module.

- **Reading:** resolve pins for an imported tool from the *defining module's*
  lock (found by that module's own `[paths] lock`, else the sibling default),
  keyed by the tool's **source** name. The root lock may still carry an entry
  under the tool's **local** name, and that wins. So an upstream owns its
  digests by default and a consumer can override one deliberately.
- **Writing:** `render pin <name>` writes the root lock under the local name --
  an explicit, reviewable override recorded in the consumer's own repo. It never
  writes another module's lock.
- **Pruning:** `Lock.restricted_to` currently drops pins for tools the manifest
  no longer declares. It must key off local names in the merged tool set, or
  every override for an imported tool disappears on the next pin.
- With no arguments, `render pin` pins every dotslash tool that is unpinned
  after the merge -- which is normally none of the imported ones. It must not
  silently re-pin an imported tool that upstream already pinned.
- The `manifest-pinned` invariant still has to hold post-merge: every dotslash
  tool in the merged set needs all four platforms from somewhere. An imported
  tool whose upstream lock is incomplete is a `RenderError` naming the lock file
  that fell short, not the consumer's own.
- A renamed dotslash tool renders `"name": "<local name>"` in its dotslash JSON,
  since that field describes the file being written. Assert it, so nobody
  "fixes" it back to the source name later.

**Done when:** a tmpdir root module importing a dotslash tool renders it using
digests from the imported module's lock with no entry in the root lock; adding a
root-lock entry under the local name overrides it; `render pin <local name>`
writes the root lock and leaves the imported module's lock byte-identical
(assert the second half -- silently rewriting somebody else's lock is the
failure mode that matters); a bare `render pin` on a fully pinned graph writes
nothing; an imported tool missing one platform reports the imported lock's path;
and `render <root> pin sometool` never touches this repo's own
`toolshed.lock.toml`.

## T6. `--no-shadow`, and `render resolve`

Both surfaces answer the same question -- what else on `PATH` answers to a name
this render is about to claim -- so implement one walker and give it two faces.

`shadowed_names(names, bin_dir)`: for each name, every directory on `PATH`
holding an executable of that name, excluding `bin_dir` itself, with each
candidate labelled toolshed-rendered or not. Rendered output is detectable
without executing anything: the `#!/usr/bin/env dotslash` shebang, or the
generated-by header line the shell templates emit.

- `--no-shadow` makes `render` exit non-zero if any name in the merged tool set
  is already resolvable elsewhere on `PATH`, listing each name and the path that
  would shadow it. **It applies with and without `--check`** -- it is an
  independent gate, not a mode of `--check`. Off by default, because a render's
  outcome must not otherwise depend on the renderer's environment. It is an
  error to combine it with `pin`, the same way `--check` already is.
- `render resolve [tool...]` reports rather than fails: for each name, every
  candidate directory, which one wins, and which are toolshed-rendered. With no
  arguments it lists only names with more than one candidate. This is the
  diagnostic half of `--no-shadow`, and it is what turns "which `jq` will run"
  from a guess into a command.

**Done when:** on a tmpdir `PATH` holding two rendered bin directories,
`render resolve` names every duplicate, its winner, and each candidate's
rendered/not label; `--no-shadow` exits non-zero on the same setup and zero once
the shadowing directory leaves `PATH`; `--no-shadow --check` fails on a shadow
even when `bin/` is otherwise in sync; a name resolvable only inside the target
`bin_dir` is not reported as shadowed; and `--no-shadow` with `pin` exits 2.

## T7. The cross-bin-directory story

The module system resolves collisions **within one render**. It says nothing
about a consumer whose `PATH` holds a release's `bin/` and their own rendered
`bin/`, which is D10's mixing mode and stays supported. Keep the two clearly
apart, in the docs and in the tests:

**Within one module graph: alias.** Two imported modules that each define `jq`
cannot both write `bin/jq`, so T4 makes it an error and the author renames one.
Deterministic, reviewable, independent of anybody's environment.

**Across independently rendered bin directories: `PATH` order.** It is already
the rule, it needs no code, and D3 is what makes it correct -- a wrapper holds no
reference to its own location, so whichever copy the shell finds first behaves
identically to any other copy of the same rendered text. A consumer who wants to
override a released tool puts their own `bin/` earlier on `PATH` and renders only
what they mean to override. `--no-shadow` and `render resolve` (T6) are how they
see it happening.

**No exec wrapper.** D8's wording anticipates one; the owner's direction is to
start with `PATH` order and add a wrapper only if something turns out to need it.
The case against, recorded so it does not have to be re-argued: a
`toolshed exec <tool>` searching a `TOOLSHED_BIN_PATH` list only helps callers
who go through it, and everything that matters -- a Makefile, a git hook,
another wrapper's `$uv` -- invokes tools by bare name through `PATH`, so the
wrapper would be bypassed in exactly the cases where a collision bites.

Also lock down the D10 mixing invariant, which nothing asserts today: a foreign
`bin/` containing one `uv-run` wrapper and no `uv`, `TOOLSHED_BIN_DIR` pointed at
that foreign directory, a fake `uv` reachable only on `PATH` -- the wrapper must
run.

**Done when:** the mixing test above passes, and it lives beside T6's tests in
`tests/test_render_foreign.py`.

## T8. Documentation

- `README.md`: a "Modules" section as the manifest's third concept, after tools
  and requirements. The `[import.<alias>]` shape, `tools`, `rename`, that
  aliasing is how two upstreams' `jq` coexist, that requirements groups are
  module-private, and that imports are re-exported.
- `README.md`: a "Render your own tools" section -- install the wheel or use a
  release's `bin/render`, write a `toolshed.toml`, `render <path>`, `[paths]`, and
  the `override_env` pattern for the consumer's own package (D4 says it is
  generic; nothing says so where a consumer will read it).
- `README.md`: extend "Tool resolution" with the two-layer story from T7 --
  alias within a graph, `PATH` order across bin directories -- plus
  `render resolve`, `--no-shadow`, and the `TOOLSHED_BIN_DIR` caveat that it
  designates *one* directory for runner lookup and is not a search path.
- `README.md`: state plainly that `args` and `entry` resolve against the working
  directory, so a tool using them is consumer-local and stays that way when
  imported.
- `README.md`: the pinning paragraph gains the T5 rule -- an imported tool's
  digests come from its own module's lock, and `render pin` on a local name is
  how you override one.
- `AGENTS.md`: under "Things that will trip you up", that `render` no longer
  assumes one root (any new path comes from the resolver, never from `cwd` or
  `__file__`), and that `resolve_manifest` rather than `load_manifest` is the
  entry point anything rendering a manifest should call.
- `design/toolshed-design-decisions.md`: append the resolution of D8 item 2 as a
  new decision -- the module system, why collisions resolve at parse time rather
  than on `PATH`, why groups are module-private, why imported pins come from the
  imported lock, and the rejected exec wrapper.
- `followup/tasks.md`: move the "Render foreign manifests" item out of the
  deferred section, and record anything left deferred (Open question 1 in
  particular, if remote sources stay out).

**Done when:** a reader who has only the README can write a module that imports
two upstreams with a colliding tool name, render it, and say which `jq` will run
and why.

---

## Open questions for the user

1. **How is a module source specified?** This plan supports filesystem paths
   only: relative to the importing manifest, or absolute, with a git submodule
   or plain checkout as the way to get somebody else's module onto disk (D10's
   consumer mode 2 already blesses checkouts). The alternative is to also accept
   a `git+https` form, the way D4's own `toolshed` requirement does. That is a
   bigger feature than it looks: it needs a fetch-and-verify story, a cache, and
   an answer to "which revision" -- which means recording the resolved revision
   somewhere, and the only existing candidate is `toolshed.lock.toml` beside the
   dotslash digests. Path-only now and remote later, or design the remote form
   in this plan?
2. **Where do an imported dotslash tool's digests come from?** T5 says: the
   imported module's own lock by default, with an entry under the local name in
   the root lock as an override, and `render pin` writing only the root lock. The
   consequence is that a consumer's lock diff does not show a digest change that
   came from bumping a vendored module -- they see the submodule pointer move
   instead. The alternative is that the root lock must carry every pin in the
   graph, re-downloaded by `render pin`, which makes every byte the consumer
   executes reviewable in their own repo at the cost of duplicating the
   upstream's pinning work and re-downloading assets somebody already verified.
   Confirm the default, or flip it?
3. **Are imports re-exported?** T3 says yes: a module's exports are the tools it
   defines plus the tools it imports, under their local names there. That is what
   makes a bundle module -- one whose entire content is curated imports -- worth
   writing. The cost is that an importer has to read a module's `[import]` tables
   to know where a name really came from, and a name can travel several hops. The
   alternative is that only defined tools are exported, with an explicit
   opt-in (`export = true` on an import, or an `[export]` allowlist) for the
   bundle case. Default-on, opt-in, or no re-export at all?
4. **May an importer override an imported tool's fields?** T4 says no: select and
   rename, nothing else. So pinning a different `version` of an imported dotslash
   tool means copying its table into your own module rather than importing it.
   Should an import be able to patch a field -- and if so, is that only
   `version`, or anything?
5. **Table and key names.** The plan uses `[import.<alias>]` with `source`,
   `tools`, `rename`, and a `[paths]` table with `lock` and `bin`. Alternatives
   considered: `[module.<alias>]` (matches the vocabulary, but `module` is
   already a `uv-run` tool key and would read ambiguously), `[require.<alias>]`,
   and `[render]` instead of `[paths]`. These names are expensive to change once
   a downstream module exists. Confirm, or rename now?
6. **Should a module be able to declare what it exports?** Independent of
   question 3: today every tool a module defines is importable. A module author
   might want to keep a tool private -- something with `args` that only works in
   their repo, for instance -- rather than having a stranger import it and find
   it broken. Worth an `[export]` allowlist, or is "importing a repo-local tool
   is the importer's mistake, documented in T8" enough?
7. **Does `--no-shadow` belong in `[paths]`' neighborhood as a manifest key?** It
   is a CLI flag in this plan, deliberately: it depends on the renderer's `PATH`,
   so it is a property of an invocation rather than of a manifest. But a repo that
   always wants it would rather declare it once than remember the flag. Add a
   manifest-level default later, or leave it CLI-only?

### Critical files for implementation

- toolshed/manifest.py (`[import]` and `[paths]` grammar, `Import`, `Manifest.imports`, `Tool.origin`)
- toolshed/module.py (new: graph loading, cycle detection, merge)
- toolshed/render.py (`RenderPaths`, the positional CLI, `--no-shadow`, `render resolve`)
- toolshed/lock.py (per-module lock lookup, pruning by local name)
- toolshed/pin.py (writing only the root lock)
- tests/test_manifest.py
- tests/test_module.py (new)
- tests/test_render.py
- tests/test_render_foreign.py (new)
- README.md, AGENTS.md
