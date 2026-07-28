# Feature Specification: Filesystem Layout

**Feature Branch**: `011-filesystem-layout`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "In the meantime, we need to reconsider folder structure. Currently, we have .agent-container folder. Where is workspace mounted from? Where are local filesystem folders (if any) mounted from and to? Where is Dockerfile stored with any supporting files?"

## Overview

The tool's on-disk layout grew one feature at a time, and it shows. Two concrete problems:

**1. The name `agent-container` identifies six unrelated things.** An operator asking "where
does my configuration live?" has to know which of these is meant:

| Location | Name | What it holds | Side |
|----------|------|---------------|------|
| `.agent-container/` | **project config** | the spec + every per-environment file | project root |
| `/workspace/.agent-container/` | delivered spec | a read-only copy of the marker | container |
| `~/.agent-container/` | shell env | persistent shell environment | container |
| `/run/agent-container/` | injected secrets | ephemeral, vanish with the container | container |
| `~/.config/agent-container/` | **user configuration** | host registry + user-level defaults | operator's machine |
| `$XDG_STATE_HOME/agent-container/<host>/` | derived host state | ports, locks, generated compose files | operator's machine |

Only the first two are related. The rest share a name and nothing else. The **Name** column is
the vocabulary this feature settles on (FR-009); the directory holding the marker is the
**project root**, never "the project directory".

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
  into the project config directory; move the image sources out of the repo root; and rename the
  in-container/host locations so `agent-container` stops meaning six different things.

### Session 2026-07-27

- Q: What is the project config directory called? → A: **Keep `.agent-container/`** and move
  the loose dotted files into it. It is already what discovery keys on and the most-referenced
  name; FR-009's ambiguity is resolved by renaming the *other* locations, not this one.
- Q: Where do the image sources move to? → A: **`image/`** — it names the artifact, not a
  runtime. `docker/` would encode exactly the Docker coupling ADR 0001 rejects, and the
  directory becoming the build context makes FR-007 true by construction.
- Q: How far do the in-container renames go? → A: **Only the persistent shell-env directory**
  (`~/.agent-container` → `~/.agent-env`). `/run/agent-container` is already unambiguous by
  its `/run` prefix, and `/workspace/.agent-container` *should* echo the project name because
  it is literally that spec delivered read-only.
- Q: For how long must the previous layout keep working? → A: **It must not.** Backward
  compatibility is **not wanted**: the old implementation is removed immediately, in the same
  change. This is a **hard cut**, not a deprecation — see the Migration posture below.

### Session 2026-07-28

- Q: Should the tool keep reading the bare `./.env` in the project root? → A: **No.** It is not
  a conventional thing for this tool to claim — a `.env` in a project root belongs to whoever
  put it there. An operator who wants an agent-container env file puts it in an
  agent-container location, at project or user level.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One tool directory per project root (Priority: P1)

An operator opens a repository that uses the tool and finds **one** directory holding
everything the tool cares about — the spec, the per-environment env files, the credential
files, the sidecar overrides — instead of a spec directory plus four kinds of dotted file
scattered beside the source code.

**Why this priority**: The biggest daily ergonomic win and the one the operator asked about
first. It also shrinks the surface that the build-context allowlist and the
git-tracked-secret refusal have to defend, because everything the tool owns is in one place.

**Independent Test**: In a project using the current scattered layout, adopt the new layout
and confirm every environment still deploys identically; then confirm a project left in the
*old* layout is refused with a message naming every file that must move.

**Acceptance Scenarios**:

1. **Given** a project with per-environment files in the new consolidated location, **When**
   the operator deploys, **Then** the tool finds them and the result is identical to the old
   layout — same identity, same runtime behavior.
2. **Given** a project still using the old scattered layout, **When** the operator deploys,
   **Then** the tool **refuses** with a message naming each superseded file and where it now
   belongs — it does not deploy a half-configured environment.
3. **Given** a credential file left in a superseded location, **When** the operator deploys,
   **Then** the tool refuses rather than starting an agent without that credential.
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
touches in-container paths and the `.agent-container` name itself, so it must land after the two moves that
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
- **Both old and new layouts present for one environment** — the superseded file is reported
  and the command refuses; there is no precedence rule to get wrong.
- **A file exists only in the old location** — refused with an actionable message. It is
  **never** silently ignored, because the set includes credential files and an ignored key
  means an agent running without the credential the operator thinks it has.
- **Teardown of a pre-upgrade environment** — must remove everything the tool created,
  including anything recorded under a superseded path.
- **A remote host built from an older layout** — a clear, actionable failure, never an
  obscure "file not found" from the build.
- **A project vendored/copied to a new path** — the layout is location-independent; nothing
  may depend on an absolute path.
- **Migration is operator-performed** — the tool never writes to an operator's project to
  migrate it, so there is no half-moved state to recover from. It detects, refuses, and
  explains.
- **The declarative spec's in-container delivery** — its read-only integrity guarantee must
  survive the rename unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All per-environment files a project owns (spec, environment variables,
  credential files, sidecar overrides) MUST live under the **project config directory
  `.agent-container/`** — which already holds the declarative spec — and it MUST be the only
  tool-owned entry in the **project root**.
- **FR-001b**: The tool MUST **stop reading the bare `./.env`** in the project root. Env-file
  resolution MUST be **symmetric across the two levels** — a per-environment file and a shared
  default at each: `.agent-container/<name>.env` → `.agent-container/.env` →
  `~/.config/agent-container/<name>.env` → `~/.config/agent-container/.env`.
