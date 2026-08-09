# Implementation Plan: Run Observability

**Branch**: `016-run-observability` | **Date**: 2026-08-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-run-observability/`

## Summary

Every run gets a small durable record that outlives its container: which environment and agent,
what it was asked, how it ended, what it committed, whether it pushed, and what it cost.

**The shape of the problem is a handoff, not a store.** Detached headless runs are the default, so
at the moment a run ends there is no CLI attached to write anything down — only the entrypoint is
present. So the container writes a summary to a volume, and the tool ingests it into a durable
user-level store the next time it talks to that host (FR-001a). Everything else in this plan
follows from that split.

**It is deliberately not a log store.** Logs stay where they are. What is missing is the small
structured thing you can list, compare and search months later.

## The four decisions this plan settles first

Each is forced by the spec, unresolved by it, and changes every task downstream.

### 1. The store needs a SIXTH location, because none of the five fits

Feature 011's layout map has five locations. Run records fit none of them:

| Candidate | Why it is wrong |
|---|---|
| `$XDG_STATE_HOME/agent-container/<host>/` | documented **"computed; safe to delete"**. A record that is safe to delete is not durable — this is the whole feature |
| `~/.config/agent-container/` | configuration is what the operator *writes*; records are what the tool *observes*. Mixing them means a `config` directory an operator cannot hand-edit safely |
| project config `.agent-container/` | travels with the repo; records are per-machine observations and would be committed by accident |

So records live in **`$XDG_DATA_HOME/agent-container/runs/`** — durable user data, the XDG category
that exists for exactly this. **This is a change to `docs/layout.md`**, which Feature 011 makes the
one map, and it must be made there rather than left as local knowledge.

### 2. The pending record needs a TENTH volume, and that is an identity change

The nine-volume contract is identity-locked and tested. A record must survive the container, so it
needs a volume, and the alternatives are worse:

- **the workspace volume** — absent entirely in `bind` and `ephemeral` modes, which is where a
  disposable headless run is most likely to live;
- **`shellenv` (`~/.agent-env`)** — always present, but it is *operator-writable by design*: a shell
  inside the container can rewrite anything there. Putting the account of the run in a place the
  subject of the account can edit is the wrong shape, whatever the practical risk.

So: a tenth volume, `agent-container-<name>-runs`, mounted at `/var/lib/agent-container/runs`.

**Treat it as a migration, not an edit** — the T118/T129d lesson from Feature 012. `--purge` and
`wipe` enumerate the volume list, `per_container_volumes` has an exact-equality doctest, and an
existing environment has nine volumes while a new one has ten. The identity check will pass on
name and port while the deployed shape differs, which is precisely the class of drift the identity
lock cannot see.

### 3. One file per record — concurrency is solved by construction, not by locking

FR-009 forbids interleaving, overwriting or loss under concurrency. A single append-only file needs
locking that must work across hosts, runtimes and a possibly-remote daemon.

One file per record, written to a temporary name and **atomically renamed** into place, cannot
interleave: rename is atomic on every filesystem in scope, and two runs cannot pick the same name.
Pruning becomes deleting files. Listing becomes reading a directory.

**This is the machinery FR-011a says Feature 014 will share** — shared placement and shared
write-safety, separate schema and separate retention. 014 does not exist yet, so 016 builds it, and
must build it as something 014 can adopt rather than as something private.

### 4. The task text is the one place a credential can legitimately arrive

FR-010 forbids any credential value in a record. FR-002 requires the task text. The spec's own edge
case notes the collision: *"nothing recorded may contain a credential; the task text itself may."*

Resolved as: **the task text is recorded, and it is the only free-text field.** Everything else is
tool-generated or git-derived and cannot carry a secret. The tool does not attempt pattern-based
redaction — a redactor that misses one value is worse than none, because it converts an operator's
caution into misplaced confidence.

What the tool does instead is **state the rule where the task is given** and never widen the field
set. This is a documented, bounded exposure rather than a silent one, and it goes in the threat
model (Constitution, Development Workflow) rather than being solved by a regex.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell in the entrypoint.

**New dependencies**: **none.** Records are JSON written with the stdlib; PyYAML remains the only
third-party dependency (Constitution VI).

**Storage**: `$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/<run-id>.json` on the
operator's machine; `/var/lib/agent-container/runs/` on a per-container volume in transit.

**Testing**: hermetic pytest for record construction, outcome vocabulary, redaction-free field set,
pruning and ingestion; acceptance for the claims that are only true of a real container — that a
record survives `down --purge`, that a killed run still records, that a detached run is ingested on
next contact, and that concurrent environments do not lose records.

**Constraints**:

- **The record must survive teardown** (FR-001) — so ingestion happens *before* volume removal.
- **A record write must never fail the run** (FR-008) — the entrypoint's exit path cannot become a
  new way for a successful run to report failure.
- **No agent cooperation** (FR-004a) — the git capture works for an agent that crashed.
- **Detached is the default** (SC-002a) — a design that only works with the CLI attached fails the
  case the feature exists for.

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, and this is the principle the feature serves.** Constitution I guarantees the *work* survives; nothing guaranteed the *account* of it did. FR-005 exists because commit-without-push is the failure I is written to prevent |
| **II. Least Privilege, Immutable Runtime** | **PASS** — no new capability, no runtime install. The entrypoint writes a file to a volume it already owns |
| **III. Least Exposure** | **PASS with a NAMED, BOUNDED exposure** — decision 4. The task text is recorded because FR-002 requires it and it is operator-authored; every other field is tool- or git-derived. Recorded in the threat model, not solved by a regex |
| **IV. Deterministic Identity** | **AT RISK — decision 2.** A tenth volume changes the deployed shape while name and port stay identical. Handled explicitly as a migration; T118/T129d showed both directions must be handled |
| **V. Durable Spec** | **PASS** — clarified in two sessions before planning |
| **VI. Least Dependencies** | **PASS** — no new dependency; one file per record is chosen partly *because* it needs no lock library |
| **VII. Continuous Deployment** | **PASS** — `feat`, minor pre-1.0. The tenth volume is a breaking shape change and its commit must say so |

## Project Structure

```text
bin/agent-container        record construction, ingestion, listing, pruning, retention
image/entrypoint.sh        start/exit git capture; write the pending summary on every exit path
docs/layout.md             the SIXTH location (decision 1) — Feature 011's map is the one map
docs/observability.md      new: what a record is, what it is not, retention, the task-text rule
docs/threat-model.md       reconcile: the task-text exposure (Constitution requires this)
bin/tests/                 hermetic construction + vocabulary + pruning; acceptance for survival
```

## Design decisions carried into tasks

1. **The container writes; the tool ingests.** The entrypoint is the only thing present when a
   detached run ends, and a summary on a volume outlives the container.
2. **The outcome vocabulary is closed and scoped to the kind** (FR-003). *finished* and *failed*
   must be unrepresentable for an interactive session — enforced at construction, not by
   convention, or the field degrades to prose.
3. **`never started` is written by the TOOL, not the container.** By definition the container never
   ran, so nothing inside it can report. This is the one record the CLI authors directly.
4. **Repository effect from git, at start and exit** (FR-004a) — `HEAD` and upstream-tracking
   position. The difference is what it committed; local vs upstream at exit is whether it pushed.
   No agent involvement, so it works for an agent that crashed.
5. **Unknown is a value, not an absence** (FR-006/FR-007). Usage is `unknown` unless reported, and
   an aggregate that includes an unknown says so. A false zero silently understates a total.
6. **Usage is never normalised** (FR-015) — stored in the agent's own units with the agent named.
7. **Teardown ingests first** (FR-001b) — `down` and `wipe` pull pending records before removing
   the volume that holds them.
8. **Retention is defined and enforced** (FR-011), and pruning is deleting files.
   **The defaults are 90 days and 500 records per environment**, whichever prunes first. Named
   here rather than left as "documented defaults", because FR-011 requires retention to be
   *defined* — and T041 checks that the documented number is the enforced one, which is
   unanswerable while no number exists. 500 records is roughly a year of four nightly runs; 90 days
   is past the point where a run's commits are ordinary history.

9. **`stopped` needs no kill switch.** The spec lists Feature 015 as a dependency for
   distinguishing a stopped run from a failed one. 015 is unbuilt, and it is **not a blocker**: a
   container stopped by `down`, `stop` or the runtime receives SIGTERM, which is what T014's trap
   observes. 015 would add an operator-facing way to *trigger* that stop; the record does not care
   who sent the signal. Stated because a reader checking dependencies would otherwise conclude this
   feature cannot ship until 015 does.

## Phasing

**P1 — the record exists and survives.** US1. The tenth volume, the entrypoint's exit write, the
store, ingestion, `--json` listing. **Prove a record survives `down --purge` before building
anything on top of it**; if it does not, the feature has no foundation.

**P2 — the record means something.** US2. Start/exit git capture, commit list, push status, and
FR-005's loud commit-without-push. This is what makes the record worth keeping.

**P3 — cost.** US3. Usage where reported, `unknown` where not, aggregates that admit gaps.

**P4 — the honest edges.** Killed runs, never-started runs, write failures that surface without
failing the run, concurrency, retention, and the threat-model reconciliation.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A sixth layout location | records are durable; state dir is documented safe-to-delete | reusing state dir — it would make "safe to delete" false, and Feature 011's map is load-bearing |
| Changed paths stored in the record | SC-007 must be answerable without the repository, months later, against rewritten history | resolving SHAs at query time — fails exactly when the record is most valuable (research R11) |
| A tenth volume (identity change) | the record must outlive the container in every workspace mode | `shellenv` — operator-writable by design; workspace — absent in bind/ephemeral |
| Record-writing logic in the entrypoint | only the entrypoint is present when a detached run ends | CLI-side capture — misses detached runs, which are the default |
| Storing raw task text | FR-002 requires it | pattern redaction — a redactor that misses one value converts caution into misplaced confidence |
