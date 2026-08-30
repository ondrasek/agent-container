# Feature Specification: Agent Configuration Templates

**Feature Directory**: `specs/021-agent-config-templates`

**Created**: 2026-08-30

**Status**: Draft

**Input**: User description: "Support for agent configuration templates, i.e. different variants of claude code, pi, etc. configurations. One of the is designated the default, the current configuration that we are using. Configuration templates are named and are configured via the yaml file and overriden using cli arguments."

## Why this exists

Today an agent's configuration is addressed by the **environment's** name: the files
an agent receives come from a directory named after the environment it is deployed
into. That binding has two consequences the operator pays for:

- **Two environments cannot share one configuration** without copying every file. The
  copies then drift, and nothing detects that they have.
- **One environment cannot switch between variants.** Changing how an agent is set up
  means editing files in place, which destroys the previous variant. There is no way
  to keep "the lean setup" and "the everything-enabled setup" side by side and pick
  one per deployment.

A configuration template gives the configuration its **own name**, independent of any
environment. Environments then *select* a template instead of *owning* a directory.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Name a configuration and select it (Priority: P1)

An operator maintains several distinct ways of setting up an agent — for example a
minimal setup for routine work and a fuller one carrying project guidance and tool
definitions. They give each variant a name, designate one as the default, and record
in the environment's declaration which variant that environment uses. Deploying the
environment delivers exactly that variant's files to the agent. An environment that
names nothing gets the designated default.

**Why this priority**: This is the feature. Naming a configuration and selecting it by
name is what makes variants possible at all; every other story is an affordance layered
on top. Delivered alone, it already lets one configuration serve many environments and
lets an operator keep several variants side by side.

**Independent Test**: Define two named templates and two environments; point each
environment at a different template; deploy both and confirm each agent received its
template's files and none of the other's. Then remove one environment's selection and
confirm it receives the designated default.

**Acceptance Scenarios**:

1. **Given** two named templates and an environment whose declaration selects one of
   them, **When** the operator deploys the environment, **Then** the agent receives the
   selected template's configuration files and no file from the other template.
2. **Given** an environment whose declaration selects no template and a designated
   default, **When** the operator deploys it, **Then** the agent receives the default
   template's files, and the report names the default that was applied.
3. **Given** two environments selecting the same template, **When** both are deployed,
   **Then** both agents receive identical configuration with the template's files stored
   in exactly one place.
4. **Given** an environment selecting a template name that does not exist, **When** the
   operator deploys it, **Then** the deployment is refused before any container is
   created, and the message names the missing template and lists the names that do exist.
5. **Given** an environment that declares its selection as explicitly empty, **When** it
   is deployed, **Then** no template configuration is delivered, and this outcome is
   reported as a declared choice rather than as an absence or a default.

---

### User Story 2 - Override the selection for one run (Priority: P2)

An operator wants to try a variant without editing the declaration — to reproduce a
colleague's setup, to test a candidate configuration before adopting it, or to run one
environment temporarily under different settings. They name the template on the command
line; that choice governs the run, and the declaration is left untouched.

**Why this priority**: Selection by declaration (P1) is already usable without this, but
every experiment then requires editing and reverting a file, which is exactly how a
temporary change becomes a permanent accident.

**Independent Test**: Deploy an environment whose declaration selects template A while
naming template B on the command line; confirm the agent received B, that the report
says the declaration was overridden, and that the declaration file is unchanged on disk.

**Acceptance Scenarios**:

1. **Given** an environment whose declaration selects template A, **When** the operator
   deploys naming template B on the command line, **Then** the agent receives B's files
   and the declaration file is byte-for-byte unchanged.
2. **Given** any environment, **When** the operator deploys with the command-line option
   that selects no template at all, **Then** no template configuration is delivered even
   if the declaration or the default would have supplied one.
3. **Given** a command line naming a template that does not exist, **When** the operator
   deploys, **Then** the deployment is refused with the same message as an unresolvable
   declared name, and no container is created.
4. **Given** a command-line override, **When** the deployment reports what it applied,
   **Then** the report states both the value applied and that it came from the command
   line rather than from the declaration or the default.

