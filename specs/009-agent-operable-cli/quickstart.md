# Quickstart: Agent-Operable CLI

Validation journeys proving an agent can drive the tool. Engine-level assertions are hermetic
(the Feature 007 snapshot is pure, so `context` needs no daemon); the end-to-end journeys use
a real local runtime.

## Prerequisites

- A working local container runtime for the lifecycle journey (A).
- Scenarios B–E need neither a runtime nor a TTY.
- A scratch agent-configuration tree for F (never the operator's real one).

## Scenario A — An agent drives a full lifecycle (US1 / SC-001, SC-003)

```bash
agent-container --help --json                 # discover capabilities
agent-container context --json                # load state, decide
agent-container up dev --json                 # act
agent-container list --json                   # verify
agent-container down dev --purge -y --json    # tear down
```

**Expected**: every call emits **one** JSON object on stdout with `schema` and `ok`; nothing
is written to stdout but the envelope; no call blocks waiting for input. The destructive step
without `-y` in a non-interactive context **refuses and names the flag** rather than
prompting.

## Scenario B — Failures are actionable (US1 / SC-002)

Force each defined failure class (no host registered, port held, credential missing, host
unreachable, invalid spec).

**Expected**: each yields `ok: false` with a **stable `code`**, the affected `entity`, the
human `message`, and a `remedy` — and a non-zero exit. An agent branches on `code` alone;
the wording of `message` is never required for the decision.

## Scenario C — The eval contract is intact (US1 / research R3)

```bash
agent-container host env nosuchhost           # expect: EMPTY stdout, non-zero
agent-container attach nosuch --print         # expect: EMPTY stdout, non-zero
```

**Expected**: unchanged Feature 005 behavior — **empty stdout** on error so `eval $(…)` runs
nothing — and these commands do **not** accept `--json`. This is the one place where the two
output disciplines meet, so it is asserted rather than assumed.

## Scenario D — `context` in four worlds (US2 / SC-004, SC-005)

Run `agent-container context --json` with: (1) nothing configured; (2) a healthy running
environment; (3) an unreachable host; (4) inside a declarative `.agent-container/` project.

**Expected**: valid structured output in **all four**; the empty world yields empty
collections rather than an error; the unreachable host appears as a **described state**, not
a failed call; the project case reports the governing spec and the applicable env-file
**path**. In every case, credentials appear as **locators only** — grep the payload for known
secret values and find **nothing**.

## Scenario E — No secret ever reaches the payload (SC-005)

With a credential configured by each supported source, capture every `--json` payload and the
`context` payload.

**Expected**: the resolved secret value appears in **none** of them; only the reference
(variable name, file path, manager item) does.

## Scenario F — Skill lifecycle (US3 / SC-006, SC-007)

```bash
agent-container skill install --json          # into the PROJECT by default
agent-container skill install --json          # again -> idempotent no-op
# hand-edit the installed SKILL.md, then:
agent-container skill update --json           # -> REFUSES, reports the difference
agent-container skill remove --json           # -> no residue
```

**Expected**: the definition lands where the target agent discovers it and conforms to the
Agent Skills standard (`SKILL.md`, `name` + `description` frontmatter); the second install
changes nothing and says so; the hand-edited file is **never silently overwritten**; removal
leaves nothing behind. Repeat for each of the four agents — the *content* is identical, only
the path differs.

## Scenario G — The skill enforces `--json` (US3 / FR-012c)

Read the installed `SKILL.md`.

**Expected**: it instructs the agent to pass `--json` on every invocation, and **every command
example inside it carries the flag** — no example invokes the tool without it.

## Success signal

All scenarios pass: an agent completes a lifecycle on machine-readable output alone; failures
carry stable codes and remedies; the eval contract is untouched; `context` is valid in every
world and leaks no secret; and the skill installs idempotently, refuses to clobber, removes
cleanly, and carries the `--json` convention — matching SC-001…SC-008.
