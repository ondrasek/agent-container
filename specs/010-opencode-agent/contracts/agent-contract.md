# Contract: Supported Agent Surface

**Feature**: 010-opencode-agent | **Date**: 2026-07-26

The externally-observable contracts this feature changes. Each is testable without reading the
implementation.

---

## C1. CLI — agent selection

```text
agent-container up   <name> --agent claude|codex|pi|opencode   [--mode interactive|headless]
agent-container redeploy <name> --agent claude|codex|pi|opencode
```

| Input | Expected |
|---|---|
| `--agent opencode` | accepted (FR-001) |
| `--agent <anything else>` | rejected host-side, before any container work, naming the four valid values |
| `--agent` omitted | `claude` (unchanged default, FR-014) |
| `--json` on any of the above | envelope shape unchanged from Feature 009 |

The `--agent` help text and the machine-readable command tree (`commands`) MUST both list all
four names.

---

## C2. Shell completions

Completing a value for `--agent` MUST offer exactly `claude codex pi opencode` (FR-013).

**Note**: no agent-name completion exists today, for any agent — this is net-new, not an edit
(research R8).

---

## C3. In-container dispatch

Interactive (`AGENT_CONTAINER_MODE=interactive`):

| Agent | tmux window |
|---|---|
| `opencode` | a window named `opencode`, discoverable by `tmux has-session` / `attach` exactly as the other three |

Headless (`AGENT_CONTAINER_MODE=headless`), agent as PID 1:

| Agent | Command |
|---|---|
| `claude` | `claude -p "<task>"` |
| `codex` | `codex exec "<task>"` |
| `pi` | `pi -p "<task>"` |
| **`opencode`** | **`opencode run "<task>"`** |

The container's exit status is the agent's exit status (FR-005).

**Contingency**: this holds only if `opencode run` propagates a non-zero status on failure —
undocumented, and therefore **probed at the acceptance tier** (research R5), not assumed. If the
probe shows it always exits 0, FR-005 is unsatisfiable for opencode and the spec must record that
rather than a test asserting it.

---

## C4. Stale-image failure

Selecting a valid agent whose binary is missing from the running image MUST fail with a message
that names the remedy:

```text
agent 'opencode' is not installed in this image; rebuild with:
  agent-container redeploy <name>
```

MUST NOT surface as `exec: opencode: not found` / exit 127 (FR-012). The preflight is written once
and applies to all four agents.

---

## C5. Volume set

```text
per_container_volumes("acme") == [
  "agent-container-acme-workspace",
  "agent-container-acme-claude",
  "agent-container-acme-codex",
  "agent-container-acme-pi",
  "agent-container-acme-shellenv",
  "agent-container-acme-tmux",
  "agent-container-acme-ssh",
  "agent-container-acme-opencode",
  "agent-container-acme-opencode-data",
]
```

| Behavior | Expected |
|---|---|
| `up --workspace persistent` | all nine declared |
| `up --workspace bind\|ephemeral` | the eight non-workspace volumes declared (workspace stays conditional, Feature 004) |
| `down --purge` / `wipe` | all nine removed; **zero** orphans (FR-008) |
| teardown of a **seven**-volume environment | succeeds; the two absent volumes are tolerated, no error, no migration (FR-009) |

Existing volume names, mounts, and relative order are **unchanged** (FR-014).

---

## C6. Persistence

| Given | When | Then |
|---|---|---|
| `opencode auth login` run inside the container | container torn down and recreated | the credential is still present (`~/.local/share/opencode/auth.json`) |
| `~/.config/opencode/opencode.json` edited inside the container | container torn down and recreated | the edit is still present |

A test that checks only `opencode.json` **does not** satisfy this contract — that is precisely the
failure the single-volume design would have hidden (research R1).

---

## C7. Credential exposure

| Given | Then |
|---|---|
| an injected opencode API key | reaches the agent via the process environment; appears **nowhere** in the project directory, command output, or tool state (FR-011) |
| any teardown | no key on any volume; the on-volume `auth.json` originates **only** from operator-interactive login |

---

## C8. Documented agent-list agreement

The set in `AGENTS` (`bin/agent-container`), the `case` dispatch in `entrypoint.sh`, and the
Dockerfile's install layer MUST be identical — asserted by a test that parses all three files
(FR-002). Drift is a red gate, not a runtime surprise.
