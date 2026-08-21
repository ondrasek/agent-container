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

**"At start" means FIRST — and there is still a window it cannot cover.** The entrypoint opens the
record before the shell-env seed, the SSH host key and the git identity, so that everything which
can `die` during setup is accounted for too. What it cannot cover is the interval before it runs at
all: a runtime reports a container `Up` the moment its process is created, and on an idle Linux
host the record lands 0.3-0.6s later, most of it bash starting up. A container killed inside that
interval leaves no record, and no ordering fixes that — there is no run yet to record. Runs killed
after their agent has started are the ones this guarantees.

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
deleting, and a test binds **both figures on this page** to those same constants in both directions —
a documented number the code does not use is this repository's recurring defect, and this page is
where an operator would come to read one.

### The count is spent on distinct UTC days first

The 500 is not "the newest 500". It is filled **one record per UTC day, newest day first, round and
round** until it runs out — so the newest run of every day that has one survives before any day gets
a second record.

The reason is the tool's own restart policy. A headless run is deployed with `restart: on-failure`
and no retry limit, so an agent that cannot start at all — a missing credential, an unresolvable
clone URL — is restarted for as long as the operator leaves it running, and every restart writes a
record. Measured: **9 records in about 40 seconds**, which is thousands overnight. Under a plain
"keep the newest 500" that one burst evicts every older record of the environment, including the
runs that show what it was doing before it broke. The store stays bounded and becomes worthless:
the letter of FR-011 with none of its point.

**The allocation has no number of its own, and that is the point rather than a detail.** An earlier
version of this rule gave any single UTC day at most half the count. It held for a burst that stayed
inside one day and failed for the scenario it was written for: an *overnight* loop crosses UTC
midnight by construction, and two days sitting at half the bound each consume all 500 slots before
an older day is ever examined. Measured on that rule — 600 records on one day left all 30 days of
prior history intact, and **500** records split across two days deleted every one of them. Fewer
records, total loss. Any fixed share S has the same hole at `500/S` buckets; round-robin takes the
share from the data instead, so K days get `500/K` apiece and there is no midnight to cross.

Round-robin is a **priority, not a third bound**. Every day empties before the count is reached, so
**nothing is deleted while the store is under the count bound** — a rule that deleted today's 251st
run from a store holding 251 records would be losing data for no space.

The cost, stated rather than left to be discovered: while a day holds more records than its round,
the survivors are no longer a contiguous "everything since *date*" window, so `runs list --changed`
is thinner across that day than it would have been. That is the incompleteness any prune creates,
placed on the day that produced thousands of identical records instead of on the days that produced
distinct ones.

The egress store next door uses the same mechanism with a different axis — the **destination**
rather than the day — because the burst it has to survive is one endpoint an agent retries. Same
rule, two axes, one implementation.

### What pruning will not do

- **It never deletes a record that has not been ingested yet.** Pruning reads the durable store and
  nothing else; a record still pending on a container volume is not a candidate. An un-ingested
  record leaves nothing behind, so its loss would be the one loss nobody could notice.
- **It never deletes a record in the same command that rescued it.** A host switched off for four
  months hands over records that are all past 90 days, and the drain removes the volume copy before
  retention runs — so the age bound skips whatever this drain has just taken custody of. They are
  pruned on a later contact, by which time they have been readable at least once and the
  announcement names them. The *count* bound still applies: being outnumbered by 500 newer records
  is a different story from being old.
- **It never deletes the newest record of an environment under the count bound.** The newest record
  is first in the fill order and its day is the first day walked. (The *age* bound will delete it
  once it is 90 days old — that is the rule doing its job, and it is the only way an environment's
  store legitimately becomes empty.)
- **It never treats a clock as gospel.** A record's age comes from the run's own `started_at`, which
  is written inside a container, clamped to the moment this store wrote the record down — no run can
  have started after the tool recorded it. Without that clamp a `started_at` in the future is newer
  than every cutoff the age rule can compute, so the record is immortal *and* holds a count slot
  forever; measured, 600 such records evicted all 30 real ones and ten years' passage removed none.
- **It is never silent.** Every prune logs the count, the rule that took the records and the range
  of run ids removed, on stderr — so it is present in `--json` mode too, where the deletion would
  otherwise be invisible to the agent FR-012 exists for.

Unlike Feature 014's host inventory, which is small and must keep its oldest entries indefinitely,
run records accumulate with every run and lose value quickly. That opposite retention need is
precisely why the two are separate stores, even though they share placement and the same
atomic-write machinery.

