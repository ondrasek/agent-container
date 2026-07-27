# Feature Specification: Agent-Operable CLI

**Feature Branch**: `009-agent-operable-cli`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "Support for agent-container to be run by AI Agents, such as PI or Claude Code. Agent-friendly error and help messages, context sub-command/argument to print/add agent-friendly context output to stdout (similar to debug/verbose logging) and support for defining skills, that invoke agent-container: a skill command that creates, removes or updates skill definition in local agent configuration (similar to what the github specify cli does for speckit)."

## Overview

Today `agent-container` is designed for a **human at a terminal**: prose errors, a guided
wizard, confirmation prompts, and machine-readable output on only a handful of commands.
Increasingly the *caller* is an **AI coding agent** (Claude Code, PI, Codex) that must
discover what the tool can do, run it, and recover from failure **without a human reading
the output**.

> **Direction matters.** Feature 004 put agents **inside** the container. This feature is
> the inverse: an agent **outside**, on the operator's machine, **driving the CLI**. The two
> are independent — an agent driving the tool need not be the agent running inside it.

Three gaps close here:

1. **Agent-friendly errors and help** — every failure carries a **stable identifier** and a
   **machine-readable remediation**, so an agent can branch on the failure instead of
   pattern-matching English prose that changes between releases.
2. **A `context` surface** — one command that emits the tool's current understanding of the
   world (hosts, environments, conventions, what to do next) as structured output an agent
   can load as context, rather than reverse-engineering it from a dozen commands.
3. **A `skill` command** — installs, updates, and removes a skill/command definition in the
   **local agent configuration**, so an agent gains a first-class, documented way to invoke
   `agent-container` (mirroring how the `specify` CLI installs speckit commands).

The load-bearing constraint throughout: an agent is a **non-interactive caller that must
never be handed a secret, and must never be left waiting on a prompt**.

## Clarifications

### Session 2026-07-25

- Q: Which agents must be supported? → A: **Four** — Claude Code, pi-coding-agent, OpenAI
  Codex, and **opencode** (replacing the earlier "Claude Code and PI initially" assumption).
- Q: How is the machine-readable contract kept from silently breaking agents on upgrade? →
  A: **Version the output** — every machine-readable payload carries a schema version an
  agent can check, so the format can evolve and a breaking change is visible rather than
  silent.
- Q: The four agents store instructions differently — how does the skill command handle
  that? → A: **They do not differ: skills are a published open standard.** The **Agent
  Skills** format (originally by Anthropic, released as an open standard, adopted by 40+
  platforms) defines a skill as a **folder containing `SKILL.md`** — YAML frontmatter with
  required `name` and `description`, plus optional `scripts/`, `references/`, `assets/`.
  **All four targets implement it**: Claude Code, OpenAI Codex, OpenCode, and pi. So the tool
  authors **one standard-conformant skill**, and the only per-agent variable is the
  **discovery path** each agent scans — not the format.
- Q: How does an agent switch the CLI into machine-readable mode? → A: **A per-command
  `--json` flag**, extending the convention the three existing commands already use. No
  global switch and no environment variable; an agent passes the flag on every call.
- Q: Where does the skill install by default? → A: **Into the project** (the repo's agent
  configuration), so it is reviewable and version-controlled; **`--user` opts in** to the
  home-directory configuration instead.
- Q: If `--json` is per-invocation, what stops an agent from forgetting it? → A: **The skill
  enforces it.** The installed skill definition MUST instruct the agent to pass `--json` on
  every invocation, and every command example it carries MUST include the flag. The skill is
  what teaches the agent to call the tool, so that is where the convention is made binding —
  rather than changing the CLI's default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An agent can drive the tool and recover from failure (Priority: P1)

An AI agent is asked to bring up a development environment. It runs `agent-container`
commands, and when something fails — no host registered, port taken, credential missing —
it receives a **structured failure** it can act on: a stable code naming *what* failed, the
entity involved, and a **suggested next command**. It never has to parse prose, and it never
blocks on an interactive prompt.

**Why this priority**: This is the foundation and the MVP. Without predictable failure
semantics an agent cannot recover, and every other capability here is unusable in practice.
On its own it makes the existing command set agent-operable.

**Independent Test**: Drive a full lifecycle (choose host → start → inspect → tear down)
using only non-interactive, machine-readable invocations; force each defined failure class
and confirm every one yields a stable identifier plus an actionable remediation, with a
non-zero exit and nothing blocking.

