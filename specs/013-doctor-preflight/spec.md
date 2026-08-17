# Feature Specification: `doctor` — Preflight Validation

**Feature Branch**: `013-doctor-preflight`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "A `doctor` command that validates everything a deploy depends on — layout, credentials, host reachability, image freshness, ports — and reports it before you deploy, rather than at deploy."

## Overview

Everything the tool needs in order to deploy is checked **at the moment of deploying**, and
nowhere else. So every unmet precondition is discovered the same way: a command the operator
expected to succeed fails instead.

That is a poor way to learn, and it is not theoretical. A defect shipped in v0.18.0 told an
operator to *"run from a checkout"* while they were standing in one — they learned their checkout
was stale only by running `build`. The Feature 011 hard cut created a whole class of the same
shape: a project on the previous layout is refused, correctly, but only once the operator tries
to deploy it.

`doctor` inverts that. It answers **"would a deploy work, and if not, why"** without attempting
one, and without changing anything.

The value is not merely earlier failure. Some of what it reports has no failure at all today —
an image older than the CLI that built it still runs, and the operator has no way to know they
are attached to something stale.

## Clarifications

### Session 2026-07-29

- Q: What is the command called? → A: **`doctor`.** Conventional across tools operators already
  use, and it does not collide: `status` is an **alias of `plan`** and answers "has my declared
  spec converged", which is a different question from "would a deploy work".
- Q: How is image staleness determined? → A: **A version label baked at build time.** The
  building CLI's version is recorded into the image; `doctor` compares it locally against the
  installed version. No network and no registry round-trip, so it belongs in the default pass —
  and it answers the question actually being asked.
- Q: What does the exit status mean? → A: **0** when a deploy would work (advisories permitted),
  **1** when a blocking finding would prevent it, **2** when `doctor` itself could not run — see
  the 2026-08-17 correction below, which narrows the original "2 or more". This makes
  `doctor && up` the natural idiom, and keeps advisories from failing scripts — a diagnostic
  people stop chaining is a diagnostic nobody runs.
- Q: What does a bare invocation check? → A: **This project plus the machine** — every environment
  declared in the project you are standing in, plus hosts, user configuration and the tool
  itself. A name narrows it to one environment; outside a project it degrades to machine-level.

### Session 2026-08-17

Both entries correct FR-011 against a contract that did not exist when this spec was written.
Recorded as a correction rather than an edit, because the original reasoning was sound and only
its environment changed — and because "why is this exactly 2" is the question an implementer will
otherwise re-open.

- Q: `doctor` failing was specified as "**2 or more**". Is any code above 2 still available?
  → A: **No — exactly 2.** Feature 019 shipped a tool-wide exit-code table after this spec was
  written, in which **`3` means *pending registration***; it is documented in `--help` and pinned
  by a test that builds the help text from the constants. A `doctor` returning `3` would tell an
  automated caller that an environment is awaiting SSH-key registration. `2` is already the shared
  "could not proceed" code and satisfies the original intent, so the range closes at 2.
- Q: What exit code does an **unknown** produce? → A: **Never 1** (new FR-011a). Exit `1` asserts
  that a deploy would not work; *unknown* is the state in which that assertion cannot be made. The
  original spec defined the exit status in terms of pass and fail only, leaving the third state
  — the one FR-006 makes first-class — undefined at the boundary where a program consumes it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask whether a deploy would work (Priority: P1)

An operator runs one command and gets a complete, ordered account of what a deploy would find:
what is satisfied, what is not, and for each problem, the action that fixes it. Nothing is
changed.

**Why this priority**: This is the feature. Every other story is a refinement of what it reports.

**Independent Test**: In a project with several deliberate problems, run the command once and
confirm every problem is named with its remedy, that nothing was modified, and that a healthy
project reports cleanly.

**Acceptance Scenarios**:

1. **Given** a project that would deploy successfully, **When** the operator runs `doctor`,
   **Then** it reports so and changes nothing.
2. **Given** a project with several problems, **When** the operator runs `doctor`, **Then**
   **all** of them are reported in one pass — not the first, and not one per run.
3. **Given** any reported problem, **When** the operator reads it, **Then** it names the action
   that resolves it, not merely the symptom.
4. **Given** any run, **When** it completes, **Then** no file, container, volume or registry
   entry has been created, modified or removed.

---

### User Story 2 - Distinguish "broken" from "not yet" (Priority: P1)

The report separates conditions that **will** fail a deploy from conditions that are merely
worth knowing — a stale image, an unreachable secondary host, a provider default — so an operator
can tell whether to act now or later.

