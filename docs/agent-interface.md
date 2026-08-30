# Agent Interface — driving `agent-container` from an AI agent (Feature 009)

`agent-container` is built for a human at a terminal, but increasingly the caller is an
**AI coding agent**. This document is the contract such an agent can rely on.

> **Direction.** Feature 004 runs agents **inside** the container. This is the inverse: an
> agent **outside**, on your machine, **driving the CLI**. The two lists are independent.

## `--json`: opt in per invocation

Every command accepts `--json` and then emits **one** JSON object on **stdout**:

```json
{ "schema": "agent-container/v1", "ok": true,  "data":  { … } }
{ "schema": "agent-container/v1", "ok": false, "error": { "code": "…", "entity": "…", "message": "…", "remedy": "…" } }
```

- `schema` is on **every** payload — check it before relying on field names.
- `ok` agrees with the exit status (non-zero ⇔ `ok: false`).
- **stdout carries only the envelope.** Human prose, progress and build logs go to
  **stderr** — including a container build's output, which is redirected there in JSON mode
  so it can never corrupt the payload.
- **No secret value ever appears in a payload.**

### Compatibility

| Change | Version bump? |
|--------|---------------|
| Adding a field · adding a new `code` | ✅ no |
| Renaming/removing a field · changing a `code`'s meaning | ❌ yes — `schema` bumps |

### Commands without `--json`

`host env`, `completions`, `attach`, `menu`. The first three have stdout that is **`eval`'d
or consumed as a stream**, so wrapping it would break `eval $(…)`; `menu` is the interactive
wizard. This set is asserted by the test suite, so a new command cannot silently opt out.

## `-v` / `--verbose`: on every command, in every position

Unlike `--json`, verbose has **no exceptions** — every command takes it, groups
included, and it is accepted before or after the subcommand:

```bash
agent-container -v attach acme
agent-container attach -v acme
agent-container attach acme --verbose
```

All three are equivalent. A flag an operator has to *place* correctly is one they
will place wrongly, and the error for that ("no such option") reads as though the
flag does not exist.

**It always writes to stderr**, never stdout, so it composes with `--json`:

```bash
agent-container list -v --json | jq .   # still parses; diagnostics went to stderr
```

**What it prints** is every child process the tool executes, with its argv:

```
[agent-container] + query: podman ps -a --format '{{.Names}}\t{{.Status}}'
[agent-container] + exec: ssh -p 2206 -o StrictHostKeyChecking=yes dev@localhost -t tmux attach -t main
```

That second line is the one worth knowing about: it is printed immediately before
`attach` hands the process over to `ssh`, which is the **last** moment anything
can be printed at all — `execvp` replaces the process, so nothing after it runs.
When an attach misbehaves, that line is the exact invocation, reproducible by
hand.

**Printing argv is safe by construction, not by redaction.** This tool never puts
a secret on a command line — credentials are delivered over the container's own
sshd and read from files (Constitution III/IX) — and that property is asserted by
tests. So `-v` is not a leak; it is a way to watch the invariant hold.

**The flag is injected, not declared per command.** One declaration is added to
every command in the tree at startup, so a command added tomorrow has it without
anyone remembering. A test walks the built tree and fails if any command lacks
it — which is how `attach -v` came to be missing in the first place.

## `list --json`: both public keys travel with the row

Each container row carries two captured **public** keys, or **`null`** when nothing
was captured — one per direction:

- **`known_hosts_entry`** (Feature 018) — the `known_hosts`-format line the tool
  pinned, which verifies the container on the way **in**.
- **`agent_ssh_public_key`** (Feature 019) — the key the container generated for
  itself, which the operator registers so the agent can authenticate on the way
  **out**. The same value is what `agent-container ssh-key show <name>` prints.

```json
{"containers": [
  {"name": "agent-container-acme", "host": "local", "port": 2206,
   "known_hosts_entry": "[localhost]:2206 ssh-ed25519 AAAAC3Nz...",
   "agent_ssh_public_key": "ssh-ed25519 AAAAC3Nz... dev@agent-container-acme"}
]}
```

`null`, never `""` — a JSON consumer must be able to tell *never captured* from a
captured value.

### `list --json` also says what it could NOT see (Feature 017)

```json
{"containers": [...], "unreachable_hosts": ["dead-vps"], "complete": false}
```

`complete` is `false` the moment a host did not answer. The rows already carry a
`status: "unreachable"` marker, but a consumer would have to scan and infer — and
the failure being guarded is a consumer reading a **short list as a complete
one**. An explicit field is the difference between *"there are no containers
there"* and *"nobody asked successfully"*.

## The telemetry payload (Feature 017)

Both observability legs — the local trail and the OTLP export — carry **one field
set**, derived from a single definition. A field added to that definition reaches
both without a second edit.

Feature 017 added three fields to the record shape documented in
[`observability.md`](observability.md):

| Field | Provenance | Notes |
|---|---|---|
| `attribution` | `tool` | which control plane performed the action; `null` for the operator's own machine |
| `egress_decision` | `tool` | Feature 012 events |
| `export_state` | `tool` | see below |

All three are `tool` provenance, deliberately: `task` remains the **only**
operator-authored field in the whole table, and that single row *is* the
no-credentials claim. A second free-text field would falsify it while every other
test still passed.

### `export_state`

```
pending | accepted | rejected | failed
```

`pending` at birth, on every record. **`accepted` means the configured endpoint
returned success for that record and nothing more** — never arrival at a backend,
which would require querying the backend's own API. There is no `ingested` or
`confirmed` value, and a consumer must not treat `accepted` as delivery.

