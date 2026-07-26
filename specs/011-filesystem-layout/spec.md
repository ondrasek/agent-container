# Feature Specification: Filesystem Layout

**Feature Branch**: `011-filesystem-layout`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "In the meantime, we need to reconsider folder structure. Currently, we have .agent-container folder. Where is workspace mounted from? Where are local filesystem folders (if any) mounted from and to? Where is Dockerfile stored with any supporting files?"

## Overview

The tool's on-disk layout grew one feature at a time, and it shows. Two concrete problems:

**1. The name `agent-container` identifies six unrelated things.** An operator asking "where
does my configuration live?" has to know which of these is meant:

| Location | What it holds | Side |
|----------|---------------|------|
| `.agent-container/` | the declarative project spec | operator's repo |
| `/workspace/.agent-container/` | a read-only delivered copy of that spec | container |
| `~/.agent-container/` | the persistent shell-env directory | container |
| `/run/agent-container/` | ephemeral injected secrets | container |
| `~/.config/agent-container/` | host registry + per-environment config | operator's machine |
| `$XDG_STATE_HOME/agent-container/<host>/` | ports, locks, generated compose files | operator's machine |

Only the first two are related. The rest share a name and nothing else.

**2. The project root is littered.** Per-environment conventions are loose dotted files
beside the code — `agent-container.<name>.env`, `agent-container.<name>.<provider>.key`,
`agent-container.<name>.config/`, `agent-container.<name>.services.yaml` — even though the
project already has a `.agent-container/` directory that could hold them. These are exactly
the files the build-context allowlist had to be written to protect.

**3. The image sources sit at the repo root.** `Dockerfile` and `entrypoint.sh` are the
build context's only real contents, yet they share the top level with everything else.

This feature reorganizes the layout so each location has **one obvious meaning and one
obvious home**, without changing what the tool *does*.

> **The hard constraint.** The tool's **deterministic identity** — the container name
> `agent-container-<name>`, the `2200 + name-hash` port, and the per-container volume names
> — is how the tool finds and owns existing deployments (Constitution IV). **None of it may
> change**, or every environment an operator already runs becomes an orphan the tool can no
> longer see. This feature moves *files*, never *identities*.

## Clarifications

### Session 2026-07-26

- Q: What should change? → A: **All three**: consolidate the project-root convention files
  into the project directory; move the image sources out of the repo root; and rename the
  in-container/host locations so `agent-container` stops meaning six different things.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One directory per project (Priority: P1)

An operator opens a repository that uses the tool and finds **one** directory holding
everything the tool cares about — the spec, the per-environment env files, the credential
files, the sidecar overrides — instead of a spec directory plus four kinds of dotted file
scattered beside the source code.

**Why this priority**: The biggest daily ergonomic win and the one the operator asked about
first. It also shrinks the surface that the build-context allowlist and the
git-tracked-secret refusal have to defend, because everything the tool owns is in one place.

**Independent Test**: In a project using the current scattered layout, adopt the new layout
and confirm every environment still deploys identically; then confirm a project using the
*old* layout still works, and that the operator is told how to migrate.

**Acceptance Scenarios**:

1. **Given** a project with per-environment files in the new consolidated location, **When**
   the operator deploys, **Then** the tool finds them and the result is identical to the old
   layout — same identity, same runtime behavior.
2. **Given** a project still using the old scattered layout, **When** the operator deploys,
   **Then** it continues to work and the operator is told, once and clearly, how to migrate.
3. **Given** both layouts are present for the same environment, **When** the tool resolves a
   file, **Then** the precedence is defined, documented, and reported — never a silent pick.
4. **Given** a consolidated project, **When** the operator inspects it, **Then** no
   tool-owned file remains loose in the project root.

---

### User Story 2 - The image sources have a home (Priority: P2)

The `Dockerfile` and its supporting files live in their own directory rather than at the
repository root, so it is obvious what belongs to the image and the build context is narrow
by construction rather than by an allowlist that must be maintained.