**Why this priority**: A checklist where everything is equally urgent is a checklist nobody
reads. Without severity the report becomes noise, and noisy diagnostics get ignored precisely
when they matter. P1 because it determines whether US1 is usable, not because it adds capability.

**Independent Test**: Construct one blocking problem and one advisory condition; confirm they are
distinguishable both by a human reading the output and by a program reading the exit status.

**Acceptance Scenarios**:

1. **Given** a blocking problem, **When** `doctor` runs, **Then** it is clearly marked as
   preventing a deploy.
2. **Given** an advisory condition only, **When** `doctor` runs, **Then** the operator can see
   the deploy would still succeed.
3. **Given** a mix, **When** a program consumes the result, **Then** it can distinguish the two
   without parsing prose.

---

### User Story 3 - Check what the operator has, not just one project (Priority: P2)

An operator can ask about a single environment, or about their whole setup — registered hosts,
user-level configuration, the installed tool itself — without needing a project at all.

**Why this priority**: Genuinely useful, especially on a new machine, but it presumes the
per-environment reporting of US1/US2. Deferring it does not weaken them.

**Independent Test**: Run the command outside any project and confirm it reports on hosts and
user-level configuration without erroring about a missing project.

**Acceptance Scenarios**:

1. **Given** no project in the current directory, **When** `doctor` runs, **Then** it reports on
   what it *can* check and says plainly that no project was found — it does not fail.
2. **Given** several registered hosts, **When** `doctor` runs, **Then** each is reported
   individually, and one unreachable host does not suppress the others.
3. **Given** a host that cannot be reached, **When** `doctor` runs, **Then** that is reported as
   unreachable — never silently as healthy or as absent.

---

### Edge Cases

- **A check that cannot complete** (a daemon times out, a credential helper hangs) — must be
  reported as *unknown*, never as pass. A diagnostic that fails open is worse than none.
- **A slow or unreachable host** — must not hang the whole run; other checks still report.
- **A credential locator that would prompt** (keychain, 1Password) — `doctor` must not trigger an
  interactive prompt as a side effect of asking whether a credential resolves.
- **Checking must not leak a secret** — confirming a credential resolves must never print,
  log or otherwise expose its value.
- **A project in the pre-011 layout** — the single most likely real finding; must be reported
  with the move, matching what a deploy would say.
- **An image older than the CLI** — has no failure today; the operator has no way to know.
- **An image with no version stamp at all** — built before stamping existed; must be *unknown*,
  not assumed either way.
- **Nothing wrong at all** — must be quiet and unambiguous, not a wall of green.
- **`doctor` itself failing** — must be distinguishable from "the environment is unhealthy".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST provide a **`doctor`** command that reports whether a deploy would
  succeed, **without performing one**. The name MUST NOT be `status`, which is already an alias
  of `plan` and answers a different question — whether a declared spec has converged.
- **FR-002**: The command MUST be **strictly read-only**: no file, container, volume, image or
  registry entry may be created, modified or removed by running it.
- **FR-003**: A single run MUST report **all** detected problems, not stop at the first.
- **FR-004**: Every reported problem MUST name the **action that resolves it**, not only the
  symptom.
- **FR-005**: Findings MUST carry a **severity** distinguishing what blocks a deploy from what is
  advisory.
- **FR-006**: A check that cannot be completed MUST be reported as **unknown**, never as passing.
- **FR-007**: A bare invocation MUST check **every environment declared in the current project,
  plus machine-level state** (hosts, user configuration, the installed tool). Naming an
  environment MUST narrow it to that one. Outside a project it MUST degrade to machine-level
  checks and say plainly that no project was found — never fail.
- **FR-008**: One failing or unreachable check MUST NOT prevent the others from being reported.
- **FR-009**: The command MUST NOT trigger an interactive prompt as a side effect of checking
  whether a credential resolves.
- **FR-010**: No credential value may be printed, logged or otherwise exposed (Constitution III).
- **FR-011**: The result MUST be available through the existing machine-readable interface, and
  the **exit status** MUST be actionable without parsing prose: **0** when a deploy would succeed
  (advisories and unknowns permitted), **1** when a blocking check **failed**, and **exactly 2**
  when `doctor` itself could not run. **No code above 2 may be used** — the tool-wide table
  (Feature 019) assigns `3` to *pending registration*, documented in `--help` and pinned by a
  test, so a `doctor` returning `3` would tell an automated caller something false about an SSH
  key. Advisories MUST NOT produce a non-zero status — chaining `doctor && up` must remain
  viable, or the command stops being run.
