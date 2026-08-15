# Implementation Plan: Kill Switch

**Branch**: `015-kill-switch` | **Date**: 2026-08-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-kill-switch/`

## Summary

One deliberate action that stops everything the tool owns, everywhere, and **tells the truth about
what it could not reach**.

The stopping is the easy half. The hard half is that an operator reaching for this is already having
a bad day, so **a report that overstates success is worse than an error** — it ends the investigation
while something is still running. Every decision below resolves toward that.

Feature 014 landed first and is a **hard** prerequisite: it is the enumeration source *and* the
ownership rule. This feature does not ask hosts what exists; it asks the record, then goes and checks.

## The decisions this plan settles first

### 1. Stop by PROJECT LABEL, not by compose file — the state dir dies with its host

The most important finding of this planning pass, and it is a real integration problem rather than a
preference.

`do_stop` requires `compose_file_path(host, name)`, which lives in **derived host state** — the
location Feature 011 documents as *"computed; safe to delete"* and which dies with its host. Feature
014's entries **outlive that directory on purpose**. So the environments this feature most needs to
stop — the forgotten one on a host whose state was cleared — are exactly the ones `do_stop` **cannot
touch**. Reusing it would make the kill switch fail precisely where it matters.

**Measured alternative**: compose stamps every container in a project with
`com.docker.compose.project=<project>`, and a label filter enumerates them with no compose file
present (verified against the live daemon during planning). So the kill switch:

1. enumerates candidates from the **inventory** (FR-002),
2. resolves each to its live containers by **project label**, and
3. stops those containers directly through the runtime.

**This also fixes sidecars.** `<runtime> stop <container-name>` would halt the agent and leave the
egress sidecar and any operator helpers running — and "everything is stopped" would be false. The
label covers the whole project, which is what the operator means.

### 2. Verification means "absent from the RUNNING set", and the distinction is the whole of FR-014

A stopped container still **exists**; it is not running. So "confirm the container is absent from what
the host reports" (FR-014) means absent from the **running** listing — `host_ps_rows(include_stopped=False)`
— not absent from `ps -a`, which would never be true for the stopping form and would make every stop
report failure.

For the **destroying** form the opposite holds: absent from `ps -a`, because the container really is
gone.

Two different queries for two different forms, and conflating them breaks one of them completely.
**One re-query per host** (FR-014's cost bound), after that host's work is done, not per environment.

### 3. Refuse on UNREADABLE; succeed on EMPTY — and say which

FR-013 says refuse when the inventory is "unavailable". Read literally against Feature 014 — which
documents that the store *begins at install and is not backfilled*, so it legitimately does not exist
on a fresh machine — that would make the kill switch refuse for an operator who has simply never
deployed.

The mischief FR-013 names is **silent fallback to live enumeration**. Emptiness does not cause
fallback. So:

| Store state | Action |
|---|---|
| unreadable (I/O error, unparseable entries) | **REFUSE**, naming the store — a narrowed scope is a false guarantee |
| absent or empty | **succeed**, saying *nothing recorded* — and that this means nothing recorded, **not** nothing exists |

The second message matters because Feature 014's own docs warn about exactly this confusion, and here
it would read as "you have nothing running" at the worst possible moment.

**This is the one place the plan reads FR-013 more narrowly than its literal wording**, and it is
recorded here rather than decided quietly at implementation time.

### 4. What gets written back is `notes`, not a new outcome (FR-012)

Feature 014's outcome set is **closed** and describes *existence*, not runstate: `active` / `removed`
/ `vanished` / `host-gone`. A stopped environment is still `active` — it exists. Inventing a `stopped`
outcome would break 014's closed set, and reusing `removed` for a stop would be a lie that survives in
a store a future audit reads.

So:

- the **stopping** form appends to the entry's `notes` (the tool-generated diagnostics field 014
  already defines) and leaves `outcome` alone;
- the **destroying** form sets `outcome = removed`, which is exactly what it means, through 014's
  existing `set_inventory_outcome`.

FR-012's "a later audit reflects what happened" is then satisfied without a second vocabulary.

### 5. A lock we cannot take is UNDETERMINED, never failed and never skipped

`deployment_lock` is per `(host, name)` and **non-blocking** — it `die`s when held. Under a kill
switch, a held lock means a concurrent lifecycle operation, which is the spec's own edge case.

Dying would abort the whole run (violating FR-003). Skipping silently would report success for
something never touched (violating FR-005). So a contended lock yields **could-not-determine** for
that environment, which is the honest answer: we did not stop it and we do not know its state.

### 6. Parallel by host, with a per-host timeout — bounded by the slowest, not the sum

FR-004a and SC-002a. `concurrent.futures.ThreadPoolExecutor` (stdlib — Constitution VI), one task per
**host**, environments sequential within a host so one host's daemon is not hammered and its single
verification re-query stays meaningful.

The timeout is per host and overridable, because the spec's own edge case distinguishes *slow* from
*unreachable* and an operator who knows their host is slow should be able to wait rather than be told
*undetermined*.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI.

**New dependencies**: **none** (Constitution VI). `concurrent.futures` is stdlib.

**Storage**: no new store. Reads Feature 014's inventory; writes back through its existing helpers.

**Testing**: hermetic pytest for enumeration, classification, the refuse/succeed split, the
lock-contention path, and the report's honesty; acceptance for what only real containers show — a
stop that is verified, an unreachable host reported undetermined while others still stop, preview
affecting nothing, and volumes surviving.

**Constraints**:

- **Never report stopped without observing it** (FR-014, SC-002b).
- **One failure must not abort the rest** (FR-003).
- **Never touch a container the tool did not create** (FR-009, SC-004) — the inventory is the
  ownership record, and Feature 014's rule that a name match is *not* ownership applies here with
  teeth: this feature acts, where 014 only reported.
- **Preview affects nothing** (FR-008, SC-007).

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, and it depends on it.** Stopping is safe only because durable work is pushed rather than held in a container — the spec says so, and it is why the stopping form needs no confirmation |
| **II. Least Privilege, Immutable Runtime** | **PASS** — no new capability, nothing in the image; entirely operator-side |
| **III. Least Exposure** | **PASS** — no credential is read, written or transported. The report names hosts and environments, which the inventory already records |
| **IV. Deterministic Identity** | **PASS** — consumes the derivation (`container_name`, `compose_project`); adds none |
| **V. Durable Spec** | **PASS** — clarified in one session, four questions settled before planning |
| **VI. Least Dependencies** | **PASS** — stdlib `concurrent.futures`; no new package |
| **VII. Continuous Deployment** | **`feat`**, minor pre-1.0. Additive: no existing interface changes |

## Project Structure

```text
bin/agent-container       enumeration from the inventory, the per-host parallel executor with its
                          timeout, stop-by-project-label, the per-host verification re-query, the
                          outcome classifier, preview, the `kill` command + --json