**Why this priority**: Real but smaller than US1, and it carries build risk — the build
context path and the allowlist both move together, and a mistake breaks every build.

**Independent Test**: Build the image from the new location on a local host and on a remote
host; confirm it succeeds, that the transferred context contains only the image sources, and
that an operator with an older checkout gets a clear message rather than an obscure failure.

**Acceptance Scenarios**:

1. **Given** the relocated image sources, **When** the image is built (locally or on a remote
   host), **Then** it succeeds and produces an equivalent image.
2. **Given** the relocated sources, **When** a build runs, **Then** the transferred context
   contains **only** the image sources — no project files, no secrets, no history.
3. **Given** a build invoked against a layout that lacks the image sources, **When** it runs,
   **Then** it fails with a clear message naming what was expected and where.

---

### User Story 3 - One name, one meaning (Priority: P3)

An operator (or an agent reading the docs) can tell, from a path alone, whether it is their
project's spec, their machine's configuration, their machine's derived state, or something
inside the container — because the names differ.

**Why this priority**: The clarity payoff is real but it is the most invasive change: it
touches in-container paths and the project marker, so it must land after the two moves that
carry their own migration. It is also the easiest to get wrong in a way that strands data.

**Independent Test**: Confirm each renamed location is distinguishable by name alone;
confirm an environment created before the rename still runs, attaches and tears down; and
confirm the documentation shows one authoritative map with no stale names.

**Acceptance Scenarios**:

1. **Given** the renamed layout, **When** an operator reads any tool-owned path, **Then**
   its role is unambiguous without consulting documentation.
2. **Given** an environment created **before** the rename, **When** the operator uses it,
   **Then** it continues to run, attach and tear down with no manual migration.
3. **Given** the rename, **When** the tool computes any identity (container name, port,
   volume names), **Then** those values are **unchanged**.
4. **Given** the documentation, **When** the layout is described, **Then** exactly one
   authoritative map exists and no superseded name remains anywhere.

---

### Edge Cases

- **A pre-existing environment is used after upgrade** — it must keep working, with no
  manual migration and no orphaned container, volume or state file.
- **Both old and new layouts present for one environment** — precedence must be defined and
  **reported**, never a silent pick.
- **A file exists only in the old location** — found, used, and the migration announced once,
  not on every command.
- **Teardown of a pre-upgrade environment** — must remove everything the tool created,
  including anything recorded under a superseded path.
- **A remote host built from an older layout** — a clear, actionable failure, never an
  obscure "file not found" from the build.
- **A project vendored/copied to a new path** — the layout is location-independent; nothing
  may depend on an absolute path.
- **Migration is interrupted** (if any migration writes) — the project must be left in a
  working state, never half-moved.
- **The declarative spec's in-container delivery** — its read-only integrity guarantee must
  survive the rename unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All per-environment files a project owns (spec, environment variables,
  credential files, sidecar overrides) MUST live under a **single project directory**.
- **FR-002**: No tool-owned file may remain loose in the project root once a project adopts
  the new layout.
- **FR-003**: A project using the **previous** layout MUST continue to work without manual
  migration.
- **FR-004**: When both layouts could supply the same file, precedence MUST be **defined,
  documented, and reported** — never a silent choice.
- **FR-005**: The tool MUST tell the operator how to migrate, **once and actionably**, rather
  than on every invocation.
- **FR-006**: The image sources (`Dockerfile` and its supporting files) MUST live in their
  own directory, not the repository root.
- **FR-007**: The build context MUST contain **only** the image sources — narrow by
  construction, not by an allowlist that must be maintained in step with the Dockerfile.
- **FR-008**: Building against a layout that lacks the image sources MUST fail with a clear
  message naming what was expected and where.
- **FR-009**: Each distinct location (project spec, host configuration, derived host state,
  in-container spec, in-container persistent state, in-container ephemeral secrets) MUST be
  **distinguishable by name alone**.