- **FR-001c**: Removing `./.env` from the chain MUST NOT strand an operator silently. The env
  file carries `GH_TOKEN`, git identity and provider keys, so when a `./.env` is present **and
  no agent-container env file resolves at all**, the tool MUST **refuse** and name where the
  file now belongs. When an agent-container env file *does* resolve, a stray `./.env` MUST be
  ignored **silently** — it may belong to Docker Compose or another tool sharing the directory,
  and refusing then would make the tool hostile to its neighbours.
- **FR-001a**: After consolidation the **same filename MUST identify the same thing at both
  levels** — `.agent-container/<name>.env` at project level and
  `~/.config/agent-container/<name>.env` at user level, differing only by directory. Today
  the two levels use *different* names (`agent-container.<name>.env` vs `<name>.env`), which
  hides the fact that they are one layered configuration. Dropping the now-redundant
  `agent-container.` prefix is what makes the layering legible.
- **FR-002**: No tool-owned file may remain loose in the project root once a project adopts
  the new layout.
- **FR-003**: The previous layout MUST **not** be supported. There is **no dual lookup and no
  precedence rule** — the old resolution code is removed in the same change, not deprecated.
- **FR-004**: A tool-owned file found **only** in a superseded location MUST cause a **clear,
  actionable failure** naming both the path found and the path expected. It MUST NOT be
  silently ignored. This is the load-bearing requirement of the hard cut: the superseded
  conventions include **credential files** (`agent-container.<name>.<provider>.key`) and
  environment files, so silently ignoring one would start an agent **unauthenticated** while
  the operator believes a key was injected (Constitution III).
- **FR-005**: The failure MUST be **actionable** — it names the exact move required (`old
  path` → `new path`), so the operator can comply without consulting documentation.
- **FR-006**: The image sources (`Dockerfile`, `entrypoint.sh` and anything the build
  consumes) MUST live in **`image/`**, not the repository root.
- **FR-007**: The build context MUST contain **only** the image sources — narrow by
  construction, not by an allowlist that must be maintained in step with the Dockerfile.
- **FR-008**: Building against a layout that lacks the image sources MUST fail with a clear
  message naming what was expected and where.
- **FR-009**: Each distinct location MUST be **distinguishable by name alone**, and the
  documentation MUST use one term per location: **project root** (the operator's directory),
  **project config** (`.agent-container/` within it), **user configuration** (per operator
  machine), **derived host state**, and the three in-container locations. "Project directory"
  is ambiguous between the first two and MUST NOT be used. Concretely,
  the in-container **persistent shell-env directory is renamed `~/.agent-container` →
  `~/.agent-env`**. Two locations deliberately keep the `agent-container` name because it is
  correct for them: `/workspace/.agent-container` (the project's own spec, delivered
  read-only) and `/run/agent-container` (already unambiguous — `/run` denotes ephemeral).
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

- **Project root**: the directory an operator's project lives in — the nearest ancestor of the
  working directory that contains `.agent-container/`. It holds the operator's own code; the
  tool owns nothing in it except the marker. Named to match the shipped implementation, where
  discovery walks up from `cwd` and returns this directory as `root`.
- **Project config** (`.agent-container/`): the directory *inside* the project root holding
  everything agent-container owns for that project — the declarative spec, per-environment
  env files, credential files, sidecar overrides and agent config. It follows the ordinary
  dot-directory convention: `.git/` holds git's data, `.github/` GitHub's, `.devcontainer/`
  devcontainer's, `.agent-container/` this tool's. In prose it is simply **"the
  `.agent-container` directory"**, the way one says "the `.github` directory".

  It pairs with **user configuration** by scope, which is the distinction that matters:
  `.agent-container/` is **per project** and travels with the repository;
  `~/.config/agent-container/` is **per operator machine** and does not. Same schema, two
  levels; project wins.

  (`PROJECT_MARKER` remains the right name for the *code constant* — the directory's
  existence is what discovery keys on — but that is its role in one algorithm, not what the
  directory is.)
- **User configuration** (`~/.config/agent-container/`): the operator's machine-wide settings.
  Two kinds live here, and the earlier name "host configuration" described only the first:
  the **host registry** (`hosts.json` — genuinely about hosts, and has no project-level
  counterpart by design), and **user-level defaults for any environment**
  (`<name>.env`, `<name>.<provider>.key`, `<name>.config/`, `<name>.services.yaml`).

  The second kind is the same schema as project config, one scope up — the tool resolves
  **project first, user as fallback**, the layering Claude Code and similar tools use. So
  project config and user configuration are **two levels of one configuration**, not two
  different configurations.
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
  files. (Identity is untouched, so this holds despite the hard cut: only *file locations*
  change, never the volume names the tool owns.)
- **SC-002a**: A project left in the superseded layout is **refused**, naming every file that
  must move — 100% of runs, with **zero** cases of a superseded credential file being
  silently ignored.
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
- **This is a hard cut, like the `encrypted` source removal.** Backward compatibility is
  explicitly **not wanted** (Session 2026-07-27): the old resolution code is deleted in the
  same change, so no dual-lookup path, precedence rule or deprecation window is carried. The
  risk that an operator "cannot see their layout is wrong until something breaks" is answered
  by **refusing loudly** (FR-004) rather than by supporting both.
- **Migration is operator-performed.** The tool detects and refuses with an actionable
  message; it never writes to an operator's project to migrate it.
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
