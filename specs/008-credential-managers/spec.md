# Feature Specification: Credential Managers

**Feature Branch**: `008-credential-managers`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "Credential managers as first-class sources for the agent-as-code credential model (builds on Feature 006), following the git-credential-helper pattern; the repo stores only a locator, never a value; remove the encrypted-in-repo source; establish the recommended credential taxonomy."

## Overview

The agent-as-code model (Feature 006) lets a repository declare the environments it
wants and the **credentials** those environments need — but only by *reference to a
source*, never by value. Today those sources are `env`, `file`, `keychain`, and
`encrypted`. The `encrypted` source lets a **ciphertext secret live in the git remote**
(age/sops on a committed file); even encrypted, distributing secrets through the
repository is the weakest posture and one operators would rather avoid.

This feature makes **credential managers** first-class, following the model git already
uses for credential helpers: the repository holds a **locator** (which vault, which
item), and the actual secret is fetched **at apply time, on the operator's machine**,
from wherever it truly lives — the OS keychain, a password manager (1Password,
Bitwarden, …), or a HW-key-backed store (YubiKey). The secret never enters the
repository. In exchange, the discouraged encrypted-in-repo source is **removed**, and a
clear **recommended taxonomy** replaces the ad-hoc source list.

## Clarifications

### Session 2026-07-23

- Q: How broad should manager support be? → A: A generic resolver source (one operator-
  declared command whose stdout is the secret) **plus** named convenience sources for the
  most common managers (1Password, Bitwarden).
- Q: What happens to the encrypted-in-repo (`encrypted`) source? → A: **Removed entirely**;
  a spec still using it is refused with an actionable migration message (breaking change,
  acceptable pre-1.0).
- Q: Where does the resolver run? → A: **Host-side at apply**, on the operator's machine
  where the manager session / YubiKey / iCloud lives — never inside the container, never
  seen by the agent.