**Acceptance Scenarios**:

1. **Given** any command that fails, **When** an agent invokes it in machine-readable mode,
   **Then** the failure carries a **stable identifier**, the affected entity, and a
   suggested remediation — and the process exits non-zero without waiting for input.
2. **Given** a destructive command invoked without confirmation in a non-interactive
   context, **When** an agent runs it, **Then** the tool **refuses rather than prompting**
   and states exactly which flag would authorize it.
3. **Given** an agent needs to discover capabilities, **When** it requests help in
   machine-readable form, **Then** it receives the commands, their arguments, and their
   effects in a structured form — without scraping formatted help text.
4. **Given** a successful command, **When** invoked in machine-readable mode, **Then**
   human-oriented decoration (progress, colour, spinners, tables) never contaminates the
   parsed output stream.

---

### User Story 2 - An agent can load the tool's context in one call (Priority: P2)

Before acting, an agent needs to know the state of the world: which hosts exist and whether
they are reachable, which environments exist and their health, which conventions apply in
this directory (project spec, env files, credential locations), and what the tool considers
the sensible next step. A single `context` surface provides that as structured output the
agent loads as context.

**Why this priority**: Ergonomics and correctness over US1 — an agent *can* work without it
by issuing many commands, but it will do so slowly and will guess about conventions. It also
depends on US1's output discipline being in place.

**Independent Test**: In several distinct states (nothing configured; a healthy running
environment; a broken/unreachable host; inside a declarative project directory), request the
context surface and confirm each state is represented accurately, that it is valid
structured output in every case, and that **no secret value appears anywhere in it**.

**Acceptance Scenarios**:

1. **Given** any machine state, **When** an agent requests the context surface, **Then** it
   receives valid structured output describing hosts, environments, applicable conventions,
   and the suggested next step.
2. **Given** state that involves credentials, **When** the context is emitted, **Then** it
   names **locators only** (which file, which variable, which manager reference) and
   **never a secret value**.
3. **Given** nothing is configured yet, **When** the context is requested, **Then** the
   output is still valid and complete (an empty world is described, not an error).
4. **Given** a host is unreachable, **When** the context is requested, **Then** that is
   reported as a known state rather than failing the whole call.

---

### User Story 3 - An operator installs the skill so their agent knows the tool (Priority: P3)

An operator runs a single command to **install** a skill definition into their local agent
configuration. Their agent then has a documented, first-class way to invoke
`agent-container`. Later they can **update** it (after upgrading the tool) or **remove** it
cleanly. Re-running the install is safe, and their own edits are never silently destroyed.

**Why this priority**: This is the distribution mechanism — valuable, but it depends on US1
and US2 existing (a skill that documents an agent-hostile CLI has little to offer). It is
also the only part that writes outside the tool's own state.

**Independent Test**: Install the skill into a scratch agent configuration and confirm the
agent can discover it; re-run the install and confirm it is a no-op; modify the installed
definition by hand and confirm an update does not silently overwrite the edit; remove it and
confirm no trace remains.

**Acceptance Scenarios**:

1. **Given** a supported agent configuration, **When** the operator installs the skill,
   **Then** the definition is written where that agent discovers it, and the operator is
   told exactly what was written.
2. **Given** the skill is already installed and unmodified, **When** the operator installs
   again, **Then** it is an **idempotent no-op** (or a clean version update), reported as
   such.
3. **Given** the operator has hand-edited the installed definition, **When** an update runs,
   **Then** the tool **refuses to silently overwrite**, reports the difference, and requires
   explicit intent.
4. **Given** an installed skill, **When** the operator removes it, **Then** the definition is
   deleted and nothing the tool created is left behind.
5. **Given** an unsupported or absent agent configuration, **When** an install is attempted,
   **Then** the tool refuses with a clear statement of what it looked for and where.
6. **Given** the installed skill definition, **When** an agent reads it, **Then** it is
   instructed to pass `--json` on every invocation, and **every command example in the skill
   carries the flag** — so the machine-readable convention is enforced by the agent's own
   instructions rather than left to recall.

---

### Edge Cases

- **Output is piped, not a terminal** — decoration, colour, and progress must be suppressed
  so parsed output is never corrupted.
- **A destructive verb is invoked non-interactively** — refuse and name the authorizing flag;
  never block on a prompt (an agent has no way to answer one).
