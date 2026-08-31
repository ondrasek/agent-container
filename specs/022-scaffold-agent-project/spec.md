# Feature Specification: Scaffold a new agent project

**Feature Directory**: `specs/022-scaffold-agent-project`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "A new CLI command to create/scaffold a new agent - new directory, a set of \"fresh\" configuration files, etc."

## Why this exists

An agent environment is declared by a **directory of files** — a project marker
directory holding a spec that names the environment, its host, its container, its
task, its credentials as locators, and optionally its egress policy. That model is
good: it is plain text, reviewable, and committable.

Getting the **first** such directory is the problem. Today an operator must know
which filenames are recognised, which suffix identifies a spec, which keys are
allowed, which values each key accepts, and where per-agent configuration has to
sit for the agent to actually read it. All of that is documented, and all of it has
to be assembled by hand before anything can be validated. The failure modes are
quiet ones: a file whose name is not recognised, a key that is silently in the
wrong place, per-agent configuration delivered to a directory the agent never
reads.

The tool already knows every one of those rules — it validates against them. This
feature makes it **write** them as well as check them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create a project that is valid immediately (Priority: P1)

An operator in an empty directory asks the tool for a new agent environment,
naming it. The tool creates the project directory and a starting spec, then tells
them exactly what it wrote. Validating the result succeeds **on the first try**,
with no edits — and deploying it produces a working environment.

**Why this priority**: This is the feature. A scaffold whose output does not
validate has moved the work rather than removed it; a scaffold whose output
validates but cannot deploy has moved it further downstream, where it is more
expensive to discover.

**Independent Test**: In an empty directory, scaffold an environment, then run the
validation verb without editing anything. It reports the environment as declared
and not yet deployed, with no errors.

**Acceptance Scenarios**:

1. **Given** an empty directory, **When** the operator scaffolds an environment
   named `acme`, **Then** a project directory and a spec declaring `acme` exist,
   and validation of that spec succeeds with no edits.
2. **Given** a freshly scaffolded project, **When** the operator deploys it,
   **Then** the environment comes up — the scaffold's output is deployable, not
   merely parseable.
3. **Given** a completed scaffold, **When** the tool reports what it did, **Then**
   every file it created is named, and nothing it did not create is implied.
4. **Given** a name that is not a legal environment identity, **When** the operator
   scaffolds with it, **Then** the tool refuses before creating anything and says
   which characters are allowed.

---

### User Story 2 - Choose what the environment is, at creation (Priority: P1)

The operator states the properties that differ per environment — which agent, run
interactively or headless, what kind of workspace, optionally a repository to clone
— and the scaffold writes those into the spec rather than leaving them to be
edited afterwards.

**Why this priority**: The same priority as US1 because a scaffold that always
emits one fixed shape is a copy-paste snippet. What makes it a command is that it
encodes the operator's actual choices, and those choices are exactly where the
allowed values are hard to remember.

**Independent Test**: Scaffold two environments with different agents and modes;
confirm each spec carries the requested values and each validates.

**Acceptance Scenarios**:

1. **Given** a requested agent, mode and workspace kind, **When** the scaffold
   runs, **Then** the spec declares those values.
2. **Given** a value that is not among the allowed ones for its field, **When** the
   operator asks for it, **Then** the tool refuses, names the field, and lists the
   accepted values — before writing any file.
3. **Given** no explicit choices, **When** the scaffold runs, **Then** it uses the
   tool's own named defaults and **reports which defaults it applied**, so the
   result is never a decision made silently on the operator's behalf.

---

### User Story 3 - Add an environment to a project that already exists (Priority: P2)

An operator with a working project wants a second environment beside the first —
for a different agent, or a different task — without hand-copying the existing
declaration and editing the parts that must differ.

**Why this priority**: The second environment is where copy-paste actually starts,
and where a duplicated identity does damage. It is not needed for the first
environment to be useful, which is why it is not P1.

**Independent Test**: Scaffold into a directory that already contains a project;
confirm the new environment is added, the existing one is untouched byte-for-byte,
and both validate together.

**Acceptance Scenarios**:

1. **Given** a project declaring one environment, **When** the operator scaffolds a
   second, **Then** both are declared afterwards and the first is unchanged.
2. **Given** a project already declaring an environment of that name, **When** the
   operator scaffolds it again, **Then** the tool refuses and names the conflict —
   two environments sharing a name would collide in identity.
3. **Given** an existing file the scaffold would otherwise write, **When** the
   scaffold runs, **Then** it refuses to overwrite and names the file, making no
   partial change.

---

### User Story 4 - Start from a known-good variant (Priority: P3)

Rather than the tool's baseline, the operator scaffolds from a **named
configuration variant** — the same named variants that environments can select —
so a new environment starts from a setup that is already known to work.

**Why this priority**: Valuable, and deliberately last: it depends on named
variants existing as a concept. The scaffold must be complete and useful without
it, and gain this when that concept lands.

**Independent Test**: With a named variant defined, scaffold from it and confirm
the new project carries that variant's configuration and validates.

**Acceptance Scenarios**:

1. **Given** a named variant, **When** the operator scaffolds from it, **Then** the
   new project's configuration matches that variant.
2. **Given** a variant name that does not exist, **When** the operator scaffolds
   from it, **Then** the tool refuses, names it, and lists the ones that do exist —
   never falling back to the baseline.

---

### Edge Cases

- **The target directory is not empty but has no project** — proceed, creating only
  what is missing, and report it. An existing unrelated file is not a conflict.
- **A project already exists** — this is US3, not an error: add to it.
- **A file the scaffold would write already exists** — refuse, name it, change
  nothing. Never merge into a file the operator may have hand-edited.
- **The environment name is already declared** — refuse; names map to a
  deterministic identity and two environments cannot share one.
- **The name is not a legal identity** — refuse before creating anything.
- **The scaffold is interrupted partway** — leave either the complete result or
  nothing recognisable as a project; never a half-written spec that fails
  validation for reasons the operator did not cause.
- **A per-agent configuration file is scaffolded for an agent that reads it from a
  specific location** — it must be written where that agent actually reads it, or
  it is inert while appearing present.
- **The operator scaffolds inside a git repository** — the output must be safe to
  commit: no secret values, no machine-specific absolute paths.
- **A value can only come from the operator** (a repository URL) — the scaffold
  must not invent one; it marks the field and the result must still validate, or
  the field is omitted entirely rather than filled with a guess.

## Requirements *(mandatory)*

### Functional Requirements

**Creating**

- **FR-001**: The system MUST create, in one command, a project directory and a
  starting specification that declares one named environment.
- **FR-002**: The generated specification MUST validate successfully with no edits.
  A scaffold whose output the tool itself rejects is a defect, not a starting point.
- **FR-003**: The generated specification MUST be deployable as written, except for
  fields whose value only the operator can supply.
- **FR-004**: The system MUST accept the environment's name and MUST validate it
  against the same identity rules the rest of the tool uses, refusing before
  creating anything.
- **FR-005**: The system MUST allow the operator to specify which agent, which
  execution mode, which workspace kind, and optionally a repository to clone, and
  MUST write those choices into the specification.
- **FR-006**: Any value the operator does not specify MUST come from a **named**
  default, and the system MUST report which defaults it applied.
- **FR-007**: A value outside the accepted set for its field MUST be refused before
  any file is written, naming the field and listing the accepted values.
- **FR-008**: Where an agent requires configuration in a specific location to be
  read at all, the system MUST scaffold that configuration in that location.

**Not overwriting**

- **FR-009**: The system MUST NOT overwrite or modify any existing file. If a file
  it would write already exists, it MUST refuse, name the file, and make no partial
  change.
- **FR-010**: When a project already exists, the system MUST add the new environment
  to it, leaving every existing declaration byte-for-byte unchanged.
- **FR-011**: A name already declared in the project MUST be refused, naming the
  conflict.
- **FR-012**: An interrupted run MUST NOT leave a partially written specification
  that fails validation.

**Safety of what is written**

- **FR-013**: The system MUST NOT write any secret value into any generated file.
  Credentials MUST appear as **locators** — what to read and from where — never as
  values.