- Q: Is an interactive unlock prompt allowed during apply? → A: No — resolution is
  **non-interactive** (stdin closed, bounded time); the operator unlocks the manager
  beforehand (e.g. `op signin`, `bw unlock`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reference a secret from any credential manager (Priority: P1)

An operator keeps their API keys and tokens in a password manager (or the OS keychain,
or a HW-key-backed store). They want a repository's `.agent-container/` spec to name
*which* secret to use, and have the tool fetch it from the manager at apply — so the
secret is never written into the repository in any form.

**Why this priority**: This is the headline value and the MVP. A single generic
resolver source makes every credential manager with a command-line interface usable
(1Password, Bitwarden, pass, gopass, KeePassXC, Vault, cloud secret stores), matching
the extensible git-credential-helper model. It alone delivers the "secrets never in the
repo" outcome the feature exists for.

**Independent Test**: In a scratch project, declare a credential whose source is a
resolver command that prints a known value; apply; confirm the value reaches the running
environment and appears **nowhere** in the project directory, the command output, or the
tool's stored state. Point the resolver at a real manager CLI and confirm the same.

**Acceptance Scenarios**:

1. **Given** a spec whose credential names a resolver command that yields a secret,
   **When** the operator applies, **Then** the secret is injected into the running
   environment and its value never appears in the project directory, in command
   arguments, in logs, or in the tool's stored state.
2. **Given** the resolver command fails or is unavailable (not installed, manager
   locked, item not found), **When** the operator applies, **Then** the tool fails
   **before making any change** and names the failing credential and source.
3. **Given** a spec committed to a shared repository, **When** another operator reads it,
   **Then** they see only the **locator** (which manager, which item) and never a secret
   value.

---

### User Story 2 - Name the common managers directly (Priority: P2)

Rather than spelling out a resolver command, an operator wants to reference the popular
managers by name with a small set of typed fields (vault, item, field) and let the tool
build the correct invocation.

**Why this priority**: Ergonomics and discoverability over US1. The generic resolver
already works; named sources remove boilerplate and typos for the managers most people
use, while the generic source remains the escape hatch for everything else.

**Independent Test**: Declare a credential using a named manager source (e.g. 1Password
or Bitwarden) with its typed fields; apply against that manager; confirm the secret is
fetched and injected exactly as the equivalent generic resolver would, and that a
malformed named reference is refused naming the missing field.

**Acceptance Scenarios**:

1. **Given** a credential using a named manager source with valid typed fields, **When**
   the operator applies, **Then** the tool fetches the secret from that manager and
   injects it, identically to the equivalent generic resolver.
2. **Given** a named manager source missing a required field, **When** the spec is
   validated, **Then** the tool refuses before any change and names the offending field.
3. **Given** a manager the tool does not name, **When** the operator uses the generic
   resolver source instead, **Then** it works with no code change to the tool.

---

### User Story 3 - Retire encrypted-in-repo and publish the recommended posture (Priority: P3)

An operator (and a repository reviewer) needs an unambiguous, recommended way to decide
where secrets live — and the tool should stop offering the discouraged option of storing
secrets (even encrypted) in the git remote.

**Why this priority**: This is the opinionated cleanup that makes the model coherent. It
depends on US1 existing (so there is a recommended alternative to migrate to), so it is
last. It is a breaking change and must guide existing users to a better source.

**Independent Test**: Apply a spec that still uses the removed encrypted-in-repo source
and confirm it is refused with a message that names the source and points to the
migration. Confirm the documented taxonomy presents the recommended hierarchy and that
the retained sources (`env`, `file`, `keychain`) still work.

**Acceptance Scenarios**:

1. **Given** a spec using the removed encrypted-in-repo source, **When** the operator
   applies, **Then** the tool refuses before any change and names an actionable migration
   (use a manager, the OS keychain, or a local/untracked file).
2. **Given** the recommended taxonomy documentation, **When** an operator or reviewer
   reads it, **Then** the preference hierarchy is explicit (manager / keychain / local /
   HW-backed recommended; plaintext-in-git refused; no encrypted-in-git tier).
3. **Given** the retained sources, **When** an operator uses `keychain`, **Then** it
   reaches the macOS Keychain (including iCloud-synced generic passwords) and the Linux
   Secret Service as before.

---

### Edge Cases

- **Manager CLI not installed / not on PATH** → refuse before any change, naming the
  credential and the resolver.
- **Manager locked or session expired** → the resolver exits non-zero; the tool fails
  before any change and names the source (never a partial apply).
- **Resolver would prompt interactively** → resolution is non-interactive (no TTY / stdin
  closed) and bounded in time, so a resolver that blocks on a prompt fails rather than
  hanging the apply.
- **Resolver writes to its error stream** → the tool never echoes the resolver's error
  output (it may contain secret material); a failure is reported with a generic message.
- **Resolver yields a multi-line value (an SSH private key)** → delivered intact via the
  existing SSH-key targets (Feature 006 T012a); a trailing newline is handled per channel.
- **A later credential's source is unavailable** → all credentials are resolved up front,
  so an earlier environment is never left partially applied.
- **The removed encrypted-in-repo source is still present in a spec after upgrade** → a
  clear refusal + migration, not a silent ignore.
- **The generic resolver argv accidentally embeds a secret** → the spec is a locator, not
  a value; documentation steers operators to pass only locators, and the resolver, not the
  argv, is where the secret originates.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST provide a **generic resolver credential source**: the operator
  declares a resolver command (an argument vector); at apply the tool runs it and captures
  its standard output as the secret value.
- **FR-002**: The resolver MUST run **host-side at apply time**, on the operator's machine
  — never inside the container and never visible to the agent.
- **FR-003**: A resolved secret value MUST NOT appear in the repository, in command
  arguments, in logs, or in the tool's stored state; it lives only in memory and in the
  existing private, per-deployment staged files (Constitution III, Least Exposure).
- **FR-004**: A resolver failure (command missing, non-zero exit, empty when a value is
  required) MUST cause the tool to **fail before making any change** and name the failing
  credential and source (carrying over Feature 006's up-front resolution of all
  credentials).
- **FR-005**: Resolution MUST be **non-interactive** and bounded in time: the resolver
  receives no interactive input and a resolver that does not complete promptly fails
  rather than hanging the apply.
- **FR-006**: The tool MUST never echo a resolver's error-stream output (it may contain
  secret material); failures are reported with a generic, secret-free message.
- **FR-007**: The tool MUST provide **named convenience sources** for at least **1Password**
  and **Bitwarden**, each accepting a small set of typed fields that the tool expands into
  the correct resolver invocation; a malformed named reference (missing required field) is
  refused before any change, naming the field.
- **FR-008**: The generic resolver source MUST remain available as the extensible option
  for any manager the tool does not name — adding support for a new manager MUST NOT
  require changing the tool.
- **FR-009**: The tool MUST **remove the encrypted-in-repo source** (decrypting a committed
  ciphertext file); a spec that still declares it MUST be refused before any change with a
  message naming an actionable migration.
