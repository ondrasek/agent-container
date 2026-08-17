# Contract: `agent-container doctor`

The observable surface. Each clause is testable, and each names the failure it exists to prevent.

---

## Command

```
agent-container doctor [NAME] [--host <host>] [--json]
```

| | |
|---|---|
| `NAME` | optional; narrows to one environment (FR-007) |
| `--host` | optional; overrides host resolution, as elsewhere |
| `--json` | the Feature 009 envelope. `doctor` is **in** the JSON set — `NO_JSON_COMMANDS` stays `{host env, completions, attach, menu}`, and two existing tests fail if it drifts (R7) |

---

## C1 — Strictly read-only

Running `doctor`, in any scope, with any outcome, MUST leave **zero** observable change to files,
containers, volumes, images or registry entries (FR-002, SC-002).

**Permitted**: an SSH socket-forward for a provisioned host, which outlives nothing (R2).
**Forbidden by construction**: `migrate_flat_state()`, `drain_host_records()`,
`record_inventory_creation()`, and every other helper that writes (R1).

> *Fails without this*: `migrate_flat_state()` is the first line of `do_up` and self-describes as
> *"safe to call repeatedly"*. Reusing it relocates files while every check still reports
> correctly — the feature broken and the output identical.

## C2 — All problems in one pass

One run MUST report **every** detected problem (FR-003, SC-001). No check may end the run.

> *Fails without this*: every existing validator `die()`s on the first problem. An operator fixes
> one thing, re-runs, finds the next — the exact experience `doctor` exists to replace.

## C3 — Every finding names a remedy

A `Finding` without a `remedy` MUST NOT be constructible (FR-004, SC-003).

## C4 — The remedy is the SAME STRING a deploy would give

For a condition a deploy already reports — the pre-011 layout above all — the remedy MUST come
from the same producer, not a copy (SC-008, R8).

> *Fails without this*: two strings that agree today drift the moment one is edited, and both
> still read correctly alone, so nothing catches it.

## C5 — Three states, and `unknown` is never `pass`

Every check reports `pass` / `fail` / `unknown` (FR-006). A check that times out, errors, or
cannot be answered without a side effect reports **`unknown`**.

> *Fails without this*: a diagnostic that reports healthy is what stops an operator looking
> further. Failing open is worse than not checking.

## C6 — Severity separates blocking from advisory

Each check declares whether its **failure** blocks a deploy (FR-005). Severity is a property of
the check, not derived per-run from the outcome.

## C7 — Exit status: 0, 1 or 2. Never more.

| Code | Meaning |
|---|---|
| `0` | a deploy would succeed — **advisories and unknowns permitted** |
| `1` | at least one **blocking** check **failed** |
| `2` | `doctor` itself could not run |

An advisory failure MUST NOT produce non-zero (FR-011). An `unknown` MUST NOT produce `1`
(data-model §1).

> **`3` and above are unavailable.** Feature 019 shipped a tool-wide table where `3` means
> *pending registration*, documented in `--help` and pinned by a test. FR-011's original
> "2 or greater" predated it (R4) and now reads **exactly 2**; **FR-011a** pins the `unknown`
> case and **SC-004a** measures both.

## C8 — No prompt, ever

No check may trigger an interactive prompt (FR-009). Manager-source credentials are checked by
**resolver-binary presence**, never by resolving (R3).

> *Fails without this*: `op read` against an approval-gated item raises a system dialog. A
> diagnostic that makes the operator approve a secret access to answer "is this configured" is one
> they will not run twice.

## C9 — No credential value is retrieved, let alone printed

`doctor` MUST NOT call `resolve_credential_value()` (FR-010, Constitution III). Findings name the
*declaration* — source, variable, path, binary — never a value.

> Stronger than "must not print": a value never retrieved cannot leak through a log, a traceback
> or a `--json` field somebody adds later.

## C10 — One bad check does not silence the rest

An unreachable host, a hung helper or a raising check MUST NOT prevent other checks from being
reported (FR-008), and MUST NOT extend the run past its bound.

## C11 — Outside a project is a success

With no project in the current directory, `doctor` reports machine-level checks and states plainly
that no project was found. It MUST NOT fail (FR-007).

> *Fails without this*: US3's whole scenario is a new machine, before any project exists.

## C12 — An unreachable host is reported as unreachable

Never as healthy, never as absent (SC-005). Each host is reported individually.

## C13 — Image freshness compares locally, and absence is `unknown`

The image carries an `org.opencontainers.image.version` label stamped at build from the building
CLI's version; `doctor` compares it against the installed version with **no network and no
registry round-trip** (FR-012a).

An image with **no** label reports `unknown` — never fresh, never stale (FR-012b).
When `_resolve_version()` cannot determine a version, `build` MUST **omit** the label rather than
stamp `0.0.0+unknown` (R5).

> *Fails without this*: reporting unstamped images stale nags every operator into a rebuild they
> may not need; reporting them fresh asserts something unknown.

## C14 — A healthy environment's own port is not a conflict

Port availability is a **blocking** finding only when the port is held by something that is not
this environment's own container (R10).

> *Fails without this*: the port is derived from the name, so a running environment always occupies
> "its" port — and `doctor` would fail on every healthy deployment.

## C15 — `doctor` failing is distinguishable from an unhealthy environment

Exit `2` plus a message that says the *command* could not run (FR-013). Never presented as a
finding about the environment.

## C16 — All clear is brief

A fully healthy run produces output an operator assesses at a glance — findings and a one-line
summary of what passed, not a wall of green (FR-014, SC-007). The `--json` view still carries
**every** check, including passes.

## C17 — The minimum check set

At least: project layout validity · per-environment configuration resolution · credential
resolvability (per C8) · host reachability · image freshness · port availability (FR-012).

---

## Non-goals, restated as contract

- **No `--fix`, no repair, no migration.** Reporting only.
- **No persistence** — no cache, no suppression file (data-model §4).
- **No agent health inside a container** (observability, 016) and **no egress policy evaluation**
  (012).
