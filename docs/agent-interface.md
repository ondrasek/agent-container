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

## `list --json`: the pinned host key travels with the row

Each container row carries **`known_hosts_entry`** — the `known_hosts`-format line the
tool pinned for that environment, or **`null`** when nothing was captured:

```json
{"containers": [
  {"name": "agent-container-acme", "host": "local", "port": 2206,
   "known_hosts_entry": "[localhost]:2206 ssh-ed25519 AAAAC3Nz..."}
]}
```

`null`, never `""` — a JSON consumer must be able to tell *never captured* from a
captured value.

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
