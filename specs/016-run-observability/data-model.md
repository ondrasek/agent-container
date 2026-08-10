# Data Model: Run Observability (Feature 016)

## §1 Run record

One agent execution **or** one interactive session. Written by the container, ingested by the tool.

| Field | Type | Notes |
|---|---|---|
| `schema` | int | starts at `1`. Present so a consumer can refuse a record it does not understand instead of misreading it |
| `run_id` | string | unique, sortable, generated in the container. Also the filename |
| `environment` | string | the environment name |
| `host` | string | the host the run happened on, filled at **ingestion** — the container does not reliably know what the operator calls its host |
| `agent` | string | one of the supported agents |
| `kind` | `headless` \| `interactive` | governs which outcome vocabulary is legal (§2) |
| `task` | string \| null | **null for interactive**, which has none (FR-002). The only free-text field — see §5 |
| `started_at` | string | RFC 3339, UTC |
| `ended_at` | string \| null | null only for a record that is still pending |
| `outcome` | string | from the closed set for `kind` (§2) |
| `exit_code` | int \| null | headless only; null for interactive and for `never-started` |
| `repository` | object \| null | §3. Null means **NOT CAPTURED** — a `never-started` record (C6), or a run whose baseline was never taken. A workspace that holds no repository is captured, as `state: "no-repository"` (C7) — an empty object here would read as "changed nothing", which is a confident answer nobody measured |
| `usage` | object | §4. Always present; `reported: false` when the agent said nothing |
| `notes` | array[string] | tool-generated diagnostics, e.g. a record that could not be written cleanly (FR-008) |

**`run_id` is generated in the container**, not by the tool: a detached run must produce a complete
record with no CLI present. It is sortable so listing is chronological without parsing timestamps.

## §2 Outcome vocabulary — closed, and scoped to `kind`

| `kind` | Legal outcomes |
|---|---|
| `headless` | `finished` · `failed` · `stopped` · `never-started` |
| `interactive` | `ended` · `stopped` |

- `finished` — the agent completed and exited zero.
- `failed` — the agent ran and exited non-zero.
- `stopped` — the container was stopped under it (SIGTERM). Applies to **both** kinds.
- `never-started` — the container never ran. **Authored by the tool**, since nothing inside existed
  to report (research R5).
- `ended` — the operator disconnected from a session. Not a success or a failure; a session has no
  completion semantics.

**`finished` and `failed` MUST be unrepresentable for `kind: interactive`** (FR-003), enforced
where the record is constructed. A rule kept by convention becomes prose the first time a kind is
added, and then SC-002 cannot be measured.

## §3 Repository effect

```json
{
  "start_head": "<sha>|null",
  "end_head": "<sha>|null",
  "branch": "<name>|null",
  "upstream": "<remote/branch>|null",
  "commits": ["<sha>", "..."],
  "paths": ["<repo-relative path>", "..."],
  "paths_truncated": true | false,
  "pushed": true | false | null,
  "state": "ok" | "no-repository" | "no-upstream" | "detached" | "unreadable"
}
```

`paths` is what the run's commits changed, **captured at exit** rather than resolved from the SHAs
later (research R11). This is what makes SC-007 answerable without the repository being present —
and what makes the spec's *"commits later rewritten"* edge case degrade to *"the paths are what
they were at the time"* instead of to an empty result.

`paths_truncated` exists because the list is capped. **The cap is never silent**: a truncated list
that looked complete would answer *"no run changed that file"* with confidence when one did.

`commits` is what `end_head` contains that `start_head` did not. `pushed` compares local against
upstream at exit.

**`state` is required and is not an error channel.** Research R4 measured all three of *no
upstream* (`git rev-parse @{u}` → exit 128), *detached HEAD* (`symbolic-ref -q` → exit 1) and *no
repository* (exit 128) as ordinary situations — an `ephemeral` workspace with no clone is the
common case for a throwaway run. Each must yield a record that says which, not a missing field.

`pushed` is `null` — never `false` — when there is no upstream to compare against. **`false` means
"committed and did not push", which FR-005 requires to be loud**; conflating it with "could not
tell" would make the loudest signal in the feature unreliable.

## §4 Usage

```json
{ "reported": false }
{ "reported": true, "agent": "claude", "units": { "<agent's own keys>": <value> } }
```

Never `0` for an agent that reported nothing (FR-006, SC-004): a false zero silently understates a
total. Never normalised across agents (FR-015) — `units` keeps the agent's own vocabulary and names
the agent, so a consumer cannot accidentally add incomparable numbers.

## §5 The task text — the one field that can carry a credential

`task` is the only free-text field; every other field is tool-generated or git-derived and
structurally cannot carry a secret. That closed field set is what makes the exposure **bounded and
statable** rather than open-ended.

The tool does **not** attempt pattern-based redaction (research R9): a redactor that misses one
value converts an operator's caution into misplaced confidence, which is the same shape as a check
that passes while the thing it names is broken. The rule is stated where a task is given and in
`docs/threat-model.md`, as Constitution III requires.

## §6 Storage layout

```text
$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/<run-id>.json   # durable, operator machine
/var/lib/agent-container/runs/<run-id>.json                              # pending, on the container volume
```

**One file per record** (research R3), written to a temporary name and atomically renamed. Two runs
cannot choose the same name, and a partially-written record is never visible at its final name — so
FR-009 holds without a lock. Pruning is deleting files; listing is reading a directory.

The atomic-write and listing helpers take a directory as a parameter and know nothing about run
records, so **Feature 014 can adopt them** as FR-011a anticipates — shared placement and
write-safety, separate schema and separate retention.

## §7 Lifecycle

```text
container start   -> capture start_head/upstream; write a PENDING record (ended_at: null)
container exit    -> capture end_head/upstream; complete the record, atomically rename
   (SIGTERM)      -> trap: complete with outcome=stopped, then exit within the grace period
tool next contact -> drain pending records from the volume into the durable store, stamp `host`, prune
teardown          -> drain FIRST, then remove volumes (FR-001b)
```

**A pending record is written at start, not only at exit.** A container killed with SIGKILL runs no
trap, so without a record already on the volume there would be nothing at all — and SC-008 requires
a killed run to be recorded. Ingestion completes such a record as `stopped` with `ended_at` unknown
and a note saying it was reconstructed, which is honest about what is and is not known.
