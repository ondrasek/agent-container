# Research: Run Observability (Feature 016)

Phase 0. Each entry records a **decision**, its **rationale**, and what was **rejected** — and
where a fact is claimed, how it was established.

---

## R1 — Where the durable store lives: a SIXTH layout location

**Decision**: `$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/<run-id>.json`
(`~/.local/share/...` when `XDG_DATA_HOME` is unset).

**Rationale**: Feature 011's map defines five locations and run records fit none of them.
`$XDG_STATE_HOME/agent-container/<host>/` is documented **"computed; safe to delete"** — a durable
record kept somewhere safe to delete is a contradiction, and it would quietly make Feature 011's
own description false. `~/.config/` is what the *operator writes*; records are what the *tool
observes*, and mixing them produces a config directory that cannot be hand-edited safely. Project
config travels with the repo and would commit per-machine observations by accident.

XDG's `DATA_HOME` is the category for durable user data. Using it keeps the map honest.

**Rejected**: a sub-directory of the state dir (would falsify "safe to delete"); a dot-directory in
`$HOME` (Feature 011 exists to stop exactly that); the project directory (records are not portable).

**Consequence**: `docs/layout.md` gains a row. Feature 011 declares it the one map, so this is a
change to that feature's artefact, not local knowledge for this one.

---

## R2 — The pending record rides a TENTH volume

**Decision**: `agent-container-<name>-runs`, mounted at `/var/lib/agent-container/runs`,
dev-owned, created in the image.

**Rationale**: FR-001a requires storage that outlives the container, and the two existing
candidates both fail:

| Candidate | Why rejected |
|---|---|
| the **workspace** volume | declared only in `persistent` mode. `bind` and `ephemeral` have none — and a disposable headless run is exactly where those modes are used |
| **`shellenv`** (`~/.agent-env`) | always present, but **operator-writable by design**: any shell in the container can rewrite it. The account of a run must not live where the subject of the account can edit it |

**Consequence — an identity change, and the lesson is already paid for.** `per_container_volumes`
carries an exact-equality doctest, `--purge` and `wipe` enumerate the list, and an existing
environment has nine volumes where a new one has ten. Container name, port and every existing
volume name are unchanged, so **the identity check passes while the deployed shape differs** —
precisely the blind spot Feature 012's T118 documented and T129d proved runs in *both* directions.
Migration must be handled on adoption *and* on rollback.

**A named volume's mount point must exist in the image, dev-owned** (CLAUDE.md invariant): a
runtime-created mount point is `root:root` and rootless cannot write it, even under a dev-owned
parent. So `/var/lib/agent-container/runs` is created in the Dockerfile, not by the entrypoint.

---

## R3 — One file per record; concurrency solved by construction

**Decision**: each record is a single JSON file, written to a temporary name in the same directory
and **atomically renamed** into place. No append, no lock.

**Rationale**: FR-009 forbids interleaving, overwriting and loss under concurrency. An append-only
file needs a lock that works across local and remote hosts, two container runtimes, and a daemon
that may not share a filesystem — a lot of machinery to get a property that a rename gives free.
Rename is atomic on every filesystem in scope, and two runs cannot select the same name.

Pruning becomes deleting files; listing becomes reading a directory; a partially-written record is
never visible because it is never at its final name.

**Rejected**: JSONL with `fcntl` locking (does not survive a remote daemon or a mounted filesystem
that lies about locks); SQLite (a dependency, and Constitution VI); one file per environment
appended in place (the interleaving FR-009 forbids, reintroduced).

**FR-011a says Feature 014 shares this.** 014 does not exist yet, so 016 builds the machinery — and
must build it as something 014 can adopt: the atomic-write and directory-listing helpers take the
directory as a parameter and know nothing about run records. **Shared placement and write-safety;
separate schema and separate retention.**

---

## R4 — Repository effect from git, captured at start and exit (MEASURED)

**Decision**: the entrypoint records `HEAD` and the upstream-tracking position at start and again
at exit. The difference is what the run committed; local versus upstream at exit is whether it
pushed.

**Rationale**: FR-004a requires this to work without agent cooperation, because the run that most
needs a record is the one where the agent crashed.

