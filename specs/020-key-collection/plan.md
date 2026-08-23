# Implementation Plan: Public-key collection, auto-injected

**Branch**: `020-key-collection` | **Date**: 2026-08-23 | **Spec**: [spec.md](spec.md)

**Input**: [`specs/020-key-collection/spec.md`](spec.md)

## Summary

An operator declares a set of SSH public keys once — `authorized_keys` at the user
or project config level — and every environment they create admits those keys with
no per-deploy flag.

The technical approach is decided by one finding rather than by the user story: the
entrypoint currently **unions** persisted + injected + env keys and writes the union
back to the `ssh` volume, so a key injected once is authorized forever. A collection
layered on that mechanism would grant access and never revoke it. The approach is
therefore a **sentinel-delimited managed block** inside `authorized_keys`, replaced
wholesale each boot, preserving everything outside it — reusing the
`# BEGIN agent-container` idiom already in the entrypoint, with the opposite update
rule stated at both sites.

A second finding shapes the injection channel: two docstrings in the CLI make
**incompatible claims** about whether a `configs: {file:}` entry crosses a remote
context, and the `ssh_authorized_keys` config — the exact channel this feature uses
— is the one they disagree about. The plan measures it and moves the entry to
`content:`.

## Technical Context

**Language/Version**: Python 3.14 (single-file PEP 723 CLI `bin/agent-container`);
POSIX shell for `image/entrypoint.sh` and `image-control-plane/entrypoint.sh`

**Primary Dependencies**: none new. PyYAML remains the one third-party dep, and this
feature does not need it — the collection is `authorized_keys` line format, not YAML
(R2). `ssh-keygen` is already present at both ends.

**Storage**: operator-authored text files at the two config levels; the resolved
admit set inside a managed block on the existing `ssh` volume. No new volume, no new
state file, no registry entry.

**Testing**: `pytest` hermetic tier (`bin/tests/`) for resolution, validation and
compose-model shape; `pytest -m acceptance` for the block semantics, the revocation
that FR-006 turns on, and the remote-context arrival.

**Target Platform**: Linux containers under Podman/Docker, rootless; macOS and Linux
hosts for the CLI.

**Project Type**: CLI + container image.

**Performance Goals**: not a factor. Validation is `ssh-keygen -l` over a handful of
lines, once per deploy.

**Constraints**: refusals must precede any runtime call (a lockout is discovered
from the device that cannot fix it); no key material on argv; public keys must not
be handled as secrets.

**Scale/Scope**: single operator, a handful of devices. Roughly a dozen keys is the
realistic ceiling and no part of the design cares.

## Constitution Check

*GATE: passed before Phase 0, re-checked after Phase 1.*

| Principle | Verdict | Basis |
|---|---|---|
| **I. Ephemerality** | **Pass, and improves it** | The managed block is derived from the operator's file on every boot. What the volume holds stops being authoritative — which is precisely the fix for FR-006. |
| **II. Least Privilege / Immutable Runtime** | Pass | No new capability, no new package, no runtime `apt`. The container writes only its own `~/.ssh/authorized_keys`, as it does today. |
| **III. Least Exposure** | Pass | Public keys, on the non-secret config channel, staged 0644 because `dev` must read them. **The private-key refusal (C7) exists so a mis-`cat` never becomes an exposure** — the only way private material could enter this path. |
| **IV. Deterministic Identity** | Pass | Same collection ⇒ same admit set. The block is content-derived, so it is reproducible rather than accumulated. |
| **V. Durable Spec** | Pass | spec/plan/research/data-model/contracts/quickstart under `specs/020-key-collection/`; the operator-facing behaviour lands in `docs/credentials.md` (SSH identity) with the managed-block rule stated at both code sites (C21). |
| **VI. Least Dependencies** | Pass | Zero new dependencies. A YAML or JSON collection format was rejected partly on this ground (R2). |
| **VII. Continuous Deployment** | **Pass, with two things that must be said out loud** | Conventional Commits; `feat(keys)` ⇒ MINOR. (a) **FR-015 breaks a shipped command**: a `keys` grant no longer survives a recreate. Pre-1.0 that is still a MINOR bump, which is exactly why the release notes must say it in words — the version number will not. (b) **If C20 shows `file:` never crossed a remote context**, the `--authorized-key` fix is a separate breaking-behaviour correction and gets its own `fix` commit, not a fold-in. |
| **VIII. Defaults Belong at the Surface** | **Pass — and it is load-bearing here** | Three states stay distinct: absent (undeclared), declared-empty, declared-N. The empty case is a legitimate instruction *and* a lockout, so it is honoured **and warned about** (R6, C4). No reader may substitute a default for absence; the delivery boundary decides, and a test pins C3 against C4 so the two can never collapse. |

