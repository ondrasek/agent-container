# Contract: Run Observability (Feature 016)

Numbered so tasks and tests can cite them. Each is testable.

## C1 — `runs list` exists and is machine-readable

`agent-container runs list [<environment>] [--json]` lists records newest-first. With `--json` the
payload is `{"runs": [<record>, ...]}` following Feature 009's conventions.

**Silence when nothing happened**: an environment with no runs yields `{"runs": []}` and, in human
mode, one line saying so — not an empty screen an operator has to interpret.

## C2 — `runs show <run-id>` returns one complete record

`--json` emits the record verbatim as stored. Human mode renders it, and MUST render `unknown`
usage as the word, never as `0` (FR-006).

## C3 — A record survives teardown

After `down --purge`, every record for that environment remains retrievable via C1/C2 (FR-001,
SC-001). This is the feature; if it fails, nothing else matters.

## C4 — Teardown ingests BEFORE removing volumes

`down` and `wipe` drain pending records first (FR-001b). **Ordering is the property** — a drain
after removal is not a late drain, it is no drain. A test must fail if the order is swapped.

## C5 — The outcome vocabulary is closed and scoped to kind

Constructing a record with `kind: interactive` and outcome `finished` or `failed` is refused
(FR-003). Every record carries an outcome from its kind's set — zero ambiguous endings (SC-002).

## C6 — `never-started` is authored by the tool

A run whose container never started produces a record with `outcome: never-started`,
`exit_code: null`, and `repository: null`, written by the CLI (research R5).

## C7 — Repository effect distinguishes its states

`repository.state` is one of `ok` · `no-repository` · `no-upstream` · `detached` · `unreadable`,
and each is a record, not an error (research R4, measured).

## C8 — Commit-without-push is LOUD

A run with `commits` non-empty and `pushed: false` is visibly flagged in both human and `--json`
output (FR-005, SC-003) — this is the failure Constitution I exists to prevent.

`pushed` is `null`, never `false`, when there is no upstream to compare against. Conflating "did
not push" with "could not tell" would make the loudest signal in the feature unreliable.

## C9 — Unknown usage is never zero

`usage.reported: false` renders and serialises as unknown (FR-006, SC-004). An aggregate states its
`unknown_components` count rather than excluding them silently (FR-007).

## C10 — Usage is not normalised across agents

`usage.units` preserves the agent's own keys and names the agent (FR-015). No cross-agent total is
offered.

## C11 — A record write never fails the run, and is never silent

A failed record write leaves the run's own exit status untouched (FR-008) and surfaces — as a
`notes` entry when the record exists, and as a warning from the tool when it does not.

## C12 — Concurrency loses nothing

N environments running concurrently produce N complete, non-interleaved records (FR-009, SC-006).

## C13 — No credential value beyond the task text

Every field except `task` is tool-generated or git-derived (FR-010, SC-005). `task` is recorded
verbatim, and the rule is stated where a task is given and in the threat model — not enforced by a
redactor that could miss a value (research R9).

## C14 — Retention is bounded and documented

Records prune by age and count per environment, with documented defaults, at ingestion (FR-011).

## C15 — The record does not replace logs

Documentation states the relationship (FR-014); `runs show` points at `logs` for detail rather than
duplicating it.


## C16 — `runs list --changed <path>` answers SC-007

`agent-container runs list [<environment>] --changed <path> [--json]` returns the runs whose
`repository.paths` contain that path, newest-first.

It reads **stored records only** — no repository access, so it works months later, on a different
machine, and against history that has since been rewritten (research R11).

A run whose `paths_truncated` is true and which does **not** match MUST be reported as an uncertain
result rather than silently omitted: the path may have been in the part that was cut. A confident
"no run changed that file" from a truncated list is the failure this contract exists to prevent.
