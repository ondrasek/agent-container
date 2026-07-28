# Phase 1 Data Model: Filesystem Layout

**Feature**: 011-filesystem-layout | **Date**: 2026-07-27

No persistent data structures change. This feature changes **where files live** and **what each
location is called**. Identity — the thing the tool uses to find and own deployments — is
explicitly out of bounds.

---

## E1. The five locations

| Entity | Path | Scope | Authored by |
|---|---|---|---|
| **Project root** | the nearest ancestor of `cwd` containing `.agent-container/` | one project | the operator |
| **Project config** | `<root>/.agent-container/` | one project, travels with the repo | the operator |
| **User configuration** | `~/.config/agent-container/` | one operator machine | the operator |
| **Derived host state** | `$XDG_STATE_HOME/agent-container/<host>/` | one operator machine | **the tool** — computed, never hand-authored |
| **Image sources** | `<checkout>/image/` | the tool's own repo | the tool's maintainers |

**Validation rules**:

- The project root is discovered by walking **up** from `cwd`; the tool must behave identically
  from any subdirectory (FR-015, location-independence).
- Project config is the **only** tool-owned entry in the project root (FR-002, SC-001).
- Derived host state is not configuration and must never be presented as such: it is
  reproducible and safe to delete.

---

## E2. Configuration is two levels of one thing

Project config and user configuration share a schema. The tool resolves **project first, user as
fallback** — the layering Claude Code and similar tools use.

| Per-environment file | Project level (wins) | User level (fallback) |
|---|---|---|
| env | `.agent-container/<name>.env` | `~/.config/agent-container/<name>.env` |
| credential | `.agent-container/<name>.<provider>.key` | `~/.config/agent-container/<name>.<provider>.key` |
| agent config | `.agent-container/<name>.config/` | `~/.config/agent-container/<name>.config/` |
| sidecars | `.agent-container/<name>.services.yaml` | `~/.config/agent-container/<name>.services.yaml` |

**The filenames become identical at both levels** (FR-001a) — today they differ
(`agent-container.<name>.env` vs `<name>.env`), which is a large part of why the layering is not
obvious. Consolidation makes the prefix redundant, and dropping it is what makes the two levels
legible as one configuration at two scopes.

**Asymmetry, by design**: the **host registry** (`hosts.json`) exists only at user level. Hosts
are a property of the operator's machine, not of a project. It has no project-level counterpart
and this feature does not add one.

**The bare `./.env` is no longer read** (research R2). A `.env` in a project root belongs to
whoever put it there; an agent-container env file goes in an agent-container location. Both
levels therefore have the same two slots — `<name>.env` and a shared `.env` default:

| Level | Per-environment | Shared default |
|---|---|---|
| **Project** | `.agent-container/<name>.env` | `.agent-container/.env` |
| **User** | `~/.config/agent-container/<name>.env` | `~/.config/agent-container/.env` |

**Explicit files outrank the whole chain.** `-e/--env-file` is repeatable and **stacks in order
of occurrence** (later wins), replacing discovery entirely. That is what makes dropping the
implicit `./.env` reasonable — an operator with an env file anywhere, `~/.env` included, names
it: `agent-container up dev -e ~/.env`.

---

## E3. The move table

| # | What | From | To | Risk |
|---|---|---|---|---|
| 1 | env file | `./agent-container.<name>.env`, `./.env` | `.agent-container/<name>.env` (+ `.agent-container/.env` default) | **conditional refusal** — a dropped `.env` strands `GH_TOKEN` and keys |
| 2 | credential | `./agent-container.<name>.<provider>.key` | `.agent-container/<name>.<provider>.key` | **refusal must fire** — silently ignoring starts an unauthenticated agent |
| 3 | agent config | `./agent-container.<name>.config/` | `.agent-container/<name>.config/` | low |
| 4 | sidecars | `./agent-container.<name>.services.yaml` | `.agent-container/<name>.services.yaml` | low |
| 5 | image sources | `./Dockerfile`, `./entrypoint.sh`, `./.dockerignore` | `image/` | **breaks the checkout marker** (R1) |
| 6 | shell env | mount point `/home/dev/.agent-container` | `/home/dev/.agent-env` | mount point must be **pre-created dev-owned** |

Rows 1–4 are the operator's files. Rows 5–6 are the tool's own.

---

## E4. Identity — the invariant this feature must not touch

| Value | Derivation | Changes? |
|---|---|---|
| Container name | `agent-container-<name>` | **No** |
| Port | `2200 + (ASCII-sum of name mod 100)` | **No** |
| Volume names (all nine) | `agent-container-<name>-<suffix>` | **No** |
| Per-host state paths | `$XDG_STATE_HOME/agent-container/<host>/<name>.*` | **No** |

**The shell-env case is the one that looks like a change and is not.** Its volume is
`agent-container-<name>-shellenv` before and after; only the path it mounts at moves. An existing
volume therefore reappears at the new path — contents are relocated, never stranded.

**Verification** (SC-003): already mechanised. The `--self-test` doctests pin
`per_container_volumes`, `all_volume_mounts` and the port corpus. Only the shell-env **mount
string** inside `all_volume_mounts` is expected to differ; every **name** must be unchanged.

---

## E5. Superseded locations (the hard cut)

| Superseded | Status |
|---|---|
| `./agent-container.<name>.env` | **refused**, naming the destination |
| `./agent-container.<name>.<provider>.key` | **refused** — the load-bearing case |
| `./agent-container.<name>.config/` | **refused** |
| `./agent-container.<name>.services.yaml` | **refused** |
| `./Dockerfile`, `./entrypoint.sh` (as build inputs) | build fails, naming `image/` |
| `./.env` | **no longer read**. Refused **only** when no agent-container env file resolves at all (R2a) — otherwise ignored silently, since a stray `.env` may be Compose's |

**State transition**: none. There is no migration state to model, because the tool never writes
to an operator's project to migrate it — it detects, refuses and explains (FR-005). A refused
project is simply a project the operator has not moved yet.