- **FR-014**: Generated files MUST be safe to commit: no secret material, and no
  path that is meaningful only on the machine that ran the command.
- **FR-015**: The system MUST NOT generate any private key or other standing
  credential.

**Reporting**

- **FR-016**: On completion the system MUST list every file it created, and MUST NOT
  imply it created anything it did not.
- **FR-017**: The system MUST tell the operator what to do next, naming the verb
  that validates the result.
- **FR-018**: The system MUST be able to report what it *would* create without
  creating it, so the effect can be examined before it happens.

**Starting from a variant**

- **FR-019**: The system MUST be able to scaffold from a **named configuration
  variant** where such variants exist, producing a project whose configuration
  matches it.
- **FR-020**: A named variant that cannot be resolved MUST be refused, naming it and
  listing those that exist. The system MUST NOT fall back to the baseline.

### Key Entities

- **Scaffold Request**: What the operator asked for — the environment's name, the
  agent, mode and workspace kind, an optional repository, and an optional named
  variant to start from. Every field except the name has a named default.
- **Generated Project**: The directory and the files created. Its defining property
  is that it validates and deploys unedited.
- **Creation Report**: The list of files actually created, the defaults that were
  applied and where they came from, and the next verb to run. Distinguishes *created*
  from *already present* from *refused*.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newly scaffolded project passes validation on the first attempt,
  with zero edits, in 100% of scaffolds.
- **SC-002**: An operator who has never written one of these specifications by hand
  can go from an empty directory to a validated project in a single command.
- **SC-003**: Zero generated files contain a secret value; every credential appears
  as a locator.
- **SC-004**: Zero generated files contain a path that is meaningful only on the
  machine that created them.
- **SC-005**: No existing file is ever modified or overwritten — across every
  scaffold into a non-empty directory, the count of pre-existing files changed is
  zero.
- **SC-006**: Every default the scaffold applies is reported, so the operator can
  tell what they chose from what was chosen for them.
- **SC-007**: The set of files a scaffold would create can be determined before it
  creates them, and matches what it then creates.
- **SC-008**: A refused scaffold — bad name, conflicting name, existing file,
  unresolvable variant — leaves the directory exactly as it found it.

## Assumptions

Decisions taken where the description left room. Each is recorded with its tradeoff
and is reversible at planning time.

- **The scaffold produces a complete, valid specification rather than a commented
  template.** A template that must be edited before it validates puts the operator
  back where they started, and the errors surface later. Where a value genuinely
  cannot be invented — a repository URL — the field is omitted rather than filled
  with a placeholder that would make the spec invalid. **Tradeoff**: the output is
  less self-documenting than a heavily commented example; the mitigation is that
  comments can be emitted alongside real values rather than instead of them.
- **It creates a project *and* adds to one.** These are the same operation from the
  operator's side — "give me a new environment here" — and splitting them into two
  commands would make the operator classify their own directory first. **Tradeoff**:
  one command with two behaviours, distinguished by what it finds.
- **It never overwrites, and never merges into an existing file.** Refusing is
  recoverable; a silent merge into a hand-edited spec is not. **Tradeoff**: an
  operator re-running after a partial failure has to remove files themselves, which
  is the safer error to make.
- **Named configuration variants are a separate concept this feature consumes.**
  Variants are specified independently; this feature works without them and gains
  US4 when they exist. **Tradeoff**: US4 cannot be completed until then, which is
  why it is P3 and separable.
- **The interactive wizard is not replaced.** The wizard walks an operator through
  *deploying*; this writes *files*. They may share machinery, but a scaffold must be
  usable non-interactively — from a script, or by an agent driving the tool.
- **The command does not deploy anything.** Scaffolding and deploying stay separate
  so the operator can read what was written before anything runs.

## Out of Scope

- Deploying the scaffolded environment, or any change to a running container.
- Generating credentials, keys, or any secret material.
- Initialising a git repository, committing, or configuring a remote.
- Migrating or rewriting an existing project into a different shape.
- Defining what named configuration variants are or how they resolve.
- Scaffolding anything outside the project directory, including user-level settings.