---

### User Story 3 - Different variants for different agents (Priority: P2)

An environment may run more than one agent. The operator wants one agent configured
from one template and another from a different one — for example a heavier setup for
the agent doing the work and a lean one for the agent used to review it — without
having to create a combined template for every pairing they might want.

**Why this priority**: The user's framing is explicitly per-agent ("variants of claude
code, pi, etc. configurations"). Without this, N variants of one agent and M of another
require N×M combined templates, which is the duplication this feature exists to remove.

**Independent Test**: Deploy one environment that selects template A for every agent but
names template B for a single agent; confirm that agent received B's files and the others
received A's.

**Acceptance Scenarios**:

1. **Given** an environment selecting one template for all its agents, **When** it also
   selects a different template for one named agent, **Then** that agent receives the
   named template and every other agent receives the environment-wide one.
2. **Given** a per-agent selection naming an agent the environment does not run, **When**
   the operator deploys, **Then** the deployment is refused and the message names the
   agent that is not present.
3. **Given** a template that carries files for several agents, **When** it is selected for
   one agent only, **Then** only that agent's files are delivered.

---

### User Story 4 - See what exists and what was applied (Priority: P3)

Before deploying, an operator wants to know which templates are available, which one is
designated the default, and which files a given selection would actually deliver. After
deploying, they want the record to state which template each agent was configured from.

**Why this priority**: Selection is usable without inspection, but a selection whose
effect cannot be examined is one the operator has to verify by deploying — which is slow
and, for a wrong template, wasteful. This is also what makes the layering auditable
rather than merely correct.

**Independent Test**: With several templates defined at both configuration levels, list
them and confirm the listing shows every name, its origin level, and which is the
default; then preview one environment's resolved configuration and confirm the file list
matches what a deployment delivers.

**Acceptance Scenarios**:

1. **Given** templates defined at both the user and project level, **When** the operator
   lists templates, **Then** every name appears once with the level it was resolved from,
   and shadowed same-name definitions are shown as shadowed rather than omitted.
2. **Given** an environment and a selection, **When** the operator previews the resolved
   configuration, **Then** each file that would be delivered is listed with the layer it
   came from, without deploying anything.
3. **Given** a completed deployment, **When** the operator inspects the environment's
   record, **Then** it states the template applied to each agent and where that selection
   came from.
4. **Given** no templates are defined at all, **When** the operator lists them, **Then**
   the result reports that none are defined, distinctly from an error.

---

### Edge Cases

- **Named template does not exist** — refuse the deployment, name the missing template,
  and list the available names. Never silently fall back to the default: a fallback turns
  a typo into a deployment the operator did not ask for and cannot see they did not get.
- **Designated default does not exist** — refuse any deployment that would rely on it,
  and say that the *designation* is unresolvable. An environment with its own explicit
  selection is unaffected.
- **No default designated and none discoverable** — an environment that selects nothing
  receives no template configuration. This is the pre-feature behaviour and is not an
  error; it is reported as "no template applied".
- **Template directory exists but contains no recognised files** — deliver nothing from
  it and report it as an empty template. Distinct from a missing one.
- **Template contains files the agent does not read** — not delivered, matching the
  existing rule that only recognised configuration is delivered and everything else is
  treated as the agent's own runtime state.
- **Template appears to carry credential material** — refuse it. Templates are shared,
  named, and committed; a secret in one is a secret in every environment that selects it.
- **Same template name defined at both configuration levels** — the project-level
  definition governs, whole, and the listing shows the user-level one as shadowed.
- **The same file is provided by both the template and the environment's own
  configuration** — the environment's file governs, and the report attributes each
  delivered file to its layer so the override is visible rather than silent.
- **Selection changes between deployments of a live environment** — the delivered set is
  replaced to match the new selection; files the previous template delivered and the new
  one does not are removed, so a selection change can withdraw configuration and not only
  add it.
- **Template selected for an agent the environment does not run** — refuse, naming the
  agent.

## Requirements *(mandatory)*

### Functional Requirements

**Defining templates**