docs/inventory.md         the kill switch as the inventory's consumer — 014 remembers, 015 acts
docs/orchestration.md     which form suits which emergency (FR-006a), stated where an operator
                          under pressure will find it
docs/threat-model.md      reconcile — a single action that stops everything is also a single action
                          an attacker with CLI access can invoke
bin/tests/                hermetic classification/refusal/lock-contention/report honesty;
                          acceptance for verified stop, unreachable host, preview, volume survival
```

## Design decisions carried into tasks

1. **Enumerate from the inventory** (FR-002), `active` entries only — `removed` and `host-gone` are
   already accounted for and re-attempting them would manufacture failures.
2. **Stop by project label** (decision 1), never through the compose file.
3. **Verify per host, against the RUNNING set for stop and `ps -a` for destroy** (decision 2).
4. **Refuse unreadable, succeed empty, say which** (decision 3).
5. **`notes` for a stop, `removed` for a destroy** (decision 4).
6. **Contended lock ⇒ undetermined** (decision 5).
7. **Parallel per host, sequential within one** (decision 6).
8. **Exit status follows the worst outcome** — anything unstopped or unconfirmed means overall
   failure (FR-005), including the undetermined cases, because "we do not know" is not success.

## Phasing

**P1 — stop everything, honestly.** US1. Enumerate, act, verify, classify, report. **Write the
unreachable-host test before the happy path**: a kill switch that reports success for a host it never
reached is the one outcome that must be impossible, and it is invisible in a green run.

**P2 — the two forms.** US2. Stop vs destroy, the confirmation asymmetry, and preview.

**P3 — scope.** US3. Subsets, and saying what was excluded.

**P4 — the honest edges.** Repeatability, interruption, contended locks, the inventory refusal, and
the threat-model reconciliation.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A second stop path, by label rather than compose | the compose file lives in host state that dies with its host, and the inventory outlives it — reusing `do_stop` would fail exactly on the forgotten environments this feature exists for | calling `do_stop` per environment — measured to be impossible without the compose file |
| Threads | FR-004a/SC-002a: total time bounded by the slowest host, not the sum | sequential hosts — N unreachable hosts would cost N timeouts, in the one command whose value is speed |
| Reading FR-013 as *unreadable* rather than *absent* | Feature 014's store legitimately does not exist before the first deploy; refusing there would break a fresh install | refusing on absence — turns "nothing recorded yet" into a hard error at the worst moment |
