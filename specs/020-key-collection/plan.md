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
therefore a **sentinel-delimited managed region** inside `authorized_keys`, replaced
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
admit set inside a managed region on the existing `ssh` volume. No new volume, no new
state file, no registry entry.

**Testing**: `pytest` hermetic tier (`bin/tests/`) for resolution, validation and
compose-model shape; `pytest -m acceptance` for the region semantics, the revocation
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
| **I. Ephemerality** | **Pass, and improves it** | The managed region is derived from the operator's file on every boot. What the volume holds stops being authoritative — which is precisely the fix for FR-006. |
| **II. Least Privilege / Immutable Runtime** | Pass | No new capability, no new package, no runtime `apt`. The container writes only its own `~/.ssh/authorized_keys`, as it does today. |
| **III. Least Exposure** | Pass | Public keys, on the non-secret config channel, staged 0644 because `dev` must read them. **The private-key refusal (C7) exists so a mis-`cat` never becomes an exposure** — the only way private material could enter this path. |
| **IV. Deterministic Identity** | Pass | Same collection ⇒ same admit set. The region is content-derived, so it is reproducible rather than accumulated. |
| **V. Durable Spec** | Pass | spec/plan/research/data-model/contracts/quickstart under `specs/020-key-collection/`; the operator-facing behaviour lands in `docs/credentials.md` (SSH identity) with the managed-region rule stated at both code sites (C21). |
| **VI. Least Dependencies** | Pass | Zero new dependencies. A YAML or JSON collection format was rejected partly on this ground (R2). |
| **VII. Continuous Deployment** | **Pass, with two things that must be said out loud** | Conventional Commits; `feat(keys)` ⇒ MINOR. (a) **FR-015 and FR-018 both break a shipped command**: a `keys` grant no longer survives a recreate. Pre-1.0 that is still a MINOR bump, which is exactly why the release notes must say it in words — the version number will not. (b) **If C20 shows `file:` never crossed a remote context**, the `--authorized-key` fix is a separate breaking-behaviour correction and gets its own `fix` commit, not a fold-in. |
| **VIII. Defaults Belong at the Surface** | **Pass — and it is load-bearing in THREE places** | (1) FR-009: absent (undeclared) vs declared-empty vs declared-N; the empty case is a legitimate instruction *and* a lockout, so it is honoured **and warned about** (R6, C4), with a test pinning C3 against C4 so they cannot collapse. (2) FR-014: projected vs observed, never one standing in for the other. (3) FR-019: unexamined (`undetermined`) vs genuinely empty — "nobody is authorised" and "we did not look" are different claims. A key collection is almost entirely absence questions, which is why this principle keeps recurring here rather than appearing once. |

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
├── data-model.md        # Phase 1 — collection, entry, admit set, managed region
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
  ├── keys_app (typer group)         # NEW — keys show / keys ls / keys add (C28..C30)
  ├── inject_keys()                  # CHANGED — writes INSIDE the managed region (C25, C27)
  ├── stage_ssh_injection()          # CHANGED — feeds content:, not a staged file path
  └── build_compose_model()          # CHANGED — ssh_authorized_keys via content:

image/entrypoint.sh                  # CHANGED — managed region replaces the union
image-control-plane/entrypoint.sh    # CHANGED — same region, same role coverage

bin/tests/test_entrypoint.sh         # CHANGED — EXECUTES the entrypoint against stubs
  ├── section 7e                     # REWRITTEN — union assertions become region assertions
  └── section 7f                     # NEW — C13/C17/C27: one marker pair, outside preserved, malformed refused
bin/tests/test_key_collection.py     # NEW — hermetic, PYTHON-side only: C1..C12, C18..C19, C24, C28..C32
                                     #       plus entrypoint PARITY (agent vs control-plane region logic)
bin/tests/test_acceptance.py         # EXTENDED — C12, C15, C16, C20, C23, C25, C26 (only a real run proves these)

