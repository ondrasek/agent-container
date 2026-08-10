# Run observability — the durable account of a run (Feature 016)

Constitution I guarantees the *work* survives a container: every agent commits and pushes, so code
is never trapped. Nothing guaranteed the **account** of the work survived. A headless run exited
with a status and wrote logs into a container the tool then encourages you to destroy, and
afterwards there was no answer to *which of last night's four runs broke the build, did it push,
and what did it cost*.

Every run — headless or interactive — now leaves one small JSON **record** that outlives its
container.

```bash
agent-container runs list                      # every environment on the default host
agent-container runs list demo --json
agent-container runs show 20260809T101010Z-ab12
agent-container runs list demo --changed src/auth/session.py
```

## What a record is

One run, one file, one closed set of fields.

| Field | Comes from | Notes |
|---|---|---|
| `schema` | tool | starts at `1`, so a consumer can refuse a record it does not understand instead of misreading it |
| `run_id` | tool | generated **in the container**, sortable, and the filename |
| `environment` · `host` | tool | both stamped at **ingestion** — the container is never told what your registry calls its host |
| `agent` · `kind` | tool | `kind` is `headless` or `interactive` and governs the outcome vocabulary |
| `task` | **operator** | the only free-text field — see [the task text](#the-task-text-is-the-one-field-that-can-carry-a-credential) |
| `started_at` · `ended_at` | tool | RFC 3339 UTC; `ended_at` is null only while the run is still in flight |
| `outcome` | tool | from the closed set for its `kind` |
| `exit_code` | tool | headless only; null for a session and for a run that never started |
| `repository` | git | what it committed, whether it pushed, which files it touched |
| `usage` | agent | in the agent's own units, or **unknown** — never zero |
| `notes` | tool | diagnostics — a record reconstructed at ingestion, a capture that hit a cap, a write that did not go cleanly |

**That table is the whole of the no-credentials claim.** Exactly one row says `operator`; every
other value is composed by the tool or read out of git, so there is no other field a credential
would be put in. The field set being closed is what makes the exposure bounded and statable rather
than open-ended — which is why a test asserts the table itself rather than trusting this sentence,
and why ingestion warns rather than staying quiet when a record arrives carrying a field this build
does not declare.

## What a record is NOT

**It is not the logs, and it never tries to be.** The two have opposite lifetimes: the record
outlives the container and the logs do not. A summary that *looked* like log output would promise
detail that is already gone, so `runs show` says it in as many words and points at the command that
still has them while the container lives:

```text
this is a summary, not the logs.
logs, while the container lives: agent-container logs demo
```

Logs are voluminous, agent-specific and already retrievable from a live container. Storing them
here would produce a store nobody prunes and nobody reads, and it would drown the small structured
thing you can actually list, compare and search months later.

It is also **not a judgement**. A record says what a run did, never what it should have done.

And it is **not evidence against the agent**. A record is written inside the container, on a volume
the agent could write to, so it is the container's own account of itself. That is exactly right for
the cases it exists for — a crash, a kill, a run nobody watched — and it is not proof against an
agent that set out to misreport. See [`docs/threat-model.md`](threat-model.md) T16.

## Where records live

Two locations, because of one constraint: **when a detached run ends, the entrypoint is the only
thing left to write anything down.** Detached is the *default* headless mode, so a design that
recorded only foreground runs would miss the case the feature exists for.

| Location | Holds | Lifetime |
|---|---|---|
| `/var/lib/agent-container/runs/<run-id>.json` — the `-runs` volume | the **pending** record | until the tool ingests it, or the volume is removed |
| `$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/<run-id>.json` | the **durable** record | yours; outlives every container |

`~/.local/share/...` when `XDG_DATA_HOME` is unset. [`docs/layout.md`](layout.md) is the one map
and explains why this is neither derived host state (documented *safe to delete*; a run that
already ended cannot be recomputed) nor configuration (what you *write*, not what the tool
*observes*).

**One file per record, written to a temporary name and atomically renamed.** Concurrency is solved
by construction rather than by a lock that would have to work across two runtimes, a remote daemon
and a filesystem that may lie about locking: two runs cannot choose the same name, and a
half-written record is never visible at its final one. Pruning is deleting files; listing is
reading a directory.

## How a record gets from the container to you

```text
container start   capture HEAD/upstream; write a PENDING record to the volume
container exit    capture HEAD/upstream again; complete the record, atomic rename
   (SIGTERM)      trap: complete it as `stopped`, within the runtime's grace period
next contact      the tool drains the volume, stamps host + environment, prunes
teardown          drain FIRST, then remove volumes
```

**The pending record is written at start, not only at exit.** `docker kill` sends SIGKILL, which
runs no trap — without a file already on the volume a killed run would leave nothing at all.
Ingestion completes such a record as `stopped` with `ended_at` unknown and a note saying it was
reconstructed, which is honest about what is and is not known.

**Draining happens on contact, not on a schedule.** `up`, `redeploy`, `down`, `wipe`,
`runs list` and `runs show` each drain that host first, so listing a detached run that finished
thirty seconds ago finds it rather than answering "no runs".

**Teardown drains BEFORE it removes.** Ordering is the property, not an optimisation: a drain
placed after volume removal is not a late drain, it is no drain — and an environment being
destroyed is the single most likely moment for its record to matter. `down` also *stops* the
container before draining, because `compose down --volumes` kills the container and drops its
volume in one step, leaving no instant at which the entrypoint's own final record could be
collected.

Ingestion reads the volume by running a throwaway container that streams its contents to the
tool's stdout. There is no shared filesystem between your machine and a VPS, and `docker cp` needs
a container that has already exited — only bytes cross the boundary, so the remote host, which is
the case this feature is aimed at, works the same as a local one.

**One record the tool writes itself**: `never-started`. Nothing inside the container ran, so
nothing inside could report. It goes straight to the durable store, with `exit_code` and
`repository` null — a `0` would read as a clean run that never happened, and an empty repository
effect would claim the run changed nothing when the truth is that it never looked.

## How a run ended

The vocabulary is closed and **scoped to the kind**, enforced where the record is constructed.

| `kind` | Legal outcomes |
|---|---|
| `headless` | `finished` · `failed` · `stopped` · `never-started` |
| `interactive` | `ended` · `stopped` |

`finished` and `failed` are *unrepresentable* for a session, not merely discouraged: a session has
no completion semantics, and a rule kept by convention becomes prose the first time a kind is
added — after which "zero ambiguous endings" cannot be measured at all. `ended` means the operator
disconnected; `stopped` means the container went away underneath, and is the one outcome legal for
both kinds.

## What the run changed

Read out of git by the entrypoint at start and at exit, with **no agent involvement** — the run
that most needs a record is the one where the agent crashed.

```json
"repository": {
  "start_head": "…", "end_head": "…", "branch": "main", "upstream": "origin/main",
  "commits": ["…"], "paths": ["src/auth/session.py"], "paths_truncated": false,
  "pushed": true, "state": "ok"
}
```

**`state` is not an error channel.** `ok` · `no-repository` · `no-upstream` · `detached` ·
`unreadable` are all ordinary situations that must each produce a record saying which — an
`ephemeral` workspace with no clone is the common case for a throwaway run, not a failure.

**Commit-without-push is loud**, in the listing and in `--json`, because it is the failure
Constitution I exists to prevent:

```text
! 1 run(s) COMMITTED WITHOUT PUSHING — the work is only in the container: 20260809T101010Z-ab12
```

`pushed` is **`null`, never `false`, when there is no upstream to compare against**. `false` means
"committed and did not push"; conflating it with "could not tell" would make the loudest signal in
the feature unreliable.

In `runs list --json` the alarm is the `unpushed` key — a list of run ids beside `runs`, derived
once by the tool so a consumer cannot forget to re-derive it. It is **always present, even empty**,
as is `usage`; a key that appeared only when it had something to say would make "nothing to report"
and "this build does not report it" indistinguishable. `uncertain` appears with `--changed`, the
only mode in which the concept exists. `runs show --json` adds nothing: it is the record verbatim.

**`paths` is captured when the run ends, not resolved from the SHAs later.** That is what lets
`runs list --changed <path>` answer months afterwards, on a machine that never had the clone, and
against history someone has since rebased. Both the path list and the commit list are capped at
200 entries — a run touching ten thousand files would otherwise write a record larger than
everything else combined — and the cap is **never silent**: `paths_truncated` travels with the
record, a note names the real total, and a run whose truncated list does not match is reported as
*uncertain* rather than omitted. A confident "no run changed that file" built on a list that was
cut is the failure that command exists to prevent.

## What it cost

```json
{ "reported": false }
{ "reported": true, "agent": "claude", "units": { "input_tokens": 10 } }
```

**Unknown is a value, never a zero and never an absent key.** A false zero silently understates
every total it enters, and an omitted key is read as zero by any consumer. Human output renders it
as the word.

**Usage is never normalised across agents.** `units` keeps the agent's own vocabulary and names the
agent beside it, and there is deliberately **no cross-agent total** — two agents' `input_tokens`
are not the same quantity, and a key that added them would produce the one number a reader would
quote and it would mean nothing. Aggregates carry an `unknown_components` count at every level
rather than quietly dropping the runs that reported nothing.

**Today every record says unknown**, and that is a fact about invocation rather than a gap: the
entrypoint runs `claude -p`, `codex exec`, `pi -p` and `opencode run` — the prose forms. None is
asked for a machine-readable report, so there is nothing to parse and nothing is invented. A test
pins those invocations, so the day one starts reporting, the extraction has to be written rather
than a real figure being quietly filed as unknown.

## Retention

**90 days, or 500 records per environment — whichever prunes first.** Both bounds apply; they
bound two different things (a machine that runs constantly, and one that ran a burst a year ago).
Pruning happens at **ingestion**, so there is no background process and no `runs rm`: a record's
lifetime is a documented rule rather than an operator action that could be taken on one machine and
forgotten on another.

500 records is roughly a year of four nightly runs; 90 days is past the point where a run's commits
are ordinary history. The figures in `runs --help` are interpolated from the constants that do the
deleting, and a test binds **the two above** to those same constants in both directions — a
documented number the code does not use is this repository's recurring defect, and this page is
where an operator would come to read one.

Unlike Feature 014's host inventory, which is small and must keep its oldest entries indefinitely,
run records accumulate with every run and lose value quickly. That opposite retention need is
precisely why the two are separate stores, even though they share placement and the same
atomic-write machinery.

## The task text is the one field that can carry a credential

**The task is recorded verbatim. The tool does not redact it. Do not put a credential in a task.**

Pattern-based redaction was rejected rather than skipped. A redactor that misses one value converts
an operator's caution into misplaced confidence — the same shape as a check that passes while the
thing it names is broken — and it would license exactly the habit this warning exists to
discourage. Saying it plainly is weaker protection and strictly better information.

The exposure is **bounded** because the field set is closed: `task` is the only operator-authored
value in a record, and widening that set is the change that would make the no-credentials claim
false. It is recorded as an accepted residual risk in [`docs/threat-model.md`](threat-model.md).

Stored records are written `0600` for that reason. A *pending* record still sits on a container
volume, where the agent that ran and the host operator can both read it — the same exposure as
anything else on a volume, which is why the store the tool keeps is elsewhere.

## When a record is lost

Two losses are possible, and both are said out loud rather than left to be inferred from a store
that is quietly short of runs.

- **A write that failed inside the container** never fails the run — the exit path must not become
  a new way for a successful run to report failure — but it surfaces, as a `notes` entry when a
  record exists and as a tool warning when it does not.
- **A runs volume removed outside the tool** (`docker volume rm`, a pruned host, a rebuilt VPS)
  takes every record still pending on it. The tool detects the gap — a deployment that still
  declares the volume on a host that answered and no longer has it — and says so. It stays silent
  when the daemon could not be asked at all: a warning that cries wolf on a host that is merely
  asleep is one an operator learns to scroll past, which would cost exactly the case it exists for.

## See also

- [`docs/layout.md`](layout.md) — where the store lives and why it is neither state nor config
- [`docs/threat-model.md`](threat-model.md) — the task-text exposure, as an accepted residual risk
- [`docs/execution.md`](execution.md) — headless runs, `--task`, and workspace modes
- [`docs/agent-interface.md`](agent-interface.md) — the `--json` conventions `runs` follows
