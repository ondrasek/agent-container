# Implementation Plan: `doctor` — Preflight Validation

**Branch**: `013-doctor-preflight` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-doctor-preflight/`

## Summary

One read-only command answers **"would a deploy work, and if not, why"** without attempting one.
Every check returns pass / fail / **unknown** with a severity and a remedy; one run reports all of
them; the exit status is actionable without parsing prose.

The feature is easy to describe and easy to get subtly wrong, because **a diagnostic that reports
healthy is what stops an operator looking further**. Two properties carry that risk and shape the
whole plan:

- **Read-only is structural, not aspirational.** The helpers a deploy calls first are the ones
  that mutate, and the most dangerous is documented as *"safe to call repeatedly"* (research R1).
- **Unknown is a first-class result.** Wherever the honest answer is "cannot tell without a side
  effect", the answer is *unknown* — not a guess in either direction (R3, R5).

## The decisions this plan settles first

### 1. `doctor` composes its own readers — it does not reuse the deploy path

`migrate_flat_state()` opens `do_up`, `do_redeploy` and `do_list`. It relocates files on disk. It
is idempotent and self-describes as safe, so it reads as harmless — and SC-002 measures exactly
what it does. Same for `drain_host_records()` (starts a container per environment) and
`record_inventory_creation()` (writes).

So the read-only guarantee is enforced by **what the command is allowed to call**, not by a flag
threaded through shared code where each new caller can forget it. See R1 for the full table.

**One deliberate exception**: an SSH socket-forward for a provisioned host (R2). It creates none
of the five artifact kinds FR-002 names and does not outlive the command, and without it every
provisioned host reads *unreachable* — a false negative on the check being asked for. The line is
**nothing that outlives the command**, and it is recorded as a judgment call rather than an
oversight.

### 2. Credential *resolvability* is not credential *resolution*

For `env` and `file` sources the question is answerable for free. For `keychain`, `onepassword`,
`bitwarden` and `command`, **resolving is the prompt** — `op read` against an approval-gated item
raises a system dialog, which FR-009 forbids as a side effect of asking a question, and pulls a
secret into memory against FR-010.

`doctor` therefore checks that the **resolver binary exists** and reports *unknown* beyond that.
That is not a consolation prize: "`op` is not installed" is the most common real failure on a new
machine, which is US3's scenario exactly. Full reasoning and the rejected `--no-prompt` approach
are in R3.

### 3. Exit codes: exactly 0, 1 or 2 — the spec's range is now a trap

FR-011 says "**2 or greater** when `doctor` itself could not run". That was written before Feature
019 shipped a tool-wide table in which **`3` means *pending registration***, documented in `--help`
and pinned by a test. A `doctor` returning 3 would tell an automated caller something false about
an SSH key.

`2` satisfies both: FR-011's letter includes it, and `2` is already the shared "could not proceed"
code. **Nothing above 2 is available.**

> **Spec follow-up, not applied here.** FR-011's open-ended range should be narrowed to *exactly
> 2* before `/speckit-tasks`. `/speckit-plan` does not edit the spec.

### 4. Image freshness is a build-time change with a diagnostic payoff

No version stamp exists today — verified in `image/Dockerfile` and in `build`'s argv. FR-012a
needs an `org.opencontainers.image.version` **label** fed by a build arg from `_resolve_version()`,
and `doctor` reads it back with `image inspect` (a label, not an `ENV`, precisely because reading
it must not start a container).

When the version is unresolvable, `_resolve_version()` returns `"0.0.0+unknown"` — **omit the
label entirely** rather than stamp that. A meaningless value that looks like an answer is worse
than the absence FR-012b already handles correctly.

Every image built before this ships reports *unknown*, permanently, until rebuilt. The spec calls
that correct rather than unfortunate; this plan agrees.

### 5. Shared wording means the SAME STRING, not a matching one

SC-008 demands **zero divergence** between `doctor`'s layout remedy and the deploy's. Two strings
that agree today drift the moment one is edited, and the drift is invisible — both still read
correctly alone. So `doctor` calls the same producer (`refuse_superseded_layout`) and traps the
`Fatal` (R8, R9).

That trap is load-bearing for FR-003 too: every existing validator `die()`s on the first problem,
which is right for a deploy and fatal for "report **all** of them in one pass". Checks convert
exceptions into findings; no check calls `die()`.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14, single-file PEP 723 CLI (`bin/agent-container`).

**Primary Dependencies**: **none new**. Typer/rich/questionary/PyYAML are already present
(Constitution VI).

**Storage**: **none, by construction.** This feature is the one that must write nothing.

**Testing**: hermetic pytest for check classification, severity, exit-code mapping, the
non-prompting credential logic and the shared-wording identity; acceptance for what only a real
environment shows — the zero-side-effect gate, an unreachable host, and freshness against a real
built image.

**Target Platform**: macOS + Linux operator machines; Docker and Podman hosts.

**Project Type**: CLI (single-file), plus a one-line image change.

**Performance Goals**: a bare run must stay **casually cheap** (spec assumption: "checks are
cheap"). Host reachability is the only network cost and is bounded per host; one slow host must
not extend the run past that bound (FR-008).

**Constraints**:
- **Zero observable side effects** (FR-002 / SC-002) — the defining constraint.
- **No interactive prompt** as a side effect of any check (FR-009).
- **No credential value** printed, logged or held (FR-010, Constitution III).
- **Exit 0/1/2 only** (FR-011 as narrowed by R4).
- **Unknown never reported as pass** (FR-006).

**Scale/Scope**: one project's declared environments plus machine-level state; tens of
environments, single-digit hosts.

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS** — writes nothing, so nothing durable can be trapped. |
| **II. Least Privilege, Immutable Runtime** | **PASS, and exemplary.** A read-only command is the least-privilege shape; it gains no capability and starts nothing. |
| **III. Least Exposure** | **PASS, and load-bearing.** FR-010 forbids exposing a credential value, and R3's design means no value is ever *retrieved*, which is stronger than not printing one. |
| **IV. Deterministic Identity** | **PASS** — reads the derived port/name contract, changes nothing about it. |
| **V. Durable Spec, Disposable Code** | **PASS** — verification is acceptance-weighted; the zero-side-effect gate is a spec-level property that survives any rewrite. |
| **VI. Least Dependencies** | **PASS** — nothing new. |
| **VII. Continuous Deployment** | **`feat`, MINOR.** A new command plus an additive image label; nothing removed, no flag changes meaning. |

**Threat model (Development Workflow, MUST)**: 013 alters no trust boundary and opens no network
surface, but it **touches a credential path** — it reads credential *declarations* and probes for
resolver binaries. Its row must record that it never retrieves a value, and must state the one
new residual: a report that enumerates which credentials an environment declares and which hosts
exist is a **reconnaissance aid** on the operator's own machine, in the same class as Feature
014's inventory. That is the honest entry; the mitigated half is that no value is read.

## Project Structure

### Documentation (this feature)

```text
specs/013-doctor-preflight/
├── plan.md              # this file
├── research.md          # Phase 0 — R1..R10
├── data-model.md        # Phase 1 — Check, Finding, Scope, Report
├── quickstart.md        # Phase 1 — S1..S12
├── contracts/
│   └── doctor-contract.md
└── checklists/requirements.md   # 16/16, pre-existing
```

### Source Code (repository root)

```text
bin/agent-container      the `doctor` command; a Check/Finding model; the check
                         registry; per-check readers (layout, config resolution,
                         credential resolvability, host reachability, image
                         freshness, port availability); the 0/1/2 exit mapping;
                         `--json` through the 009 envelope
