# `doctor` — would a deploy work? (Feature 013)

Everything a deploy needs used to be checked **at the moment of deploying**, and nowhere else. So
every unmet precondition was learned the same way: a command you expected to succeed failed
instead.

`doctor` inverts that. It answers **"would a deploy work, and if not, why"** without attempting one
and **without changing anything**.

```sh
agent-container doctor                 # this project's environments + the machine
agent-container doctor acme            # narrow to one environment
agent-container doctor --json          # the machine-readable report
```

## It changes nothing — and that is enforced structurally

`doctor` writes no file, creates no container, volume or image, and touches no host-registry entry.
That is not a promise about intent: the command **composes read-only readers** and deliberately
cannot reach the deploy path's setup helpers.

That matters more than it sounds. The helpers a deploy calls *first* are the ones that mutate, and
the most dangerous is `migrate_flat_state()` — it opens `up`, `redeploy` and `list`, it relocates
files on disk, it is idempotent, and its own docstring says *"safe to call repeatedly."* It reads as
harmless. A test walks the transitive closure of reachable names from the command and asserts those
helpers are **unreachable**, which catches what a before/after snapshot cannot: a call that exists
but that the test project never happened to trigger.

**One deliberate exception**: an SSH socket-forward for a provisioned host. It creates none of the
artifact kinds above and does not outlive the command, and without it every provisioned host would
report *unreachable* — a false negative on the check you asked for. The line is **nothing that
outlives the command**.

## Three statuses, and `unknown` is one of them

| Status | Meaning |
|---|---|
| `pass` | the check was answered, and the answer is fine |
| `fail` | the check was answered, and it is a problem |
| **`unknown`** | the check **could not be answered** |

A check that cannot complete reports `unknown` — **never** `pass`. A diagnostic that reports healthy
is what stops you looking further, so failing open is worse than not checking at all. Reporting
`fail` instead would be the opposite error: it manufactures work that may not exist.

Every finding — including an `unknown` — names **the action that resolves it**, not just the
symptom. A finding without a remedy cannot be constructed.

## Severity, and what the exit code means

Severity belongs to the **check**, not to the run: "an unreachable secondary host is advisory" is a
fact about that check, and deriving it per-run from the outcome would make the same condition
blocking on Tuesday and advisory on Wednesday.

| Code | Meaning |
|---|---|
| `0` | a deploy would succeed — **advisories and unknowns permitted** |
| `1` | at least one **blocking** check **failed** |
| `2` | `doctor` itself could not run |

**Nothing above 2**: `3` means *pending registration* tool-wide (Feature 019), so a `doctor`
returning it would tell an automated caller something false about an SSH key.

**An `unknown` never produces `1`.** Exit `1` asserts that a deploy would not work, and `unknown` is
precisely the state in which that assertion cannot be made. Failing the run on one would break
`doctor && up` for anyone whose secondary host happened to be slow — and a diagnostic people stop
chaining is a diagnostic nobody runs.

```sh
agent-container doctor && agent-container up acme    # the intended idiom
```

## What is checked

| Check | Severity | Notes |
|---|---|---|
| `runtime-present` | blocking | docker or podman on `PATH` |
| `tool-version` | advisory | `unknown` when unresolvable — which is also why freshness is unknown |
| `user-config` | advisory | absent is a **pass**; a fresh machine has none |
| `host-reachability` | advisory | **each host individually**, bounded; one dead host never suppresses another |
| `layout` | blocking | pre-011 layout — the same remedy string a deploy prints |
| `credentials` | blocking | see below |
| `port-availability` | blocking | held by **its own** container is a pass |
| `image-freshness` | advisory | local label comparison; no registry |

### Credentials are checked without being resolved

For a manager source, **resolving is the prompt**: `op read` against an approval-gated item raises a
system dialog, and `doctor` must never do that as a side effect of answering a question. So:

| Source | What is checked | Result |
|---|---|---|
| `env` | is the variable set | pass / fail |
| `file` | does the path exist | pass / fail |
| `keychain`, `onepassword`, `bitwarden`, `command` | is the resolver binary on `PATH` | fail if absent, else **unknown** |

No credential **value** is ever retrieved — stronger than "never printed", because a value never
read cannot leak through a log, a traceback, or a field somebody adds later.

The binary check is not a consolation prize: *"`op` is not installed"* is the most common real
failure on a new machine, and it is free to detect.

### Image freshness needs a rebuild first

`build` stamps the building CLI's version into the image as an
`org.opencontainers.image.version` label, and `doctor` compares it locally — **no network, no
registry round-trip**. A label rather than an `ENV`, because reading it must not start a container.

An image with **no** label predates stamping and reports **`unknown`** — never fresh, never stale.
So every image built before this feature reports unknown until rebuilt, which is correct rather
than unfortunate: reporting it stale would nag you into a rebuild you may not need, and reporting it
fresh would assert something nobody knows.

When `build` cannot determine its own version it **omits** the label and says so, rather than stamp
`0.0.0+unknown` — a meaningless value that looks like an answer is worse than an honest absence.

## Outside a project

`doctor` degrades to machine-level checks and says plainly that no project was found. **That is a
success, not an error** — the case it matters most for is a new machine, before any project exists.

## What it deliberately does not do

- **No repair, no `--fix`, no migration.** Reporting only. A diagnostic that changes things is one
  you have to think about before running.
- **No persistence** — no cache, no "known good" suppression file. Both would need a write, and a
  cached diagnostic is a stale one.
- **No agent health inside a container** (that is observability, Feature 016) and **no egress policy
  evaluation** (Feature 012).
