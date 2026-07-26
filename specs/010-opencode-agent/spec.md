# Feature Specification: opencode as a Supported Agent

**Feature Branch**: `010-opencode-agent`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "Introduce support for running opencode inside the container. Let's keep the list of supported agents consistent."

## Overview

The container ships three coding agents — Claude Code, OpenAI Codex, and pi-coding-agent —
selectable with `--agent`. Feature 009 establishes that **four** agents can drive the CLI
from outside: those three plus **opencode**. That asymmetry is the problem: an operator can
install a skill for opencode but cannot then *run* opencode in the environment that skill
talks about.

This feature closes the gap by making **opencode a first-class agent inside the container**,
so the supported-agent list is **one list, used consistently** in both directions.

The change is deliberately unglamorous — opencode joins the existing per-agent machinery
rather than getting a parallel path. What makes it non-trivial is that it **changes a pinned
on-disk contract**: the per-container volume set grows from **seven to eight**, and that
number is referenced by the design contract, a self-test, the teardown paths, and the shell
completions.

## Clarifications

### Session 2026-07-25

- Q: Should the four agents that can *drive* the CLI and the agents that can *run inside* the
  container be the same list? → A: **Yes** — one consistent list of supported agents; this
  feature adds opencode to the container so the two do not diverge.
### Session 2026-07-26

- Q: opencode's config directory is nested (`~/.config/opencode`) while the other three
  agents use flat `$HOME` directories — where should its persistent storage mount? → A: **At
  opencode's own native location.** Anything an operator reads in opencode's documentation
  then works verbatim inside the container, and no environment override is needed. The cost
  is accepted knowingly: the volume layout has one nested path among three flat ones, which
  **Feature 011 (filesystem layout) may revisit for all four agents together**.

**Verified during clarification** (facts, not preferences — checked against opencode's
documentation rather than assumed):

- opencode **is installable at image build time by the same mechanism as the other three**
  (a global npm package), so it needs no new install machinery and nothing at runtime.
- Its configuration lives in **one directory**, and that directory is **overridable by an
  environment variable** — the same lever Feature 003 already uses for the other agents'
  ephemeral-credential redirect, so the existing credential machinery applies unchanged.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run opencode inside a container (Priority: P1)

An operator selects opencode as the agent for an environment. It launches exactly as the
other three do — interactively in its own session window, or non-interactively as the
container's main process — and its configuration and credentials persist across restarts and
recreation just like the other agents'.

**Why this priority**: This is the whole feature and the MVP. Without it the two supported-
agent lists stay inconsistent, which is the problem being solved.

**Independent Test**: Create an environment selecting opencode, in both interactive and
non-interactive modes; confirm it starts, is reachable the same way the other agents are,
and that its configuration survives a teardown-and-recreate cycle.

**Acceptance Scenarios**:

1. **Given** an operator selects opencode, **When** the environment starts interactively,
   **Then** opencode is running in its own session window, discoverable exactly like the
   other agents.
2. **Given** an operator selects opencode, **When** the environment runs non-interactively,
   **Then** opencode runs as the main process and the environment's exit status reflects the
   agent's outcome, matching the other agents' behavior.
3. **Given** opencode has been configured or authenticated inside a container, **When** the
   container is torn down and recreated, **Then** that configuration persists.
4. **Given** an operator selects an agent, **When** they choose any of the four supported
   names, **Then** the tool accepts it — the accepted set is one list with no special cases.

---

### User Story 2 - Credentials reach opencode by the same rules (Priority: P2)

An operator supplies opencode's credentials the same way they do for the other agents — the
runtime injection channels, not a bespoke path — and a credential intended for opencode never
lands anywhere the other agents' credentials would not.

**Why this priority**: Correctness and least-exposure. It builds on US1 and must not open a
new secret path; but the agent is useful (with interactive login) before this lands.

**Independent Test**: Provide an opencode credential through the supported channel, confirm
it reaches the running agent, and confirm no secret value appears in the project directory,
the tool's output, or its stored state.

**Acceptance Scenarios**:

1. **Given** a credential declared for opencode, **When** the environment starts, **Then**
   the agent can use it, delivered through the same runtime channels as the other agents.
2. **Given** any opencode credential, **When** it is delivered, **Then** no secret value
   appears in the project directory, the command output, or the tool's stored state.
3. **Given** no credential is supplied, **When** opencode starts interactively, **Then** the
   operator can authenticate from inside the session and that credential persists.

---

### User Story 3 - The volume-set change is safe for existing environments (Priority: P2)

An operator upgrading the tool finds that their **existing environments keep working** and
that teardown still removes everything the tool created — even though the per-container
volume set has grown.

**Why this priority**: This is the risk the feature carries. The volume set is a pinned
contract used by teardown; getting it wrong either strands storage or breaks upgrades. It is
independently testable and must not be deferred.

**Independent Test**: Create an environment on the previous volume set, upgrade, and confirm
it still starts, attaches, and tears down completely with no orphaned storage; then confirm a
freshly created environment has the full new set and also tears down completely.

**Acceptance Scenarios**:

1. **Given** an environment created before this change, **When** the operator upgrades and
   uses it, **Then** it continues to work without manual migration.
2. **Given** an environment created before this change, **When** it is fully torn down,
   **Then** the absence of the new volume is tolerated and no error results.
3. **Given** a newly created environment, **When** it is fully torn down, **Then** **every**
   volume the tool created is removed, leaving no orphaned storage.