**The edge cases are not hypothetical, and the exit codes matter.** Measured, unpiped:

| Situation | Command | Exit |
|---|---|---|
| no upstream configured | `git rev-parse @{u}` | **128** |
| normal | `git rev-parse HEAD` | 0 |
| detached HEAD | `git symbolic-ref -q HEAD` | **1** |
| detached HEAD | `git rev-parse HEAD` | 0 |
| not a repository | `git rev-parse HEAD` | **128** |

So all three of *no upstream*, *detached HEAD* and *no repository* are ordinary states that must
produce a record saying so, not an error and not a silently empty field. A workspace in `ephemeral`
mode with no clone is the common case for a throwaway run.

**A trap worth recording, because this project has now hit it three times.** The first probe read
`$?` after piping git through `head`, and reported **exit 0 for every failing case** — `$?` is the
last element of the pipeline. It is the same defect CLAUDE.md already records for
`quality-gate.sh | tail`, and it would have produced a research entry that was confidently wrong.
**Measure exit codes unpiped.**

---

## R5 — The outcome vocabulary is closed, scoped to kind, and enforced at construction

**Decision**: headless → `finished` · `failed` · `stopped` · `never-started`.
Interactive → `ended` · `stopped`. Enforced where the record is constructed.

**Rationale**: FR-003 forbids *finished*/*failed* on an interactive session, because a session has
no completion semantics. A rule enforced only by convention degrades into prose the first time
someone adds a kind, and then the field cannot be aggregated — which is what SC-002 measures.

**`never-started` is authored by the TOOL, not the container.** By definition nothing inside ran, so
nothing inside can report. It is the one record the CLI writes directly, and that asymmetry has to
be explicit or the ingestion path will assume every record arrives from a volume.

**`stopped` requires the entrypoint to trap the signal.** A container stopped by the runtime gets
SIGTERM; without a trap the process dies and the exit path never runs, so the record is simply
absent — and SC-008 requires a killed run to produce one. The trap must write the record and then
exit, and it must not exceed the runtime's stop grace period, or the record is lost to SIGKILL.

---

## R6 — Unknown is a value; usage is never normalised

**Decision**: usage is `{"reported": false}` unless the agent reported it; when reported it is
stored in the agent's own units with the agent named. Aggregates carry an explicit
`unknown_components` count.

**Rationale**: FR-006 and SC-004 forbid a false zero, which silently understates a total — and a
total that is quietly wrong is worse than one that admits a gap. FR-015 forbids normalising across
agents: the four supported agents do not report comparable units, and inventing parity would
produce a number that looks authoritative and is not.

**Rejected**: omitting the field when unreported (indistinguishable from a schema change, and
consumers would read absence as zero); a `0` sentinel (the exact failure SC-004 names).

---

## R7 — Ingestion happens on next contact, and teardown ingests FIRST

**Decision**: any CLI command that talks to a host drains that host's pending records before doing
its work. `down` and `wipe` drain **before** removing volumes.

**Rationale**: FR-001b, and the spec's edge case *"teardown before ingestion"*. Removing the volume
first destroys the account of the run being torn down — the single most likely moment for the
record to matter and the easiest to lose.

**Ordering is the property**, exactly as it was in Feature 012's entrypoint: a drain that runs
after removal is not a late drain, it is no drain. It must be asserted by a test that fails if the
order is swapped, not left to reading the code.

---

## R8 — Retention is defined, documented and enforced

**Decision**: records are pruned by age and by count per environment, with documented defaults;
pruning runs at ingestion.

**Rationale**: FR-011 requires bounded growth and says records are expected to be pruned
*actively*, unlike Feature 014's inventory which must keep its oldest entries. This is the concrete
reason the two stores are separate (FR-011a) — sharing one would give one of them the wrong
retention.

Pruning at ingestion avoids a background process, which would be a new moving part with no home in
a CLI that runs on demand.

---

## R9 — The task text is the one field that can carry a secret, and that is stated rather than filtered

**Decision**: the task text is recorded verbatim. No pattern-based redaction. The exposure is
documented in `docs/threat-model.md` and stated where a task is given.

**Rationale**: FR-010 forbids credential values in records; FR-002 requires the task text; the
spec's own edge case admits the collision. Every other field is tool-generated or git-derived and
structurally cannot carry a secret — the field set is closed, which is what makes this bounded.

A regex redactor was rejected on the same grounds this project rejected other
looks-like-a-check mechanisms: **one that misses a value converts an operator's caution into
misplaced confidence**, and it would be a check that passes while the thing it names is broken.
Saying plainly "the task text is recorded verbatim; do not put credentials in it" is weaker
protection and stronger information.

**Constitution III requires this reach the threat model**, not just a docstring.

---

## R10 — How ingestion actually reads the volume (MEASURED)

**Decision**: a throwaway container mounts the runs volume and streams its contents to the CLI's
stdout: `docker run --rm -v <runs-volume>:/mnt alpine tar cf - -C /mnt .`

**Rationale**: R7 said teardown drains pending records "before removing volumes" and never said
*how*. That omission matters precisely where this feature is aimed — a **remote** host. Three
machines are involved and only one of them has the operator's store:

| Machine | Holds |
|---|---|
| operator's machine | the durable store, `$XDG_DATA_HOME/agent-container/runs/` |
| the container host (possibly a VPS) | the volume with pending records |
| the container | wrote them, and is typically gone by now |

There is **no shared filesystem** between the first two, so the records cannot be read directly and
`docker cp` has no container to copy from once the run has exited.

**Measured**, not assumed:

| Check | Result |
|---|---|
| a fresh container reads a volume whose writer is gone | **yes** — file listed and read back |
| contents stream out as a tarball on stdout | **yes** — `./demo.json` present in the stream |

stdout is what makes this work across a remote Docker context: the throwaway container runs on the
remote daemon, and only bytes cross the boundary.

**Rejected**: `docker cp` (needs a container; the writer has exited); mounting the volume on the
operator's machine (impossible for a remote host, which is the case that matters); an agent or
sidecar that uploads records (a network dependency, a credential, and a new thing to fail — for a
file already sitting on a volume).

**Consequence for tasks**: ingestion needs the runtime, not the filesystem. It therefore belongs
with the other `driver_*` argv builders, and it must be exercised against a **remote context** in
acceptance — a test that only ever runs locally would pass while the remote path, the one this
mechanism exists for, was never executed.

---

## R11 — Which run changed a file: capture the PATHS, do not resolve the SHAs later

**Decision**: the entrypoint records the **changed file paths** in the record at exit, alongside
the commit SHAs. The query is then a lookup over stored records and touches no repository.

**Rationale**: SC-007 requires an operator to identify which of N runs changed a given file. The
record holds commit SHAs, and a SHA is not a file list — so something has to bridge them. There
are only two moments where that can happen, and they are not equivalent:

| | Resolve at QUERY time | Capture at WRITE time |
|---|---|---|
| needs the repository present | **yes**, months later, on the machine asking | no |
| survives rewritten history | **no** — the spec's own edge case | **yes** — paths were recorded when the commits existed |
| survives the repository being deleted or moved | no | yes |
| cost | a git call per candidate run, per query | one `git diff --name-only` at exit |

Query-time resolution fails exactly when the record is most valuable: long after the run, on a
machine that may not have the repository, against history someone has since rebased. The spec
already anticipates this — *"a run whose commits were later rewritten … must degrade gracefully"* —
and capture-at-write-time is what makes that graceful rather than a lookup returning nothing.

**So one decision closes two findings**: SC-007 becomes answerable (G1), and the rewritten-history
edge case degrades to *"the paths are what they were at the time"* rather than to an empty result
(G3).

**The list must be bounded, and the bound must be stated.** A run that touches ten thousand files
would otherwise write a record larger than everything else combined. Capped, with an explicit
`paths_truncated` flag — **never a silent cap**, because a truncated list that looks complete would
answer SC-007 with a confident *"no run changed that file"* when one did. That is the shape this
project keeps finding: a check that passes while the thing it names is broken.

**Rejected**: storing a full diff (this is a summary, not a log — the feature's first assumption);
resolving lazily and caching (all the fragility of query-time resolution plus a cache to invalidate);
recording only the commit count (does not answer the question at all).