**No violations. Complexity Tracking is therefore empty and omitted.**

One risk worth naming rather than tracking as a violation: this feature makes it
easy to hold **one** file whose contents determine access to every environment.
That is the point of the feature, and it is also a single edit away from a
self-lockout. The mitigations are all in the contracts — refuse early (C6–C9), state
the set before deploying (C10), warn on empty (C4) — and none of them is optional.

## Project Structure

### Documentation (this feature)

```text
specs/020-key-collection/
├── plan.md              # this file
├── research.md          # Phase 0 — R1..R6
├── data-model.md        # Phase 1 — collection, entry, admit set, managed block
├── quickstart.md        # Phase 1 — S1..S7 validation scenarios
├── contracts/cli.md     # Phase 1 — C1..C22
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # /speckit-tasks — NOT created here
```

### Source Code (repository root)

```text
bin/agent-container            # resolution, validation, statement, compose model
  ├── authorized_keys_candidates()   # NEW — project-then-user, mirrors settings_candidates()
  ├── resolve_key_collection()       # NEW — winning file, three states distinguished
  ├── validate_public_key_line()     # NEW — ssh-keygen -l; private-key refusal
  ├── resolved_admit_set()           # NEW — collection ∪ --authorized-key, attributed
  ├── report_admit_set()             # NEW — fingerprint + comment + source, pre-deploy
  ├── report_admit_set_observed()    # NEW — projected vs observed, `undetermined` when unreachable (C24)
  ├── start_collection_drift()       # NEW — warn-only comparison on resume (C23)
  ├── inject_keys()                  # CHANGED — writes INSIDE the managed region (C25, C27)
  ├── stage_ssh_injection()          # CHANGED — feeds content:, not a staged file path
  └── build_compose_model()          # CHANGED — ssh_authorized_keys via content:

image/entrypoint.sh                  # CHANGED — managed block replaces the union
image-control-plane/entrypoint.sh    # CHANGED — same block, same role coverage

bin/tests/test_key_collection.py     # NEW — hermetic: C1..C11, C13..C19
bin/tests/test_acceptance.py         # EXTENDED — C12, C15, C20 (the ones only a real run can prove)

docs/credentials.md                  # CHANGED — the collection, and the two block rules
```

**Structure Decision**: no new module and no new file in the CLI — the project is a
single-file CLI by design, and the collection is five small functions next to the
existing `settings_candidates`/`resolve_settings_key` pair it deliberately mirrors.
The one new test file matches the per-feature convention (`test_control_plane.py`,
`test_doctor.py`).

## Phase sequencing

The order is forced by the two findings, not by convenience:

1. **Settle C20 first** — measure whether `file:` crosses a remote context. It
   decides whether the change to `content:` is a refactor or a bug fix, and
   Principle VII says that distinction has to be made before the commit, not after.
2. **Managed block in the entrypoint** — the revocation fix. It is independently
   valuable and testable with `--authorized-key` alone, before any collection
   exists.
3. **Resolution + validation + statement in the CLI** — the operator-facing feature.
4. **`inject_keys` moves inside the region** (FR-015, C25/C27) — after the block exists, since
   there is nothing to write inside until then. The paired test C26 must land in the same
   change: the two halves ("tool grants are revocable", "hand-added keys are not the tool's
   to remove") are one boundary, and a change that asserts only the first will happily
   delete an operator's keys.
5. **Resume drift and the observed query** (FR-013/FR-014, C23/C24) — both are comparisons
   against the created-with set, so they share a mechanism and should not be built twice.
6. **Docs and the two block-rule comments** (C21, C22).

Step 2 before step 3 is deliberate: if the collection landed first, US1 would pass
and US3 would fail, which is the failure mode the spec's own checklist warned about.

## What could still be wrong

- **C20's outcome is unknown.** Both branches are planned for, but if `file:`
  *does* cross, then 017's "measured" claim is the wrong one, and that finding
  reaches beyond this feature — the host registry chose `content:` on the strength
  of it. Worth reporting either way.
- **FR-015 is the clarification that most changes the shape of the work**, and it arrived
  after this plan was first written. It turns `keys` from an untouched command into a
  modified one, and it means the managed region has *two* writers (deploy-time and
  `keys`-time) rather than one. Two writers to one delimited region is where C27 comes from
  and is the likeliest place for this feature to go wrong.
- **`authorized_keys` options syntax** (`command=`, `from=`, `restrict`) is legal in
  the format and unexercised by any scenario here. The plan treats a line as opaque
  and validates via `ssh-keygen -l`, which handles options — but no contract pins
  it. If an operator uses `from=`, nothing should break; that it *doesn't* is
  currently an assumption, not a tested one.