docs/credentials.md                  # CHANGED — the collection, and both update rules
```

**Structure Decision**: no new module and no new file in the CLI — the project is a
single-file CLI by design, and the collection is five small functions next to the
existing `settings_candidates`/`resolve_settings_key` pair it deliberately mirrors.
The one new test file matches the per-feature convention (`test_control_plane.py`,
`test_doctor.py`).

**The test split is load-bearing, not stylistic.** The region parser is **shell**, so it
is tested by the harness that **executes** shell (`test_entrypoint.sh`). This repo's
alternative precedent — a Python test that `read_text()`s the entrypoint and asserts on
its source — cannot fail when the shell logic is wrong, and grep-the-source coverage for
the mechanism the whole feature rests on is the exact defect shape 020 exists to remove.
`test_key_collection.py` therefore holds only what genuinely is Python, plus one textual
**parity** check between the two entrypoints — where a textual assertion is honest,
because the claim is that two texts agree, which text can prove.

## Phase sequencing

The order is forced by the two findings, not by convenience:

1. **Settle C20 first** — measure whether `file:` crosses a remote context. It
   decides whether the change to `content:` is a refactor or a bug fix, and
   Principle VII says that distinction has to be made before the commit, not after.
2. **Managed region in the entrypoint** — the revocation fix. It is independently
   valuable and testable with `--authorized-key` alone, before any collection
   exists.
3. **Rewrite `test_entrypoint.sh` §7e in the same change as step 2.** That section
   EXECUTES the entrypoint and asserts the union step 2 deletes, and it runs in the
   quality gate — so the gate goes red here whether or not anyone planned for it. Its
   fixture also places one key in both the persisted file and the env source, so the
   count changes and the failure reads as "the new code is broken" when the old contract
   is merely still pinned. Rewritten, never deleted: a removed assertion leaves nobody
   watching, which is why 7c/7d were inverted rather than dropped.
4. **Resolution + validation + statement in the CLI** — the operator-facing feature.
5. **`inject_keys` moves inside the region** (FR-015, C25/C27) — after the region exists, since
   there is nothing to write inside until then. The paired test C26 must land in the same
   change: the two halves ("tool grants are revocable", "hand-added keys are not the tool's
   to remove") are one boundary, and a change that asserts only the first will happily
   delete an operator's keys.
6. **Resume drift and the observed query** (FR-013/FR-014, C23/C24) — both are comparisons
   against the created-with set, so they share a mechanism and should not be built twice.
7. **Docs and the two update-rule comments** (C21, C22) — write-once vs replaced-every-boot,
   plus the threat-model row and the CLAUDE.md pointer the constitution requires in the same
   change as the behaviour.

Step 2 before step 4 is deliberate: if the collection landed first, US1 would pass
and US3 would fail, which is the failure mode the spec's own checklist warned about.

**These seven steps map onto the seven phases of `tasks.md`** (steps 2 and 3 are one
phase — Foundational — because they must land together). If the two ever disagree,
`tasks.md` is the executable one and this list is the stale one.

## What could still be wrong

- **C20's outcome is unknown.** Both branches are planned for, but if `file:`
  *does* cross, then 017's "measured" claim is the wrong one, and that finding
  reaches beyond this feature — the host registry chose `content:` on the strength
  of it. Worth reporting either way.
- **FR-015 is the clarification that most changes the shape of the work**, and it arrived
  after this plan was first written. It turns `keys` from an untouched command into a
  modified one, and it means the managed region has *two* writers (deploy-time and
  `keys`-time) rather than one. Two writers to one managed region is where C27 comes from
  and is the likeliest place for this feature to go wrong.
- **`authorized_keys` options syntax** (`command=`, `from=`, `restrict`) is legal in
  the format and unexercised by any scenario here. The plan treats a line as opaque
  and validates via `ssh-keygen -l`, which handles options — but no contract pins
  it. If an operator uses `from=`, nothing should break; that it *doesn't* is
  currently an assumption, not a tested one.


---

## Superseded by later work (2026-08-24)

This plan describes the feature as designed, and three things changed after it shipped.
Recorded here because the plan is what a reader opens first, and a plan that quietly
disagrees with the code is worse than no plan.

**Credential delivery moved out of the deployment description entirely.** The plan's
`content:` decision still holds for PUBLIC material (authorised keys, known_hosts,
canonical config, the task). Secrets no longer appear in the compose model in any form:
they are pushed over SSH into the running container by `deliver_secrets`, per
Constitution IX, which was ratified from a near-miss during this work. See
`research.md` R7.

**Credentials PERSIST, one volume each.** The first implementation made them ephemeral,
which cannot survive a reboot or a daemon restart — nothing is present to re-deliver.
FR-012 is superseded by FR-012a. Persistence is paired with reconciliation: every
deploy removes the volume of a credential it no longer declares, or the declaration
stops being the authority. See `research.md` R8.

**sshd runs in every mode**, headless included, and starts before the credential
stages. It is the primary interaction surface, and it is also the delivery channel, so
it has to be listening before anything waits on a delivery.

**Revocation is a CLI operation**: `creds ls` / `creds rm`. `docker volume rm` works —
the naming is deliberate — but it cannot take effect while the container holds the
volume, so it cannot serve the case an operator actually means by "revoke".

The task list in `tasks.md` reflects the feature as planned and completed (55/55); it
does NOT cover the four changes above, which arrived as separate work after it closed.