- **Context requested in an empty world** — valid, complete, empty output; not an error.
- **Context requested where a host is unreachable** — the unreachable host is a *described
  state*, not a failure of the whole call.
- **Secret-adjacent state in context** — env files, key files and manager references appear
  as **locators**; a value never does.
- **Skill target agent not installed / unknown** — refuse, naming what was searched for.
- **Installed skill was hand-edited** — never clobber silently; report and require intent.
- **Tool upgraded after skill install** — the operator can update, and a stale definition is
  detectable.
- **Two agents configured on one machine** — the operator can say which to target rather
  than the tool guessing.
- **A long-running command (build, provision) is driven by an agent** — progress must not
  corrupt machine-readable output, and the caller must still be able to tell success from
  failure.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every command MUST accept a **`--json` flag** that switches it to
  machine-readable structured output, extending the convention the existing commands already
  use. Mode is selected **per command invocation** — there is no global switch or environment
  variable — so an agent passes the flag on every call.
- **FR-002**: In machine-readable mode, human-oriented decoration (colour, progress,
  spinners, tables) MUST NOT appear in the parsed output stream.
- **FR-003**: Every failure MUST carry a **stable identifier** for the failure class,
  identifying *what* failed independently of the wording of the message.
- **FR-004**: Every failure MUST name the **affected entity** (which environment, host,
  credential, port) where one applies.
- **FR-005**: Every failure MUST carry a **suggested remediation** — the next command or
  action that would resolve it — in a form an agent can act on, wherever one exists.
- **FR-006**: Every machine-readable payload MUST carry an **explicit schema version** that
  an agent can inspect, so the contract can evolve without silently breaking callers and a
  breaking change is detectable rather than discovered at runtime.
- **FR-007**: The tool MUST **never block on an interactive prompt** when not attached to an
  interactive terminal; it MUST instead refuse and state which flag authorizes the action.
- **FR-008**: The tool MUST provide **machine-readable help**: the available commands, their
  arguments, and their effects, discoverable without scraping formatted help output.
- **FR-009**: The tool MUST provide a **`context` surface** that emits, in one call, the
  state relevant to an agent: known hosts and their reachability, known environments and
  their state, the conventions applicable in the working directory, and the suggested next
  step.
- **FR-010**: The context surface MUST be **valid and complete in every state**, including an
  empty, partially configured, or broken world — an unconfigured machine or an unreachable
  host is *described*, not an error.
- **FR-011**: The context surface MUST express credential-related state as **locators only**
  (which file, variable, or manager reference) and MUST **never emit a secret value**
  (Constitution III, Least Exposure).
- **FR-012**: The tool MUST provide a **`skill` command** that **installs**, **updates**, and
  **removes** a skill definition in the local agent configuration.
- **FR-012a**: The skill definition MUST conform to the **Agent Skills open standard** — a
  folder containing a `SKILL.md` whose frontmatter carries at least `name` and `description`
  — so it is portable across every skills-compatible agent rather than bespoke per tool.
- **FR-012b**: The skill MUST install into the **project's** agent configuration by default,
  so it is reviewable and version-controlled alongside the code it describes; installing into
  the **user's** home configuration MUST require an explicit opt-in. The chosen scope MUST be
  stated in what the command reports (FR-016).
- **FR-012c**: The skill definition MUST **enforce the machine-readable convention**: it MUST
  instruct the agent to pass `--json` on **every** invocation, and **every command example it
  contains MUST include the flag**. This is what makes the per-invocation choice in FR-001
  workable — the agent's own instructions carry the convention, so it is not left to the
  agent to remember.
- **FR-013**: Installing the skill MUST be **idempotent**: re-running it on an unmodified,
  current installation makes no change and reports that.
- **FR-014**: The skill command MUST **never silently overwrite an operator's edits** to an
  installed definition; it must detect the difference, report it, and require explicit
  intent to replace.
- **FR-015**: Removing the skill MUST leave **no residue** from what the tool installed.
- **FR-016**: The skill command MUST report **exactly what it wrote, changed, or removed, and
  where**.
- **FR-017**: The skill command MUST support the four named agents — **Claude Code,
  pi-coding-agent, OpenAI Codex, and opencode** — and let the operator choose the target when
  several are present, rather than guessing. Because all four consume the same standard
  format, supporting a further agent MUST require only its **discovery path**, not a new
  definition.