`rejected` and `failed` are distinct because they decide whether a retry helps.
`accepted` and `rejected` are terminal.

### `telemetry` envelopes

`collect` reports per host and names what it missed:

```json
{"collected": 12, "hosts": [{"host": "vps1", "ingested": 12, "status": "ok"}],
 "unreachable": ["vps2"], "complete": false}
```

`reconcile` reports the comparison, and whether one happened at all:

```json
{"window": {"since": "2026-08-20T09:00:00Z", "until": null},
 "local_accepted": 40, "collector_holds": 39, "pending_excluded": 3,
 "missing_at_collector": ["20260821T1000Z-ab12"], "unknown_locally": [],
 "compared": true, "agree": false}
```

`agree`, **not** `ok`. The envelope already carries a top-level `ok` meaning *the
command ran*; a second `ok` inside it meaning *the legs agree* is how a consumer
reads agreement off a run that compared nothing. `agree` is `null` when
`compared` is `false`.

Field types do not change between branches: `local_accepted` is a count in both,
and the id lists are `null` rather than absent when no comparison was made.

## `doctor --json`: every check, not only the problems

The report carries `scope`, `scope_target`, `exit_code`, `checks_run`, `checks` and `findings`.

**`checks` lists every check that ran, passes included.** A consumer that sees only failures cannot
tell *"checked and fine"* from *"never asked"* — and those call for opposite reactions. `checks_run`
is the same information as a flat list of ids, for a caller that only wants to know coverage.

```json
{"scope": "project", "scope_target": "/src/acme", "exit_code": 1,
 "checks_run": ["credentials", "host-reachability", "layout", "runtime-present"],
 "checks": [{"id": "layout", "scope": "project", "severity": "blocking",
             "status": "fail", "finding": {"check_id": "layout", "severity": "blocking",
             "observed": "…", "remedy": "…", "entity": "acme"}}],
 "findings": [{"check_id": "layout", "…": "…"}]}
```

**Branch on `status` and `severity`, never on prose.** `status` is `pass` / `fail` / **`unknown`** —
three values, because a check that could not be answered is not a pass. `severity` is `blocking` or
`advisory`, and it describes the CHECK rather than the run.

**`exit_code` is 0, 1 or 2 and never more.** An `unknown` never yields 1: exit 1 asserts that a
deploy would not work, which is exactly what `unknown` cannot assert. See
[`docs/doctor.md`](./doctor.md).

**No credential value ever appears here** — `doctor` never retrieves one. `observed` names the
declaration (source, variable, path, resolver binary), which is what makes the absence structural
rather than a filter someone has to maintain.

**Only ever public halves.** Neither private key exists outside the container: 018
removed the host key from the operator's disk, 019 removed the agent key. There is
no field, and no command, that would hand one back.

**Read from local state, never the daemon.** So it still answers for a stopped
environment or an unreachable host, which is exactly when it is needed: recovering
verified access to something you cannot reach. A field that required reachability would
fail in the one case it exists for.

**This is the right way to trust a container from a second machine.** Copy the line
from the machine that deployed. That entry **predates** what it checks; a key accepted
at `attach`'s prompt does not, because at that moment the runtime can only say *"the
container currently called X"* — never *"the container you created"*.

## Failures

Branch on **`code`**, never on `message` (whose wording may change):

```json
{"code": "host_not_registered", "entity": "hz1",
 "message": "no host named 'hz1' (see: agent-container host ls)",
 "remedy": "agent-container host ls"}
```

`unspecified` is a valid, documented code for call sites not yet annotated — handle it.
Failures are emitted **before any change** wherever the tool's fail-fast discipline applies.

## `context` — load the world in one call

```bash
agent-container context --json
```

Returns `target`, `stages` (tri-state: `satisfied` / `unsatisfied` / `unusable` — *present
but broken* is distinct from *absent*), `hosts`, `environments`, `conventions`,
`credentials`, `problems`, and a suggested `next_step`.

It is **valid in every state**: an unconfigured machine yields empty collections, and an
unreachable host is a *described state*, not a failed call. **Credentials appear as
locators only** — a variable name, a path, a vault coordinate — never a value.

## `skill` — teach an agent to use this tool

```bash
agent-container skill install                    # into THIS PROJECT (default)
agent-container skill install --agent codex      # claude | codex | opencode | pi
agent-container skill install --user             # into your home config instead
agent-container skill update                     # refuses if you edited it
agent-container skill remove
```

Writes an **[Agent Skills](https://agentskills.io) standard** definition —
`skills/agent-container/SKILL.md` with `name` + `description` frontmatter. All four agents
consume the same standard, so there is **one definition** and a target is only a *discovery
path*.

- **Idempotent** — reinstalling an unmodified, current definition changes nothing.
- **Never clobbers** — a hand-edited file is detected by a checksum in its frontmatter and
  refused; `--force` replaces it explicitly.
- **No residue** — `remove` deletes only what the tool wrote.

The installed skill instructs the agent to pass `--json` on **every** invocation, and every
example in it carries the flag. That is what makes the per-invocation flag workable.

## Not promised

- **Human (non-`--json`) output is not stable** — it is for people and may change freely.
- No network API, daemon, or RPC surface. The contract is a command-line invocation.
- No autonomous action: the tool reports state and suggests a next step; it does not act
  unattended. Destructive commands still require `-y`, and **refuse rather than prompt**
  when not attached to a terminal.
