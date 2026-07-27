# Implementation Plan: Filesystem Layout

**Branch**: `011-filesystem-layout` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-filesystem-layout/spec.md`

## Summary

Give every tool-owned location one obvious meaning and one obvious home, **without changing what
the tool does**. Three independent moves, ordered by risk:

1. **Consolidate** the project-level convention files into `.agent-container/` (project config),
   dropping the now-redundant `agent-container.` prefix so both configuration levels use the same
   filename.
2. **Relocate** the image sources to `image/`, which makes the build context narrow by
   construction instead of by an allowlist.
3. **Rename** the one genuinely confusable in-container path: `~/.agent-container` → `~/.agent-env`.

Per the 2026-07-27 clarification this is a **hard cut** — the previous layout is removed in the
same change, with no dual lookup and no deprecation window. The safety property that makes that
acceptable is FR-004: a superseded file is **refused loudly**, never silently ignored, because
the superseded set includes credential files.

**The constraint that shapes everything**: identity is untouchable. Container names, the port
formula and every volume **name** are unchanged (Constitution IV). This feature moves *paths*,
never *identities* — including the shell-env volume, whose name stays `-shellenv` while only its
mount point moves.

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file PEP 723 CLI) · POSIX shell (`entrypoint.sh`) ·
Dockerfile (`debian:12-slim`)

**Primary Dependencies**: none added. Pure reorganization.

**Storage**: unchanged. The nine per-container volume **names** are byte-identical before and
after; one **mount point** moves (`-shellenv`).

**Testing**: hermetic `pytest` + shell suites (gate tier) · `pytest -m acceptance` (real
containers, CI-authoritative). The identity guarantee (SC-003) is already mechanised by the
`--self-test` doctests and the port corpus.

**Target Platform**: rootless Linux container, driven from macOS or Linux hosts, local or remote.

**Project Type**: CLI tool + container image.

**Performance Goals**: none. The build context shrinks, which is a side effect, not a target.

**Constraints**:

- **Identity may not change** (FR-010) — the hard boundary of the whole feature.
- The **checkout marker** keys on `Dockerfile` at the root and runs **at import, before `die`
  exists** (research R1). Breaking it degrades silently to "no checkout reachable".
- The new `~/.agent-env` mount point **must be pre-created dev-owned in the image** — Feature 010
  proved a volume mounted at an image-absent path comes up `root:root` and rootless cannot write
  it, even under a dev-owned parent.
- `./.env` is **not** tool-owned and must keep working (research R2).

**Scale/Scope**: `bin/agent-container`, `entrypoint.sh`, `Dockerfile` → `image/`, the
`orchestration/` templates, docs, and roughly ten test modules that reference the moved paths.

## Constitution Check

| Principle | Gate | Verdict |
|---|---|---|
| **I. Ephemerality** | No workflow depends on uncommitted container state | **PASS** — file locations only |
| **II. Least Privilege, Immutable Runtime** | Rootless, deps baked | **PASS with a named trap** — the new `~/.agent-env` mount point must be pre-created dev-owned (R3); this is the exact failure Feature 010 hit |
| **III. Least Exposure** | No secret exposed | **PASS, and improves** — the build context stops depending on an allowlist that once let 23.4 MB and a planted key through (R4). FR-004's loud refusal is what keeps the hard cut from silently dropping a credential file |
| **IV. Deterministic Identity** | Derived, never stored; a stable contract | **PASS — and this is the feature's binding constraint.** Every name is unchanged; only paths move. Verified by existing doctests, not by inspection |
| **V. Durable Spec, Disposable Code** | Spec is the durable artifact | **PASS** — spec clarified and vocabulary-settled before planning |
| **VI. Least Dependencies** | Justify any new dependency | **PASS** — none added |
| **VII. Continuous Deployment** | Gate green; Conventional Commits | **PASS with a caveat** — this is the project's **first genuinely breaking change** and must carry `!`/`BREAKING CHANGE`. Pre-1.0 that cuts a *minor*, so the version number will understate it (R8) |

**No unjustified violations.**

## Project Structure

### Documentation (this feature)

```text
specs/011-filesystem-layout/
├── spec.md                  # clarified 2026-07-27; vocabulary settled
├── plan.md                  # this file
├── research.md              # Phase 0 — R1 (checkout marker) and R2 (./.env) are load-bearing
├── data-model.md            # the five locations + the move table
├── contracts/
│   └── layout-contract.md
├── quickstart.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
image/                       # NEW — the entire build context
├── Dockerfile               #   + ~/.agent-env mount point, dev-owned
├── entrypoint.sh            #   AGENT_CONTAINER_ENV_FILE path
└── .dockerignore            #   defence in depth now, not the sole guard

bin/agent-container          # _is_repo_checkout marker (R1) · 4 resolution sites (R2)
                             #   · all_volume_mounts doctest · build context · refusal (R5)
bin/tests/                   # test_packaging (fake-checkout fixture) · test_pure_logic
                             #   · test_credentialing · test_compose · shell suites · acceptance
orchestration/               # compose.yaml + quadlet: build context + shell-env mount
docs/                        # the single authoritative layout map (FR-014)
CLAUDE.md                    # layout statement
```

**Structure decision**: no new modules. `bin/agent-container` edits are sequential (one file);
the `image/` move, the templates and the docs parallelise against it.

## Design decisions carried into tasks

1. **Update the checkout marker in the same commit as the move** (R1) — marker, `die` text and
   the packaging test's fixture. This is the highest-risk edit; a wrong marker makes the tool
   fail to recognise its own repo, and it cannot report that failure loudly.
2. **`./.env` stays put and keeps working** (R2) — it is not tool-owned. The refusal fires only
   on the three `agent-container.`-prefixed names.
3. **The shell-env volume name does not change** (R3) — only its mount point. Existing contents
   reappear at the new path rather than being stranded.
4. **Pre-create `~/.agent-env` dev-owned in the image** (R3) — the Feature 010 trap, and it fails
   only at runtime if missed.
5. **The hard cut is two pieces of work, not one** (R5): delete the old lookup *and* add the
   refusal. Deleting alone is indistinguishable from silently ignoring.
6. **`/workspace/.agent-container` and `/run/agent-container` deliberately do not move** (R6).

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| A hard cut with no compatibility window | Explicit operator decision (2026-07-27); avoids carrying a dual-lookup path, a precedence rule and their tests forever | Supporting both layouts makes every future change to file resolution pay the tax permanently — and the risk it hedges is answered better by refusing loudly than by guessing |
| The refusal check is net-new code in a feature that "only moves files" | Without it the hard cut silently drops credential files (Constitution III) | Deleting the old lookup and saying nothing is the failure mode, not the fix |
