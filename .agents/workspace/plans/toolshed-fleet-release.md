# Plan: Fleet-compatible toolshed release

**Goal.** Rename the renderer executable to `toolshed`, make rendering an explicit
`toolshed render` command, and publish an immutable release with separate Linux
x86_64 and arm64/aarch64 artifacts suitable for Fleet.

**Status.** Approved; implementation not started.

**Decisions.** Keep `pin` and `update` as top-level commands (`toolshed pin`,
`toolshed update`); remove the legacy `render` executable/interface; publish
separate Linux archives; pin the self-reference to a full commit SHA. The
release workflow must handle the self-reference cycle explicitly rather than
claiming a release can atomically contain its own final SHA.

## Tasks

1. **CLI and manifest rename.** Add tests first for `toolshed render`,
   `toolshed pin`, and `toolshed update`; rename the manifest tool and generated
   executable from `render` to `toolshed`; update parser help/prog and all
   internal invocations. Remove the root `render` symlink and update validator
   file lists. Verify generated wrappers and CLI behavior.

2. **Generated output and integration tests.** Update templates, lock/manifest
   references, and existing tests for the new executable name. Add coverage for
   the explicit render subcommand, rejected legacy/bare forms, and generated
   wrapper execution. Run the full unit suite and validation.

3. **Immutable package pin.** Replace the mutable self-reference with a full
   commit SHA in the manifest and generated output. Document the two-step
   release/repin process required when the release commit cannot know its own
   SHA. Add tests or validation that reject mutable self-pins where practical.

4. **Architecture-specific release artifacts.** Update CI/release workflows and
   installer logic to build, name, checksum, verify, and select distinct Linux
   x86_64 and arm64/aarch64 archives while preserving macOS support. Add matrix
   or native-runner verification for both Linux architectures and tests for
   artifact naming/selection and checksum handling.

5. **Documentation and migration guidance.** Update README, AGENTS guidance,
   install/release docs, and comments to use `toolshed render`, identify the
   immutable release pin and supported architecture names, explain artifact
   selection, and state the migration from `render`.

6. **Release verification and closeout.** Run render/check, tests, validation,
   and available network/package checks. Review generated diffs and stale
   references. Update this task's followup entry only after all acceptance
   criteria are verified; keep any unavailable publication step explicitly
   recorded rather than claiming it completed.