image/Dockerfile         org.opencontainers.image.version label (FR-012a)
bin/tests/test_doctor.py hermetic: classification, severity, exit mapping, the
                         non-prompting credential logic, shared-wording identity
bin/tests/test_acceptance.py  the ZERO-SIDE-EFFECT gate; unreachable host;
                         freshness against a really-built image; all-problems-in-
                         one-pass against a really-broken project
completions/agent-container.{bash,zsh}   `doctor` in the command list (a test pins
                         the completions' list to the CLI's and fails on drift)
docs/                    where `doctor` is documented (see below)
docs/threat-model.md     reconcile the 013 row (Constitution MUST)
CLAUDE.md                at most a one-line invariant — and the file is ALREADY
                         over its 2000-token budget, so this prunes before adding
```

**Structure Decision**: the existing single-file CLI plus one image line. No new module, no new
directory: the checks are readers over state this tool already understands, and Constitution VI
says reach first for what is present.

## Design decisions carried into tasks

1. **Compose read-only readers**; never call the deploy path's setup helpers (R1).
2. **A tunnel is permitted, a container is not** — nothing that outlives the command (R2).
3. **Never resolve a manager credential**; check the resolver binary, else *unknown* (R3).
4. **Exit 0/1/2 only** (R4).
5. **Stamp a label from the build arg; omit it when the version is unknown** (R5).
6. **`doctor` is in the `--json` set** — enforced by an existing test (R7).
7. **Reuse the deploy's remedy STRING, trapping its `Fatal`** (R8, R9).
8. **A healthy environment's own port is a pass, not a conflict** (R10).

## Phasing

**P1 — the report exists and changes nothing.** US1. The Check/Finding model, the registry, two
or three real checks, and — first — **the zero-side-effect acceptance gate**. That gate is the
feature; building checks on top of an unproven one means writing it later to pass what exists.

**P2 — the report is readable and actionable.** US2. Severity, the 0/1/2 exit mapping, the `--json`
shape, and the brief all-clear output (FR-014).

**P3 — the whole machine, and the honest edges.** US3 (machine-level scope, no project, per-host
isolation), image freshness including the build-side stamp, *unknown* on timeout, and the threat
model row.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| An SSH socket-forward during a read-only command | without it every provisioned host reads *unreachable* — a false negative on the check FR-012 asks for | reporting provisioned hosts as *unknown*; honest, but so much less useful that operators would stop running it |
| Trapping `Fatal` from existing validators | SC-008 wants the same string and FR-003 wants all findings; the validators `die()` on the first | refactoring four features' validators to return results — a far larger change to code that is correct as it stands |
| A build-time change inside a diagnostic feature | FR-012a's freshness check is unanswerable without a stamp, and no stamp exists | a registry round-trip, rejected in the spec's own clarification: slow, networked, and answers a different question |