- **FR-011a**: An **unknown** result MUST NOT produce exit **1**. Exit `1` asserts that a deploy
  would not work, and *unknown* (FR-006) is precisely the state in which that assertion cannot be
  made. The unknown MUST still be reported prominently — it simply is not a verdict. Failing the
  run on it would break `doctor && up` for anyone whose secondary host happened to be slow, which
  is how a diagnostic stops being chained and therefore stops being run.
- **FR-012**: The checks MUST include, at minimum: project layout validity, per-environment
  configuration resolution, credential resolvability, host reachability, image freshness relative
  to the installed tool, and port availability.
- **FR-012a**: The image build MUST stamp the **building CLI's version** into the image, and the
  freshness check MUST compare it locally against the installed version — no network or registry
  round-trip, so the check belongs in the default pass.
- **FR-012b**: An image carrying **no version stamp** predates this feature. It MUST be reported
  as **unknown**, never as fresh and never as stale — consistent with FR-006. Reporting it stale
  would nag every operator into a rebuild they may not need; reporting it fresh would assert
  something unknown.
- **FR-013**: A failure **of the command itself** MUST be distinguishable from a report that the
  environment is unhealthy.
- **FR-014**: When everything is satisfied, the output MUST be **brief** — an operator must be
  able to tell "all clear" at a glance.

### Key Entities *(include if feature involves data)*

- **Check**: one question with a name, a severity, and one of pass / fail / unknown.
- **Finding**: the result of a check that did not pass — its severity, what it observed, and the
  remedy.
- **Scope**: what a run covers — a single environment, a project, or the operator's whole setup.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a project with N deliberate problems, one run reports **all N** — no run
  reports fewer.
- **SC-002**: Running the command leaves **zero** observable side effects — verified by comparing
  filesystem, container, volume and registry state before and after.
- **SC-003**: Every finding names a remedy — **zero** findings that state only a symptom.
- **SC-004**: A blocking and an advisory finding are distinguishable by a program without parsing
  prose — **100%** of runs — and an advisory-only result exits **0**, so `doctor && up` proceeds.
- **SC-004a**: An **unknown-only** result exits **0**, and no run ever exits above **2** — **100%**
  of runs. Measures FR-011/FR-011a, whose failure is silent: a program branching on `3` reads it
  from the tool-wide table as *pending registration*.
- **SC-005**: An unreachable host is reported as unreachable, never as healthy or absent —
  **100%** of runs.
- **SC-006**: No credential value appears in any output — **100%** of runs.
- **SC-007**: A healthy setup produces a report an operator can assess in **one screen**.
- **SC-008**: A project on the pre-011 layout is reported with the same remedy a deploy would
  give — **zero** divergence between the two messages.

## Assumptions

- **Read-only is absolute, not best-effort.** A diagnostic that repairs things is a different
  feature; an operator must be able to run this without considering consequences.
- **Unknown is a first-class result.** Pass/fail is insufficient: the common real case is a host
  that did not answer in time, and calling that healthy would make the tool actively misleading.
- **Remedies are for humans.** They name the action, not a code — the audience is an operator who
  has just been surprised.
- **Checks are cheap.** This is run casually and often; it must not build images, start
  containers or resolve credentials that require interaction.
- Findings should share their wording with the corresponding deploy-time failure, so operators
  learn one message rather than two.
- **The freshness check only becomes useful after images are rebuilt.** Stamping is a build-time
  change, so every existing image reports *unknown* until it is rebuilt. That is correct rather
  than unfortunate — asserting freshness about an unstamped image would be a guess.

## Out of Scope

- Repairing anything. Reporting only.
- Migrating a project between layouts (Feature 011 deliberately made migration operator-driven).
- Continuous or background monitoring — this is invoked, not resident.
- Health of the *agent* inside a container (that is the observability feature).
- Provider or egress policy evaluation (Feature 012).

## Dependencies

- **Feature 011 (filesystem layout)**: the layout check, the shared remedy wording, and
  `image/` — where FR-012a's version stamp is applied at build.
- **Feature 003 / 008 (credentialing, credential managers)**: resolvability without prompting or
  exposure.
- **Feature 001 / 002 (hosts, lifecycle)**: host reachability, fail-closed rather than
  fail-silent.
- **Feature 009 (agent-operable CLI)**: FR-011's machine-readable result.
- **Constitution III (least exposure)**: FR-010.
