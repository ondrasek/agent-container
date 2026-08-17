# Phase 1 Data Model: `doctor`

Three entities from the spec, plus the report that carries them. Nothing here is persisted —
this feature's defining property is that it writes nothing (FR-002), so every structure below
lives for the duration of one command and then goes.

---

## 1. `Check`

One question, asked once.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | stable, kebab-case (`layout`, `image-freshness`, `port-availability`). **The machine-readable key** — a program branches on this, never on the title. |
| `title` | `str` | what the check asks, for a human |
| `scope` | `Scope` | what it is asking *about* (§3) |
| `severity` | `"blocking" \| "advisory"` | the severity of a **failure** of this check, decided by the check, not by the outcome |
| `status` | `"pass" \| "fail" \| "unknown"` | **three states, never two** |
| `finding` | `Finding \| None` | present iff `status != "pass"` |

**`unknown` is not a failure and not a pass.** FR-006 makes it a first-class state, and the whole
feature turns on it: a check that cannot complete and reports *pass* is worse than no check at
all, because it stops the operator looking. A check that cannot complete and reports *fail*
generates work that may not exist.

**Severity is a property of the check, not of the run.** "An unreachable secondary host is
advisory" is a fact about that check; deciding it per-run from the observed outcome would make the
same condition blocking on Tuesday and advisory on Wednesday.

### Status ↔ exit-code contribution

| Status | Severity | Contributes |
|---|---|---|
| `pass` | — | nothing |
| `fail` | `blocking` | **exit 1** |
| `fail` | `advisory` | nothing — advisories MUST NOT fail the run (FR-011) |
| `unknown` | `blocking` | nothing (see below) |
| `unknown` | `advisory` | nothing |

**An `unknown` never produces exit 1**, even on a blocking check. Exit 1 asserts *"a deploy would
not work"*, and `unknown` is precisely the state in which that assertion cannot be made. Failing
the run on `unknown` would break `doctor && up` for anyone whose secondary host happened to be
slow — and a diagnostic people stop chaining is one nobody runs (the spec's own reasoning in the
exit-status clarification). The `unknown` is still *reported*, prominently; it just does not
pretend to be a verdict.

---

## 2. `Finding`

The result of a check that did not pass.

| Field | Type | Notes |
|---|---|---|
| `check_id` | `str` | joins back to the `Check` |
| `severity` | `"blocking" \| "advisory"` | copied from the check, so a consumer reading findings alone is not missing it |
| `observed` | `str` | what was actually seen — the symptom |
| `remedy` | `str` | **the action that fixes it.** Mandatory; there is no finding without one (FR-004, SC-003) |
| `entity` | `str \| None` | which environment / host / image this is about, when a run covers several |

**`remedy` is non-optional at the type level, not by convention.** SC-003 requires *zero* findings
that state only a symptom, and a field that is merely "usually filled in" produces exactly the
finding that is not. A check that cannot name a remedy has not finished being designed.

**Where a deploy already has the message, `remedy` is the SAME STRING** — produced by the same
code, not restated (research R8). SC-008 measures divergence at zero, and two strings that agree
today drift invisibly, since both still read correctly in isolation.

**`observed` must not carry a credential value** (FR-010). For credential checks it names the
*declaration* — source, variable name, path, resolver binary — never a resolved value, which by
R3's design is never retrieved at all.

---

## 3. `Scope`

What a run covers. Determined from the invocation and the working directory, and reported so the
operator can see what was *not* looked at.

| Value | When | Covers |
|---|---|---|
| `environment` | a name was given | that one environment, plus the machine-level checks it depends on |
| `project` | in a project, no name | every environment declared in it, plus machine-level |
| `machine` | no project found | hosts, user configuration, the installed tool |

**`machine` is a success state, not an error** (FR-007). Outside a project, `doctor` reports what
it *can* check and says plainly that no project was found. Failing there would make the command
useless in the case US3 exists for — a new machine, before any project is set up.

---

## 4. `Report`

The whole result of one run.

| Field | Type | Notes |
|---|---|---|
| `scope` | `Scope` | and, when `project`/`environment`, the resolved path or name |
| `checks` | `list[Check]` | **every** check attempted, including passes — the JSON consumer needs to know what was asked, not only what went wrong |
| `findings` | `list[Finding]` | derived: the non-passing checks, blocking first |
| `exit_code` | `0 \| 1 \| 2` | derived (§1); `2` only when `doctor` itself could not run |

**Human output is not the JSON with formatting applied.** FR-014 wants an all-clear an operator
takes in at a glance, so the human view shows findings and a one-line summary of the passes; the
JSON carries every check, because a program that cannot see which checks ran cannot tell "checked
and fine" from "never asked".

**Ordering is blocking-first, then advisory, then unknown**, and stable within each — a report
whose order changes between runs cannot be diffed, and diffing two runs is how an operator
confirms they fixed something.

---

## What is deliberately NOT modelled

- **No persistence.** No cache of previous results, no "last run" file. FR-002 forbids the write,
  and a cached diagnostic is a stale one — the value is that it reflects *now*.
- **No registration of "known good".** Suppressing an advisory the operator has accepted is a real
  need and a different feature; adding it here would mean writing state (FR-002) and would let a
  suppression outlive the reason for it.
- **No repair action on a `Finding`.** `remedy` is prose for a human (spec assumption: "remedies
  are for humans"). A machine-executable remedy invites a `--fix` flag, which is the feature the
  spec puts out of scope in its first line.