- **FR-018**: An unsupported or absent agent configuration MUST cause a **clear refusal**
  naming what was looked for and where — never a partial or silent install.
- **FR-019**: All existing human-facing behavior (the guided wizard, prose messages,
  prompts) MUST remain unchanged when the tool is used interactively — this feature is
  **additive**.

### Key Entities *(include if feature involves data)*

- **Failure descriptor**: the structured form of a failure — a stable identifier, the
  affected entity, a human message, and a suggested remediation.
- **Agent context**: the point-in-time, structured description of hosts, environments,
  applicable conventions, and the suggested next step; contains **locators, never secrets**.
- **Skill definition**: the artifact installed into a local agent configuration that teaches
  an agent how to invoke the tool; has an identity, a version, and a location, so it can be
  updated, detected as drifted, and removed.
- **Agent target**: a supported local agent configuration (its location and format) that the
  skill command can install into.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can complete a full environment lifecycle (choose host → start →
  inspect → tear down) using **only machine-readable output**, with no parsing of prose and
  no human intervention.
- **SC-002**: For every defined failure class, the failure yields a **stable identifier and
  an actionable remediation** — verified for 100% of defined classes.
- **SC-003**: No invocation blocks waiting for input when run non-interactively — 100% of
  destructive and interactive paths either proceed under explicit authorization or refuse.
- **SC-004**: The context surface returns **valid structured output in 100% of machine
  states** exercised, including empty, healthy, broken, and declarative-project states.
- **SC-005**: **No secret value ever appears** in machine-readable output or the context
  surface — 100% of runs.
- **SC-006**: Installing the skill twice produces **no change on the second run**, and a
  hand-edited definition is never overwritten without explicit intent — 100% of runs.
- **SC-007**: After removal, **no artifact the tool installed remains** in the agent
  configuration.
- **SC-008**: Interactive human use is unchanged — existing prompts, wizard, and prose
  behavior continue to work exactly as before.

## Assumptions

- **Machine-readable means the existing `--json` convention**, extended to every command
  rather than the three that carry it today; a new output format is not introduced. Selecting
  it **per invocation** (FR-001) is made workable by **FR-012c**: the installed skill
  instructs the agent to pass `--json` every time, so the convention lives in the agent's own
  instructions rather than depending on recall. Should it still be omitted, the failure is
  **self-evident** — the output does not parse as structured data — rather than silently
  yielding wrong values.
- **Structured output goes to standard output; human and diagnostic text goes to standard
  error**, following the discipline Feature 005 established for its print/emit surface, so a
  parsing caller reads a clean stream.
- **Errors keep their current human wording**; this feature *adds* the stable identifier and
  remediation rather than rewriting messages, so humans see no regression.
- **Supported agent targets are Claude Code, pi-coding-agent, OpenAI Codex, and opencode**;
  all four implement the Agent Skills open standard, so one standard-conformant definition
  serves them all and adding another agent is a discovery path, not new content.
- **The agents that DRIVE the CLI and the agents that RUN INSIDE the container are the same
  four** — the container's agent set is being extended with opencode to match, so the two
  lists do not diverge.
- The skill's install scope is no longer an assumption — it is **FR-012b** (project by
  default, `--user` to opt in).
- **Non-interactive refusal of destructive actions already exists for some verbs**; this
  feature generalizes that behavior rather than inventing it.
- This feature concerns the **host-side CLI only** and changes neither the container image
  nor the entrypoint.

## Out of Scope

- Changing what runs **inside** the container (that is Feature 004); this feature is about
  agents **driving** the CLI from outside.
- Authoring the agents themselves, or any agent-side runtime/harness.
- A network API, daemon, or RPC surface — the contract remains a command-line invocation.
- Autonomous action by the tool: it reports state and suggests a next step; it does not
  decide or act unattended.
- Rewriting the guided wizard (Feature 007) for agent use — the wizard stays human-facing.

## Dependencies

- **Feature 005 (shell integration)**: the established discipline that structured output is
  stdout-only, humans go to stderr, and an error produces empty stdout with a non-zero exit.
- **Feature 006 (agent-as-code)** and **Feature 008 (credential managers)**: the declarative
  project and credential-locator concepts the context surface reports on.
- **Feature 007 (guided wizard)**: the state assessment and "suggested next step" logic the
  context surface can express in machine-readable form.
- **Constitution III (Least Exposure)**: the load-bearing guarantee that no secret value ever
  reaches machine-readable output.