- **FR-010**: The tool's **deterministic identity** — container name, port, and volume names
  — MUST be **unchanged** by this feature (Constitution IV).
- **FR-011**: Environments created **before** this change MUST continue to run, attach and
  tear down, with **no orphaned** container, volume or state file.
- **FR-012**: The declarative spec's **read-only in-container delivery** guarantee MUST be
  preserved unchanged through any rename.
- **FR-013**: No credential value may be exposed by the reorganization; files that were
  private MUST remain private, and a git-tracked plaintext secret MUST remain refused.
- **FR-014**: Exactly **one authoritative map** of the layout MUST exist in the
  documentation, with no superseded name left anywhere.
- **FR-015**: The layout MUST be **location-independent** — nothing may depend on the
  project living at a particular absolute path.

### Key Entities *(include if feature involves data)*

- **Project directory**: the single directory in an operator's repository holding everything
  the tool owns for that project — spec and per-environment files.
- **Host configuration**: the operator machine's own settings (the host registry), distinct
  from any project.
- **Derived host state**: values the tool computes and caches per host (ports, locks,
  generated compose files) — reproducible, never authored by hand.
- **Image sources**: the `Dockerfile` and the files it consumes; together they are the build
  context.
- **In-container locations**: the delivered spec (read-only), persistent agent state, and
  ephemeral injected secrets — three different lifetimes that must not share a name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A project using the new layout has **zero** tool-owned files loose in its root.
- **SC-002**: An environment created before this change continues to run, attach and tear
  down after upgrade — 100% of runs, with **zero** orphaned containers, volumes or state
  files.
- **SC-003**: Container name, port and volume names are **byte-identical** before and after
  this change — verified for a corpus of environment names.
- **SC-004**: The image builds successfully from the new location on both a local and a
  remote host, and the transferred context contains **only** the image sources.
- **SC-005**: Every tool-owned location is identifiable by name alone — verified by review
  with **zero** ambiguous names remaining.
- **SC-006**: The documentation contains exactly **one** authoritative layout map, and a
  search for superseded names returns **zero** hits outside migration notes.
- **SC-007**: No credential value is exposed by the reorganization, and a git-tracked
  plaintext secret remains refused — 100% of runs.

## Assumptions

- **Identity is untouchable.** The deterministic identity is the tool's ownership mechanism;
  this feature moves files only. Any change that would alter an identity is out of scope by
  construction.
- **Backward compatibility is required, not optional.** The previous layout keeps working;
  this is a reorganization with a migration path, not a hard cut like the `encrypted` source
  removal — because unlike a credential source, an operator cannot see that their layout is
  "wrong" until something breaks.
- **Migration is operator-driven.** The tool detects and guides; it does not silently move
  an operator's files.
- **The three changes can land independently** and are ordered by risk: consolidation first
  (highest value, contained), image sources next (build risk), renames last (most invasive).
- The container image remains **rootless and immutable at runtime**; nothing here changes
  what is baked at build time.

## Out of Scope

- Changing what the tool *does* — no behavioral change to deploy, attach, credentials or the
  declarative model beyond where their files live.
- Changing the deterministic identity, the port allocation, or the volume naming.
- Changing what `/workspace` is mounted from (the `--workspace` modes are Feature 004).
- Reorganizing the tool's own source repository beyond the image sources.

## Dependencies

- **Feature 003 (credentialing)** and **Feature 006 (agent-as-code)**: the conventions whose
  files are being consolidated, and the read-only spec delivery that must survive a rename.
- **Feature 004 (execution)**: the `--workspace` modes and `--mount` binds that define what
  is mounted where; unchanged here but adjacent.
- **Constitution IV (Deterministic Identity)**: the guarantee that constrains this entire
  feature — files may move, identities may not.
- **Constitution III (Least Exposure)**: private files must stay private through the move.