- **FR-001**: The system MUST support configuration templates identified by a **name**
  that is independent of any environment name, so that one template can serve many
  environments and one environment can move between templates.
- **FR-002**: A template MUST be definable at both the user and the project configuration
  level, using the same layout at each level, with the project-level definition of a given
  name governing over a user-level definition of that name, whole.
- **FR-003**: A template MUST be able to carry configuration for more than one agent, so
  that a single named variant can describe a coherent multi-agent setup.
- **FR-004**: A template MUST NOT carry credential material, and the system MUST refuse a
  template that carries it rather than delivering it.
- **FR-005**: Files in a template that are not recognised configuration for their agent
  MUST NOT be delivered, consistent with the existing treatment of unrecognised files as
  agent runtime state.
- **FR-006**: A template MUST be able to declare agent-scoped settings in addition to
  files, drawn from a closed, named set of settings that describe how an agent is
  configured. A template MUST NOT declare deployment topology — anything governing how the
  environment itself is deployed, reached, or isolated.

**Designating a default**

- **FR-007**: The system MUST allow exactly one template to be **designated** the default
  through the settings file, by name, so the default can be changed without renaming or
  moving any template.
- **FR-008**: When no designation is declared, the system MUST resolve the default through
  a single named fallback rather than an unnamed literal, and MUST report which of the two
  supplied the default it used.
- **FR-009**: When a designated default cannot be resolved, the system MUST refuse any
  deployment that would depend on it and MUST attribute the failure to the designation, not
  to the environment.

**Selecting a template**

- **FR-010**: An environment MUST be able to select a template by name in the YAML
  declaration, applying to every agent the environment runs.
- **FR-011**: An environment MUST be able to select a template for an individual agent,
  overriding the environment-wide selection for that agent only.
- **FR-012**: Operators MUST be able to override any declared selection from the command
  line, both environment-wide and for an individual agent, without modifying any file on
  disk.
- **FR-013**: The system MUST resolve a selection through a single, documented precedence:
  command line, then per-agent declaration, then environment-wide declaration, then the
  designated default. Each level MUST be able to state "no template" explicitly.
- **FR-014**: The system MUST distinguish **absent**, **defaulted**, and **declared-empty**
  selections at every level and MUST NOT collapse them, so that "nothing was said" and
  "nothing was wanted" remain different facts.
- **FR-015**: A selection naming a template that does not exist MUST be refused before any
  container is created, with a message naming the unresolved template and the names that do
  exist. The system MUST NOT fall back to the default.
- **FR-016**: A per-agent selection naming an agent the environment does not run MUST be
  refused, with a message naming that agent.

**Composition and delivery**

- **FR-017**: The system MUST compose the delivered configuration from an ordered stack of
  layers — the selected template first, then the environment's own configuration — with the
  later layer governing per file.
- **FR-018**: The system MUST attribute every delivered file to the layer it came from, so
  that an override is reported rather than inferred.
- **FR-019**: Redeploying an environment whose selection changed MUST make the delivered set
  match the new selection, removing files the previous selection delivered that the new one
  does not.
- **FR-020**: An environment that declares no selection, in a setup where no default is
  designated or discoverable, MUST receive exactly the configuration it receives today.

**Inspection**

- **FR-021**: Operators MUST be able to list the defined templates, each shown with the
  configuration level it resolved from, with same-name definitions at a lower-precedence
  level shown as shadowed rather than omitted.
- **FR-022**: Operators MUST be able to preview the resolved configuration for an
  environment — every file that would be delivered, with its originating layer — without
  deploying.
- **FR-023**: The system MUST record, per deployed environment, which template governed each
  agent and which precedence level supplied that selection.
- **FR-024**: When no templates are defined, listing MUST report their absence as a result,
  not as an error.

### Key Entities

- **Configuration Template**: A named, environment-independent bundle of agent
  configuration — recognised configuration files for one or more agents, plus optionally a
  closed set of agent-scoped settings. Non-secret by definition. Resolved from the project
  level first, then the user level.
- **Default Designation**: The declaration, in the settings file, naming which template
  applies when an environment selects none. Distinct from the template itself, so the
  default can move without any template moving.
