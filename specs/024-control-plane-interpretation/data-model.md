# Phase 1 data model: Interpreting control plane

Two new signal classes, one extended role, and a watermark. Nothing here introduces a new store: the
signals go to the telemetry stack, the role extends the inventory entry that already exists.

---

## Signal 1 — Agent output stream (`log`)

The agent's stdout/stderr, exported as it is produced (FR-007). **Not** a record and never folded
into one (FR-010).

| Field | Source | Notes |
|---|---|---|
| `run_id` | 016, generated in-container | the correlation key; the same value the run record carries |
| `environment` · `host` | attribution, from the existing definition | identical to the record's, derived from one source so the two cannot drift (017's rule) |
| `agent` · `mode` | entrypoint | already composed into `_otel_attrs` today |
| `timestamp` | entrypoint | per batch flush, not per line |
| `body` | **the agent** | the output text. The widest operator-visible surface this tool exports. |
| `stream` | entrypoint | `stdout` or `stderr`, kept distinct because an agent's error channel is where the useful part usually is |
| `truncated` | exporter | present only once, when the per-run cap is reached (FR-008) |

**Provenance is the whole exposure claim, as in 016.** Exactly one field — `body` — carries content
this tool did not compose, and it carries whatever the agent printed. That is broader than the run
record's single operator-authored `task` field, which is why FR-007b requires the consequence to be
stated when an endpoint is declared, and why the exclusion is by name (FR-007c) rather than by any
pattern.

**Ordering.** Batches carry a monotonic sequence per run so a consumer can detect a gap rather than
silently reading an incomplete stream as complete.

**Lifecycle.** Produced from container start to exit; bounded by the per-run cap; retained by the
stack's retention (023), not by this feature.

---

## Signal 2 — Interpretation

The interpreter's reading of one run (FR-011, FR-012). A judgement, kept apart from the record it
concerns so the two can never be confused when read back (016: a record is never a judgement).

| Field | Source | Notes |
|---|---|---|
| `interpretation_id` | interpreter | stable identity, so a revision is distinguishable from a duplicate |
| `interpreter` | interpreter | **which interpreter claims this.** Required: two interpreters, or an impostor on an unauthenticated ingest, must be distinguishable rather than merged |
| `run_id` · `environment` · `host` | the run being interpreted | the join back to the trail |
| `produced_at` | interpreter | |
| `state` | interpreter | what the interpreter believes the run is or was doing |
| `assessment` | interpreter | the reading itself |
| `confidence` | interpreter | `sourced` or `inferred` — FR-011a requires a claim it cannot source to be labelled as inference |
| `evidence[]` | interpreter | see below; FR-011a requires every claim be traceable |
| `contradictions[]` | interpreter | where record and log disagree (FR-011b), each naming both sides |
| `input_health` | interpreter | the state of the stack, hosts and log availability at the time (FR-013) |
| `observed_directives` | interpreter | instruction-shaped text found in agent output, quoted as content (FR-014) |

### Evidence

An interpretation's claims resolve to one of these, and nothing else:

| Kind | Points at |
|---|---|
| `record_field` | a run record and a named field in it |
| `log_span` | a run identifier plus the sequence range of the quoted lines |
| `absence` | a thing that was looked for and was not there — which is a fact, and FR-013 forbids inferring activity from it |

`absence` exists as a first-class kind deliberately. Without it, "no output since 14:02" has no way
to be evidence, and the interpreter would either drop the claim or assert it unsourced.

---

## Signal 3 — Notification bookkeeping

What has already been reported (FR-017), written as produced so it survives the container (R4).

| Field | Notes |
|---|---|
| `interpreter` | whose bookkeeping this is; two interpreters do not share a ledger and do not deduplicate each other |
| `event_key` | identifies the event, not the message: `run_id` + event kind + the state that triggered it. This is what makes catch-up idempotent — the same event recomputed after a restart produces the same key and is not re-sent |
| `reported_at` · `delivered_at` | distinct: a notification held by an unreachable channel is decided at one time and delivered at another (FR-018) |
| `delivery_state` | `sent` · `held` · `delayed` · `failed` |
| `held_reason` | `channel_unreachable` or `silence_window` — FR-019 requires held events to be marked as held when they arrive |

**Why the key is the event and not the message.** An interpreter that recorded "I sent message N"
would, after a restart, have to reconstruct which message corresponded to which event; keying on the
event lets the notifier be a pure function of the trail plus this ledger, which is what makes FR-017
catch-up work without duplicates (SC-008).

---

## Entity — Interpreter (extends the existing inventory entry)

An environment with `role = interpreter`. `ROLES` grows from two to three.

| Field | Notes |
|---|---|
| `role` | `interpreter`, distinct from `agent` and `control-plane` (FR-002) |
| `agent` | any member of `AGENTS`; none privileged (FR-003) |
| `watched_scope` | hosts and environments it reads. A **snapshot at deploy**, as 017's host registry is — a host registered afterwards is invisible until redeploy, and the interpreter says so rather than appearing to have looked |
| `stack` | the tool-managed telemetry stack it reads and writes. A prerequisite; absence is a refusal naming it (R3) |
| `channel` | `slack`, plus the conversation it is bound to |
| `declared_sender` | the Slack workspace member whose messages it will answer (FR-023). No default admits anyone |
| `notification_policy` | notifiable-event set, stall window, digest schedule, silence window — each a named default (R6) |
| `authority` | `observe` — the only value this feature defines (FR-020) |

**Credentials it holds** (FR-006, delivered per Constitution IX, never in the deployment
description): the Slack bot token — which lets its holder *speak as the interpreter to the operator*
and is listed as a credential for that reason — and the stack's address. **Not** the control plane's
standing key, and there is no runtime client in the image to use one with.

---

## Entity — Watermark

How far through the trail the interpreter has read.

| Field | Notes |
|---|---|
| `interpreter` · `signal` | one watermark per signal class per interpreter |
| `position` | the last point consumed |
| `advanced_at` | |

**It advances only after the events in a window have been recorded in the bookkeeping ledger.** 017's
reconcile watermark carries the same rule for the same reason: a watermark advanced before the work
settled makes the next pass treat unprocessed items as "before the window", which silently excludes
exactly the events that were missed.

---

## State transitions

**Run, as the interpreter sees it** — derived from the trail, never from having been present:

```text
  observed ──────────► interpreted ──────► notified
     │                      │                  │
     │                      ▼                  ▼
     └──► unreadable    stalled          held ──► delivered
          (schema it    (no output for
           refuses to    the stall window,
           misread,      reported as a
           FR-029)       duration, not a
                         verdict, FR-015b)
```

**Notification delivery:**

```text
  decided ──► sent
     │
     ├──► held (silence window) ──────► delivered, marked held
     └──► delayed (channel down) ─────► delivered, marked delayed, in order
```

A run that ends while the interpreter is stopped enters at `observed` on its return and proceeds
normally, arriving marked late — because the pipeline reads the trail rather than events it
witnessed.

---

## What is deliberately not modelled

- **No agent session data.** No transcript, tool-call or memory entity exists, because FR-025
  excludes them from export and from reading. Their absence from this model is the requirement.
- **No action, command or confirmation entity.** FR-020a forbids a dormant path toward the future
  authority feature; a modelled-but-unused action type is exactly such a path.
- **No second copy of the run record.** The interpreter reads 016's record as it is. Restating its
  fields here would create the drift 017 avoided by deriving its payload from one definition.