4. **Given** any place that states how many per-container volumes exist, **When** the change
   lands, **Then** that statement is updated consistently — no stale count remains.

---

### Edge Cases

- **An environment predating the change is torn down** — the missing volume must be tolerated,
  never an error (the same tolerance already applied when the workspace volume became
  conditional).
- **The new agent is selected on a host whose image predates it** — the failure must be clear
  and name the remedy (rebuild), not surface as an obscure "command not found".
- **Non-interactive mode with an agent that cannot authenticate** — must fail with the
  agent's own outcome rather than hanging.
- **The agent's own configuration directory collides with an existing mount** — its
  persistence must not disturb the other agents' state.
- **Shell completions offering agent names** — must offer all four, or the tool and its
  completions disagree.
- **Image size** — adding a fourth agent grows the image; acceptable, but it should be a
  conscious cost rather than an accident.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST accept **opencode** wherever an agent is selected, alongside
  Claude Code, OpenAI Codex, and pi-coding-agent.
- **FR-002**: The supported-agent list MUST be **single-sourced**, so the CLI, the container,
  the completions, and the documentation cannot disagree about which agents exist.
- **FR-003**: opencode MUST be available **inside the container image** — installed at build
  time, never fetched at runtime (the image is immutable at runtime by decision).
- **FR-004**: In interactive mode, opencode MUST launch in its **own session window**,
  discoverable exactly as the other agents are.
- **FR-005**: In non-interactive mode, opencode MUST run as the **main process**, with the
  environment's exit status reflecting the agent's outcome — identical to the other agents.
- **FR-006**: opencode's configuration and credentials MUST **persist across restart and
  recreation**, in the same manner as the other agents', with its persistent storage mounted
  at **opencode's own native configuration location** — so guidance written for opencode
  applies verbatim inside the container and no environment override is required.
- **FR-007**: The per-container storage set MUST be updated to include opencode's, and every
  place that states the number or names of those volumes MUST be updated **consistently**.
- **FR-008**: Full teardown MUST remove **every** volume the tool creates, including the new
  one — no orphaned storage.
- **FR-009**: Teardown of an environment created **before** this change MUST tolerate the
  absence of the new volume and succeed without error or manual migration.
- **FR-010**: Credentials for opencode MUST be delivered through the **existing runtime
  injection channels**; no new secret path is introduced.
- **FR-011**: No opencode credential value may appear in the project directory, the tool's
  output, or its stored state (Constitution III, Least Exposure).
- **FR-012**: Selecting opencode against an image that predates it MUST fail with a **clear,
  actionable message** naming the remedy.
- **FR-013**: Shell completions MUST offer all four agent names.
- **FR-014**: Behavior for the three existing agents MUST be **unchanged** — this feature is
  additive.

### Key Entities *(include if feature involves data)*

- **Supported agent**: a selectable coding agent, identified by name; the set is one list
  consumed by the CLI, the container, the completions, and the docs.
- **Per-agent persistent state**: the storage that keeps an agent's configuration and
  credentials across recreation; each supported agent has one.
- **Per-container volume set**: the canonical, ordered set of storage the tool creates for an
  environment — a pinned contract used by teardown and asserted by the self-test.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can run opencode in a container in **both** interactive and
  non-interactive modes, with the same commands used for the other three agents.
- **SC-002**: opencode's configuration survives a teardown-and-recreate cycle — 100% of runs.
- **SC-003**: The supported-agent list is identical everywhere it appears (CLI, container,
  completions, documentation) — verified with **zero** discrepancies.
- **SC-004**: Full teardown of a newly created environment leaves **zero** orphaned volumes.
- **SC-005**: An environment created before the change tears down successfully after upgrade
  — 100% of runs, with no manual migration.
- **SC-006**: No opencode credential value appears in the project directory, output, or
  stored state — 100% of runs.
- **SC-007**: The three existing agents behave exactly as before — no regression in their
  launch, persistence, or teardown.

## Assumptions

- **Verified, not assumed:** opencode is installable at image build time by the **same
  mechanism as the existing agents**, and its configuration lives in a **single, persistable
  directory** that an environment variable can relocate (see Clarifications).
- **The volume-set growth (seven → eight) is an additive contract change**, handled the same
  way the workspace volume was made conditional: teardown tolerates absence, so no migration
  is required for existing environments.
- **Interactive authentication inside the container remains a supported path** for opencode,
  as it is for the other agents, so the feature is useful before declared credentials land.
- **Image growth from a fourth agent is acceptable**; the container is a development
  environment, not a minimal runtime.
- The image is **rootless and immutable at runtime**, so the agent must be baked at build
  time — no runtime installation.

## Out of Scope

- Changing how any existing agent is installed, launched, or persisted.
- Adding agents beyond the four now supported.
- opencode-specific tuning, model configuration, or provider setup beyond what the other
  agents receive.
- The skill-definition work for opencode — that is Feature 009 (agents *driving* the CLI).

## Dependencies

- **Feature 004 (agent execution)**: the `--agent` selection, the interactive/non-interactive
  modes, and the per-agent launch machinery this extends.
- **Feature 003 (agent credentialing)**: the runtime injection channels opencode's
  credentials must reuse.
- **Feature 009 (agent-operable CLI)**: establishes the four-agent list this feature makes
  consistent on the container side.
- **Constitution II (rootless, build-time dependencies)**: the agent must be baked into the
  image, never installed at runtime.
