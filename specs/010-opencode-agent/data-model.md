# Phase 1 Data Model: opencode as a Supported Agent

**Feature**: 010-opencode-agent | **Date**: 2026-07-26

This feature adds no persistent data structures. It changes two **contracts** — the supported-agent
set and the per-container volume set — both of which are pinned in code, tests, and documentation.

---

## E1. Supported agent

A selectable coding agent, identified by a lowercase name.

| Field | Value |
|---|---|
| `name` | `claude` \| `codex` \| `pi` \| **`opencode`** |
| headless form | `claude -p` \| `codex exec` \| `pi -p` \| **`opencode run`** |
| interactive form | launched in a tmux window named after the agent |
| persistent state | one or more named volumes (see E2) |

**Canonical source**: `AGENTS` in `bin/agent-container`.

**Validation rules**:

- `--agent` accepts exactly the members of `AGENTS`; anything else is rejected host-side before
  any container work (FR-001).
- `entrypoint.sh`'s dispatch `case` and the `Dockerfile`'s install layer MUST cover exactly the
  same set. Enforced by a parsing test, not by construction (FR-002, research R7).
- Selecting a valid agent whose binary is absent from the running image MUST fail with a message
  naming `redeploy` as the remedy — never a bare `command not found` (FR-012).

**State transitions**: none. The set is static per release.

---

## E2. Per-container volume set

The canonical, ordered set of named volumes the tool creates for an environment. Used by
`up`/`redeploy` to declare mounts, and by `down --purge`/`wipe` to tear storage down.

**Before this feature** — seven:

| # | Volume suffix | Mount |
|---|---|---|
| 1 | `-workspace` | `/workspace` (conditional — persistent mode only, Feature 004) |
| 2 | `-claude` | `/home/dev/.claude` |
| 3 | `-codex` | `/home/dev/.codex` |
| 4 | `-pi` | `/home/dev/.pi` |
| 5 | `-shellenv` | `/home/dev/.agent-container` |
| 6 | `-tmux` | `/home/dev/.config/tmux` |
| 7 | `-ssh` | `/home/dev/.ssh` |

**After this feature** — nine. Two are added; the existing seven are unchanged in name, mount, and
order:

| # | Volume suffix | Mount | Holds |
|---|---|---|---|
| 8 | **`-opencode`** | `/home/dev/.config/opencode` | `opencode.jsonc` (created by opencode; the documented `opencode.json` is also read), `tui.json`, `agents/`, `commands/`, `modes/`, `plugins/`, `skills/`, `themes/` |
| 9 | **`-opencode-data`** | `/home/dev/.local/share/opencode` | `auth.json` — written **only** by operator-interactive `opencode auth login` |

**Naming**: `agent-container-<name>-opencode` and `agent-container-<name>-opencode-data`, derived
deterministically from the environment name (Constitution IV). No new state is stored.

**Validation rules**:

- Both mount points MUST exist in the image, owned by `dev`, before the volume is mounted
  (research R3) — otherwise the runtime creates the parent and rootless writes may fail.
- Full teardown MUST remove **all nine** (FR-008).
- Teardown of an environment created on the **seven**-volume set MUST tolerate the absence of the
  two new volumes and succeed (FR-009). No migration.
- Every place stating the count or the names MUST agree: the `per_container_volumes` docstring
  (self-test), the `--volumes` teardown comment in `bin/agent-container`, `CLAUDE.md`, and the
  shell completions (FR-007).

---

## E3. Per-agent persistent state (relationship)

| Agent | Volumes | Why |
|---|---|---|
| claude | 1 (`~/.claude`) | single directory holds config + credentials |
| codex | 1 (`~/.codex`) | same |
| pi | 1 (`~/.pi`) | same |
| **opencode** | **2** | opencode follows XDG and splits config (`~/.config/opencode`) from data (`~/.local/share/opencode`); both must persist to satisfy FR-006 |

This asymmetry is a property of opencode, not of the design. Feature 011 (filesystem layout) is
chartered to revisit the layout for all four agents together.

---

## E4. Credential routing (Feature 003 channels, no new entity)

| Channel | claude | codex | pi | opencode |
|---|---|---|---|---|
| Injected key file (`INJECT_APIKEY_DIR`, ephemeral) | `apiKeyHelper` in fresh `settings.json` | ephemeral `CODEX_HOME` | ephemeral `PI_CODING_AGENT_DIR` | **process environment only** |
| On-volume credential | operator-interactive login only | same | same | same (`auth.json`) |

opencode requires **no ephemeral-`$HOME` redirect**: the redirect exists for codex/pi solely to
keep an injected key out of `auth.json`, and an env-delivered key is never written to opencode's
auth store at all (research R6). Strictly less exposure — FR-010/FR-011 hold with less machinery.
