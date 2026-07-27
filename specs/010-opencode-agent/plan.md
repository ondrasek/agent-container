# Implementation Plan: opencode as a Supported Agent

**Branch**: `010-opencode-agent` | **Date**: 2026-07-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-opencode-agent/spec.md`

## Summary

Make **opencode** a first-class agent inside the container so the list of agents that can *drive*
the CLI (Feature 009) and the list that can *run inside* it are one list. opencode is installed as
a global npm package in the existing Dockerfile layer, dispatched by `entrypoint.sh` exactly as the
other three are (`opencode run "<task>"` headless, its own tmux window interactively), and
credentialed through Feature 003's existing runtime channels.

**The plan departs from the spec on one material point.** Phase 0 research checked opencode's own
documentation and found the recorded 2026-07-26 clarification to be **factually wrong**: opencode
does not keep its state in one directory. Config lives in `~/.config/opencode/`, but credentials
written by `opencode auth login` live in `~/.local/share/opencode/auth.json`. Mounting the single
volume the clarification approved would have persisted config while **silently losing credentials
on every recreate** — passing any test that only inspected `opencode.json`. The design therefore
uses **two** native mounts, taking the per-container volume set from **seven to nine**, not to
eight. The four spec amendments that follow from this **landed in `spec.md` on 2026-07-26**
(listed in [research.md](./research.md)).

## Technical Context

**Language/Version**: Python ≥ 3.14 (host CLI, single-file PEP 723 script) · POSIX shell
(`entrypoint.sh`, runs in-container) · Dockerfile (`debian:12-slim`)

**Primary Dependencies**: no new host-side dependency. In-image: `opencode-ai` (npm, global),
joining the three agent CLIs already installed the same way.

**Storage**: per-container named volumes. This feature adds two —
`agent-container-<name>-opencode` → `/home/dev/.config/opencode` and
`agent-container-<name>-opencode-data` → `/home/dev/.local/share/opencode`.

**Testing**: hermetic `pytest` under `bin/tests/` (gate tier) + `pytest -m acceptance`
(real-container tier, CI-only). Two questions in this feature are **only** answerable at the
acceptance tier — see Constraints.

**Target Platform**: rootless Linux container (Podman/Docker), driven from macOS or Linux hosts.

**Project Type**: CLI tool + container image.

**Performance Goals**: none. Image growth from a fourth agent is an accepted, conscious cost
(spec Assumptions).

**Constraints**:

- Rootless, no `sudo`, **no runtime `apt`/install** — opencode must be baked at build time.
- Two facts are **unverifiable from documentation** and must be probed against the real image
  rather than assumed: (a) whether `opencode run` propagates a non-zero exit status, which FR-005
  depends on; (b) that both volume mount points are writable by `dev` under rootless
  (see research R3).
- Deterministic identity (container name, port, existing volume names) must not change.

**Scale/Scope**: one agent added. Touches `bin/agent-container`, `entrypoint.sh`, `Dockerfile`,
`completions/`, `CLAUDE.md`, `docs/`, and nine test modules.

## Constitution Check

| Principle | Gate | Verdict |
|---|---|---|
| **I. Ephemerality** | No workflow may depend on uncommitted container state | **PASS** — additive; opencode's persistence is config/credentials, never work product |
| **II. Least Privilege, Immutable Runtime** | Deps baked at build; nothing installed at runtime | **PASS** — `npm install -g opencode-ai` in the existing build layer (R4). R3 adds the dev-owned mount-point dirs, which exists *because* of this principle |
| **III. Least Exposure** | No secret on argv, in the image, or on a durable volume beyond operator-interactive login | **PASS**, and *improves* on the other agents — an injected key reaches opencode via the process environment only and is never written to the auth store, so opencode needs no ephemeral-`$HOME` redirect at all (R6) |
| **IV. Deterministic Identity** | Names derived, never stored | **PASS** — both new volume names derive from `<name>`; container name and port unchanged |
| **V. Durable Spec, Disposable Code** | Spec is the durable artifact | **PASS** (was ATTENTION) — the spec recorded a false verified fact; the four corrections landed 2026-07-26, checklist re-validated 16/16 |
| **VI. Least Dependencies** | Justify every new dependency | **PASS** — no new host dependency. FR-002 is met with a parsing test rather than build-time codegen precisely to avoid one (R7) |
| **VII. Continuous Deployment** | Gate green; Conventional Commits | **PASS** — `feat` scope, cuts a minor release |

**No unjustified violations.** The one former **ATTENTION** was a spec-correctness action, since
resolved — not a design compromise.

## Project Structure

### Documentation (this feature)

```text
specs/010-opencode-agent/
├── spec.md              # 4 amendments applied 2026-07-26
├── plan.md              # this file
├── research.md          # Phase 0 — includes the CRITICAL R1 correction
├── data-model.md        # Phase 1 — supported-agent + volume-set contracts
├── contracts/
│   └── agent-contract.md
├── quickstart.md        # Phase 1 — runnable validation
└── checklists/requirements.md
```

### Source Code (repository root)

```text
bin/agent-container          # AGENTS (canonical list); opencode_volume_name,
                             #   opencode_data_volume_name; all_volume_mounts;
                             #   per_container_volumes; --agent help; stale "seven" comment