- **Selection**: The resolved answer to "which template governs this agent in this
  environment", together with the precedence level that supplied it. Carries three
  distinguishable non-values: not stated, explicitly none, and unresolvable.
- **Layer Stack**: The ordered sequence composing the delivered configuration — selected
  template, then environment-specific configuration — where a later layer governs a file the
  earlier one also provided.
- **Delivered Configuration Set**: What an agent actually receives for a deployment: each
  file, its content's originating layer, and the template that supplied it. This is what the
  preview shows and what the deployment record retains.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two environments can share one configuration variant with the variant's files
  stored exactly once — zero duplicated files across the two environments.
- **SC-002**: Switching an environment between two variants requires changing exactly one
  declared value, and no configuration file is edited, moved, or deleted to do it.
- **SC-003**: Every unresolvable template name is refused before any container is created;
  across all such cases, zero deployments proceed with a substituted configuration.
- **SC-004**: An operator can determine the complete set of files a selection would deliver,
  and the layer each comes from, without deploying anything.
- **SC-005**: An environment that declares no selection, where no default is designated,
  deploys with configuration identical to the pre-feature behaviour — no operator is required
  to change anything to keep working as before.
- **SC-006**: For any deployed environment, the template that governed each agent, and the
  precedence level that chose it, can be read back from the environment's record.
- **SC-007**: The four selection outcomes — a named template, the default, explicitly none,
  and unresolvable — are distinguishable from the reported result in every case, with no two
  rendering identically.
- **SC-008**: An agent started from the designated default template reaches a usable state
  without any interactive first-run setup.
- **SC-009**: An environment with N variants of one agent and M of another can express any of
  the N×M pairings using N+M templates.

## Assumptions

These are decisions taken where the description left room, chosen for consistency with the
existing configuration model. Each is reversible at planning time.

- **A template carries files and agent-scoped settings, not deployment topology.** Settings
  that describe how an agent is set up (for example which authentication mode it uses) are
  what distinguishes one variant from another, so excluding them would make templates cover
  only half of what "a variant of a Claude Code configuration" means. Settings that govern
  the deployment — networking, isolation, host binding — stay with the environment, because a
  shared, named bundle is the wrong owner for them. **Tradeoff**: this widens the feature
  beyond file delivery and requires a named, closed set of template-scoped settings; the
  alternative (files only) is smaller but leaves variants unable to express settings-only
  differences.
- **Selection is per-agent with an environment-wide shorthand.** The description enumerates
  agents when describing variants. Environment-wide-only selection would force one combined
  template per pairing. **Tradeoff**: two selection scopes to resolve and report instead of
  one.
- **The template layers under the environment's own configuration, per file.** The
  environment-specific statement is the more specific one, so it governs. Wholesale
  replacement was rejected because adding a single environment-specific file would then
  silently discard the whole template — a "reported success while delivering nothing" failure
  this project has already paid for more than once. **Tradeoff**: composition across layers is
  a merge, whereas resolving a configuration *directory* today is first-match-wins; the two
  rules must be stated explicitly so they are not mistaken for each other. FR-018's
  per-file attribution is what keeps the merge visible.
- **The default is designated by name in the settings file**, rather than by a template
  holding a privileged name, so that the default can be changed without moving any template.
  A named fallback covers the case where nothing is designated.
- **Selecting nothing remains valid.** Operators using the tool today declare no template;
  they must keep working unchanged, so "no template" is a legitimate resolved state and not a
  degenerate one.
- **Templates are non-secret**, matching the existing rule that delivered configuration
  carries no embedded credentials; secrets continue to travel through the dedicated
  credential channel.
- **Existing environment-specific configuration directories keep working** and are not
  migrated or deprecated by this feature; they become the upper layer of the stack.

## Out of Scope

- Template inheritance or composition between templates (one template extending another).
- Templates that generate or transform files rather than provide them.
- Distributing or fetching templates from a remote registry.
- Versioning templates independently of the repository that holds them.
- Reclassifying which files count as an agent's configuration; the existing recognition rules
  are reused unchanged.