The same split now has a second consumer. Feature 012's **egress events** live in
`egress/<host>/<environment>/` beside the run records: same placement, same atomic write and the
same listing helper, their own schema and their own retention rule — theirs spends the count bound
on distinct *destinations* first, because the burst it has to survive is one endpoint an agent
retries rather than one night of restarts. See [egress.md](egress.md#the-durable-record--what-was-refused-after-the-container-is-gone).

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

---

# The dual stack — a local trail and an active export (Feature 017)

Feature 017 widened the above from "run records" to **the tool's whole observability trail**, and
added a second leg.

**Two legs, one payload.**

| Leg | What it is |
|---|---|
| **the local trail** | the **durable baseline**. Written where the action lands, regardless of any endpoint. |
| **OTLP export** | an **additional active path**, to a collector you declare. |

They are **independent, not alternatives**. The local record exists whether or not you configure an
endpoint, and export never replaces it.

## They carry identical payloads, from one definition

`RECORD_PAYLOAD_FIELDS` is **derived** from `RECORD_FIELD_PROVENANCE` rather than written out again.
Two lists would agree today and drift the moment one was edited — and **the drift would be
invisible**, because each leg still looks correct on its own. Nothing would fail until someone
compared them, which is exactly what reconciliation does and exactly what it could not do if the
halves carried different things.

Three classes, one shape: **attribution records** (which control plane did what), **run records**
(Feature 016), and **egress events** (Feature 012).

## The export state — what the client can actually observe

Every record carries one, and it is `pending` at birth.

| Value | Means | Retry? |
|---|---|---|
| `pending` | written; not yet resolved with the endpoint | **yes** |
| `accepted` | the **configured endpoint returned success for this record** | no |
| `rejected` | the endpoint explicitly refused it | **no** — it will refuse again unchanged |
| `failed` | unreachable, or an error | **yes** — it may be back later |

### `accepted` does NOT mean it arrived at a backend

It means the configured endpoint returned success for that record and **nothing more**. Establishing
arrival would require querying the backend's own API — the vendor coupling this feature refuses, and
the same coupling that makes end-to-end ingestion unobservable in the first place. There is
deliberately no `ingested` or `confirmed` state.

### A 2xx is not acceptance

OTLP's export response carries `partialSuccess` with a rejected-record count, so **a receiver may
return 200 while refusing records**. That count is subtracted before anything is marked `accepted`.
An implementation that skipped it would record refused records as delivered — and the local leg would
then claim a delivery the collector never made.

`rejected` and `failed` stay distinct because they decide whether retrying helps. Collapsing them
would either retry forever against a refusal or abandon a recoverable record. `accepted` and
`rejected` are **terminal**: re-exporting an accepted record duplicates it at the collector.

State is derived from the **response**, never from the fact that an attempt was made.

## Export mechanics

A `curl` POST of a JSON document, from the entrypoint. **Zero Python packages, zero image
additions** — `curl` and `jq` already ship. OTel is used at the **protocol level only**; no
backend-specific package, ever, and a test checks the declared distribution set rather than the
import list.

**It fires at write time, per record** — not batched at exit, not on a timer. Anything held for later
is lost exactly when a container is `kill -9`'d, which is the circumstance under which someone later
asks what happened. It also needs no resident exporter.

**It is fail-open.** An unreachable or undeclared collector degrades to the local record, reports the
gap, and never blocks the work. Under enforced egress, silence here would yield an empty collector
that reads like a quiet system — the most misleading outcome an audit trail can have.

## Declaring an endpoint

`settings.yaml`, at either config level, **project winning** — the tool's existing two-level
contract:

```yaml
# ~/.config/agent-container/settings.yaml  (or .agent-container/settings.yaml)
otlp_endpoint: https://collector.example/v1/logs
export_task_text: true          # the default
```

A URL without a scheme is **refused, not prefixed**: guessing would decide, on your behalf, whether
the trail crosses the network in plaintext.

Export is **outbound traffic a Feature 012 declaration governs**. If you enforce egress, declare the
collector or export will be blocked — fail-open, so the work continues and the gap is reported.

## The task text

**Exported by default**, because a task is **not a credential channel**: credentials reach a
container by injection, the single exception being the SSH keys a container generates itself.
Withholding it would design around an operator error the tool already provides the correct
alternative for — and it is the most useful field for *"this run failed, what was it doing"*, on a
phone, with no laptop to correlate against.

**Pointing this at a shared backend therefore shares your tasks.** To exclude it:

```yaml
export_task_text: false
```

**Excluded by name, never by pattern.** There is no regex, no entropy heuristic and no
"looks-like-a-token" check. A redactor that misses one value converts caution into false confidence;
omitting a named field either happens or it does not.

**`run_id` exports regardless.** That is what makes the exclusion cheap rather than lossy — without
correlation, excluding the task removes the reason to look at the record at all.

## Getting the trail off the hosts

```sh
agent-container telemetry collect          # every host
agent-container telemetry retry            # re-export pending/failed
agent-container telemetry reconcile        # do the two legs agree?
```

`collect` works **whether or not** an endpoint is declared — the local record exists
unconditionally, so its retrieval must too. It is Feature 016's `drain` **generalised**, not a second
puller.

It reports **per-host counts and names every host it could not reach**, and carries a `complete`
flag. "Collected nothing" and "collected nothing *from that host*" are different facts, and a skipped
host must never read as a complete trail.

`retry` re-exports `pending` and `failed` only. There is no override flag: the terminal states are
terminal, and forcing them would duplicate records or repeat refusals.

## Reconciliation — do the two legs agree?

```sh
agent-container telemetry reconcile --collector-ids ids.txt
```

Over a window — **since the last successful `collect`**, or a range you supply — the set of records
marked `accepted` locally must equal the set your collector holds, **or the difference is reported**.
Zero silent divergence, in **both** directions:

- locally `accepted`, absent at the collector → the local leg claims a delivery that did not land;
- at the collector, not `accepted` here → a second exporter, a replay, or a lost local store.

**`pending` records are outside the window.** They have not finished exporting, and counting them as
divergence would fail this against a healthy system with exports in flight.

**The tool does not query your collector.** That would be the vendor coupling described above, so you
run your backend's own query and hand over the ids; the tool does the comparison it can do without
coupling. Without that file it reports **no comparison was made** — never "no divergence", which
would assert agreement that was never checked.

The watermark advances **only after a complete `collect`**. A partial one that advanced it would make
the next reconciliation treat the unreached hosts as "before the window" and silently exclude exactly
the records that are missing.

## See also

- [`docs/control-plane.md`](control-plane.md) — the control plane, and what attribution records
- [`docs/layout.md`](layout.md) — where the store lives and why it is neither state nor config
- [`docs/threat-model.md`](threat-model.md) — the task-text exposure, as an accepted residual risk
- [`docs/execution.md`](execution.md) — headless runs, `--task`, and workspace modes
- [`docs/agent-interface.md`](agent-interface.md) — the `--json` conventions `runs` follows