bin/tests/
├── test_execution.py           # --agent selection surface (FR-001/FR-014)
├── test_pure_logic.py          # agent-list cross-file agreement (FR-002)
├── test_compose.py             # nine-volume declaration (FR-007)
├── test_lifecycle.py           # pre-upgrade teardown tolerance (FR-009)
├── test_credentialing.py       # env-only key delivery (FR-010/FR-011)
├── test_completions.sh         # --agent value completion (FR-013)
├── test_entrypoint_execution.sh    # dispatch + stale-image preflight (FR-005/FR-012)
├── test_entrypoint_tmux_layout.sh  # opencode window (FR-004)
└── test_acceptance.py          # real-container: exit status, persistence, zero orphans
entrypoint.sh                # opencode dispatch, binary preflight (FR-012), tmux window
Dockerfile                   # npm layer + dev-owned mount-point dirs (R3/R4)
completions/                 # --agent value completion (FR-013 — net-new, see R8)
docs/execution.md            # four-agent documentation
CLAUDE.md                    # volume-count contract statement
```

**Structure decision**: no new modules. This feature extends existing single-file surfaces; the
`bin/agent-container` edits are sequential (one file), the `entrypoint.sh` / `Dockerfile` /
completions edits are parallelizable against it.

## Design decisions carried into tasks

1. **Two volumes, native mounts** (R2) — the load-bearing correction. Set grows 7 → 9.
2. **Dockerfile creates both mount-point directories owned by `dev`** (R3) — otherwise a rootless
   ownership failure that only appears at runtime.
3. **`AGENTS` is canonical; agreement is enforced by a file-parsing test** (R7) — detection, not
   prevention, and stated as such.
4. **FR-012 gets an explicit binary preflight** — without it, selecting opencode against a stale
   image surfaces as `exec: opencode: not found` (exit 127). The preflight names `redeploy` as the
   remedy and is written once for all four agents.
5. **FR-013 is net-new work** (R8) — completions offer no agent names today.
6. **FR-009 gets a dedicated old-set → new-code teardown test** (R9) even though the existing
   label-based `compose down --volumes` is expected to already satisfy it.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Volume set grows by **two**, not one; opencode is the only agent with two volumes | opencode splits config (`~/.config`) from credentials (`~/.local/share`) per XDG; both must persist (FR-006) | One volume + symlink, or one volume + `OPENCODE_CONFIG`, each put cleverness or an env override into the persistence path — and `OPENCODE_CONFIG` names a file, so `agents/`/`skills/`/`themes/` still would not persist (R2) |
| FR-002 satisfied by a cross-file **parsing test** rather than a single source of truth | The list is encoded in Python, shell, and Dockerfile — three languages | Build-time codegen would add a dependency and a new failure mode to eliminate drift in a list that changes about once a year (Constitution VI, R7) |