- **FR-010**: The tool MUST retain the `env`, `file` (outside the tracked tree or
  untracked), and `keychain` sources; `keychain` MUST continue to reach the macOS Keychain
  (including iCloud-synced generic passwords) and the Linux Secret Service.
- **FR-011**: A plaintext secret **file tracked in git inside the project** MUST remain
  refused (unchanged from Feature 006).
- **FR-012**: The resolved secret MUST be delivered through the **existing runtime
  injection channels** (the file-first API-key channel, the per-deployment secrets
  env-file, or the SSH-key targets), staged as private (owner-only) files under the
  operator's private state directory, regenerated each apply.
- **FR-013**: The repository spec MUST express a credential only as a **locator** (which
  manager / item / field, or which resolver to run) and never as a value, so a spec is
  safe to commit and review.
- **FR-014**: The tool MUST document the **recommended credential taxonomy** as an explicit
  preference hierarchy (recommended: manager / OS keychain / local / HW-key-backed; refused:
  plaintext secret tracked in git; no encrypted-in-git tier), and note that HW keys such as
  YubiKey are a **backing** for a resolver (a manager unlocked by the key, an SSH key
  resident on the key), not a separate source.
- **FR-015**: The credential schema MUST be **validated before any action** (source enum
  including the new/removed sources, required per-source fields, unknown keys rejected),
  failing with the offending file and field and making no partial change.

### Key Entities *(include if feature involves data)*

- **Credential reference**: a declared entry naming a **source** and its per-source locator
  fields; never a secret value. Sources after this feature: `env`, `file`, `keychain`,
  `command` (generic resolver), and named managers (e.g. `onepassword`, `bitwarden`). The
  `encrypted` source is removed.
- **Resolver**: the host-side command that yields a secret on standard output; the generic
  `command` source is an explicit resolver, a named manager source expands to one.
- **Credential taxonomy**: the recommended preference hierarchy over sources — the
  decision guide a repository reviewer applies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A spec that references a secret through a credential manager applies and the
  secret reaches the running environment, while no plaintext value appears in the project
  directory, the command output, or the tool's stored state — in 100% of runs.
- **SC-002**: When a resolver is unavailable (not installed, manager locked, item missing),
  the tool fails before making any change and names the failing credential and source — in
  100% of runs.
- **SC-003**: A spec using the removed encrypted-in-repo source is refused before any change
  with a message naming the migration — in 100% of runs.
- **SC-004**: A credential manager the tool does not name can be integrated through the
  generic resolver source with **zero changes to the tool**.
- **SC-005**: A named manager reference (1Password / Bitwarden) is expressed in a single
  declaration with typed fields and no resolver-command boilerplate, and resolves
  identically to the equivalent generic resolver.

## Assumptions

- The operator's machine has the referenced manager CLI installed and an **unlocked
  session** at apply time (the operator signs in / unlocks beforehand); resolution is
  non-interactive.
- Builds on **Feature 006** (agent-as-code credential model, up-front in-memory resolution,
  the git-tracked-plaintext refusal) and **Feature 003** (the runtime injection channels).
- The project is pre-1.0, so **removing the `encrypted` source is an acceptable breaking
  change**; existing users migrate to a manager, the OS keychain, or a local/untracked file.
- A generic resolver passing a **locator on its argument vector** is sufficient; a
  git-credential-helper-style stdin protocol is **not** required for one-shot retrieval and
  is out of scope.
- Named manager support ships initially for **1Password and Bitwarden**; other managers are
  reached through the generic resolver until (optionally) named later.
- No new third-party dependency is introduced in the tool: managers are **external CLIs the
  operator already has** (Constitution VI, Least Dependencies).

## Out of Scope

- A git-credential-helper stdin/stdout key-value protocol (only one-shot argv → stdout
  retrieval is in scope).
- Managing, writing, rotating, or unlocking secrets in the manager (the tool only *reads*
  at apply; unlock/rotation stays with the operator's manager tooling).
- Provisioning HW keys or configuring the managers themselves.
- In-container secret resolution (the agent never resolves secrets; the trust boundary is
  host-side-only).

## Dependencies

- **Feature 006** (agent-as-code): the credential model, schema validation, and up-front
  in-memory resolution this feature extends.
- **Feature 003** (agent credentialing): the runtime injection channels (API-key file
  channel, per-deployment secrets env-file, SSH-key targets) the resolved value is
  delivered through.
- **Constitution III (Least Exposure)**: the load-bearing guarantee — no secret value ever
  reaches the repository, argv, logs, or stored state.
