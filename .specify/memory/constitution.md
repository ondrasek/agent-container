<!--
SYNC IMPACT REPORT
==================
Version change: 2.2.0 → 2.3.0   (MINOR)

- **Added Principle VIII — Defaults Belong at the Surface.** MINOR: a new
  principle, additive, with no existing principle redefined or removed.
- Ratified after a measured defect rather than on principle: `driver_reachable_address`
  defaulted an absent host address to `localhost`, so `host_is_local` reported
  True for a remote docker context, `gather_rows` classified it as a local alias,
  and an unreachable host was never queried nor reported — the exact failure
  SC-002 (Feature 017) exists to prevent, produced by a default nobody downstream
  could see.
- Consequences already applied: defaulting moved to registration and to the
  registry-read boundary; `export_task_text` and `control_plane_hosts` report
  `None` for undeclared so the surface can say which case an operator is in;
  `DEFAULT_SSH_USER`, `DEFAULT_ATTACH_ADDRESS` and `EGRESS_ENFORCEMENT_DEFAULT`
  name what were bare literals — the last of these appeared at five separate
  decision sites, and the fifth was found by the new guard rather than by audit.

Version change: 2.1.0 → 2.2.0   (MINOR)
Bump rationale: Added a Development Workflow clause requiring
  `docs/threat-model.md` to be reconciled with every feature that alters a trust
  boundary, a credential path, or the network surface — MINOR under this file's
  own rule (materially expanding guidance, no principle removed or redefined).
  Placed in Development Workflow rather than as a principle: it is a cadence
  obligation on how changes land, not a new invariant about what the system is.
  The threat model itself is a docs artifact and ships in the wheel; the
  requirement that it record UNMITIGATED risk is the load-bearing half, since a
  document listing only successes is marketing. Prior reports retained below.

Version change: 2.0.0 → 2.1.0   (MINOR)
Bump rationale: Added Principle VII "Continuous Deployment" — a new principle
  (MINOR). `main` is always releasable and every substantive change is released
  automatically (strict semver: what users receive ships; docs/chores/internal
  churn cut no release); releasing is never a manual act. Broad/invariant
  altitude — the mechanism (python-semantic-release, workflow_run gate, OIDC
  PyPI publishing) lives in CLAUDE.md + README, not the principle. Intro triad
  extended to "...spec-driven, and continuously delivered." Prior 2.0.0 report
  retained below.

Version change: 1.1.0 → 2.0.0   (MAJOR)
Bump rationale: Principle I was REDEFINED (a MAJOR event): "Ephemerality &
  Commit-Push Discipline" → "Ephemerality". The principle was raised to the
  invariant altitude and stripped of all technology-specific mechanism (SCM /
  git / commit-push / named volumes), stating the broad rule instead: a
  container is a disposable holder of short-lived working copies, no correctness
  may rest on in-container persistence, durable state is externalized
  continuously in small increments, and the system actively supports
  ephemeralization. The commit-and-push mechanism now lives only in lower-
  altitude guidance (Development Workflow section, CLAUDE.md).

Amendments in 2.0.0 (altitude-raising pass — principles restated as broad,
technology-agnostic invariants; concrete mechanism relocated to CLAUDE.md):
  Principle I REDEFINED & RENAMED — "Ephemerality & Commit-Push Discipline" →
  "Ephemerality". Broadened to a technology-agnostic invariant; the git
  commit-push mechanism is no longer part of the principle text.
  Principle II REDEFINED & RENAMED — "Rootless by Construction, Build-Time
  Dependencies" → "Least Privilege, Immutable Runtime". Broadened from the
  rootless/no-sudo/no-runtime-apt/Podman mechanism to the underlying invariant
  (least privilege + a runtime fixed at build and immutable thereafter). The
  concrete rootless/build-time-deps mechanism lives in CLAUDE.md.
  Principle III REDEFINED & RENAMED — "Secrets Injected at Runtime — Never
  Baked, Never on Argv" → "Least Exposure". Broadened from a secrets-only rule
  to the general dual of Principle II: whatever the system reveals (data,
  secrets, network surface, identity) is exposed no more widely than needed, in
  scope and reach. The secret-specific mechanism (no baking, no argv, runtime
  injection, host-scoped grants) lives in docs/credentials.md and CLAUDE.md.
  Principle IV REDEFINED & RENAMED — "Parallel-Safe by Construction, One Source
  of Truth" → "Deterministic Identity". Broadened to the invariant: per-instance
  identity derives deterministically from one identifier, has one authoritative
  definition, and is a stable contract. The concrete on-disk contract (the
  agent-container-<name> name, the 2200 + ASCII-sum-mod-100 port formula, the
  seven volume suffixes, the XDG state/config paths, completion mirroring) is now
  mechanism in CLAUDE.md — so the specific port hash can be improved without a
  constitutional amendment, only a migration path.
  Principle V REDEFINED & RENAMED — "Hermetic, Contract-Pinned Testing &
  Real-Build Verification" → "Durable Spec, Disposable Code". Reframed from a
  testing-mechanism principle to a spec-driven stance: the spec is the artifact
  of record, code is disposable and re-derived (never patched), and verification
  is inverted-pyramid, validation/acceptance-first. NOTE: directional — it runs
  ahead of the current bottom-heavy, implementation-coupled test suite (argv
  pins, doctests); adopting it implies migrating tests toward spec-level
  validation and updating CLAUDE.md's testing guidance over time.
  Principle VI REDEFINED & RENAMED — "Idiomatic Python on uv" → "Least
  Dependencies". Reframed from a Python/uv style-and-tooling spec to a broad
  invariant (rely on the fewest packages and least coupling; every dependency
  must earn its place), completing the Least Privilege / Least Exposure / Least
  Dependencies trilogy and resolving the conflict with V (code named as
  disposable must not be locked to a language/toolchain). The packaging/tooling
  specifics (single-file PEP 723, Typer/questionary/rich, wheel↔pyproject sync,
  non-editable install, platform-aware runtime) already live in CLAUDE.md's
  Decisions/Packaging sections; the finer code conventions dropped from old VI
  (Fatal-not-sys.exit, layer separation, doctests, stderr/stdout split, argv-not-
  shell) are implementation practice visible in the code and MAY be ported to
  CLAUDE.md as guidance if desired.

Amendments carried from 1.1.0:
  #1 Accuracy fix — the intro agent list wrongly named "opencode". Ground
     truth (Dockerfile Layer 3, lines 51-57) installs exactly three agent CLIs:
     Claude Code, Codex, pi-coding-agent. "opencode" removed; not installed.
  #2 Principle IV — added a stable identity contract MUST clause: the
     name/port/volume/XDG on-disk identifiers MUST NOT change the value
     computed for an existing name without a versioned migration path, and any
     change MUST be mirrored in the shell completions. Prevents silently
     orphaning running containers (unmanageable by their own tooling, identity
     shifted under a connected operator).
  #3 New Core Principle VI "Idiomatic Python on uv" — promoted from the
     "Platform & Interface Constraints" bullet of the same name; that bullet's
     substance was moved into Principle VI to avoid duplication; the platform-
     default and non-editable-PyPI-install facts are preserved in the new
     principle.

Principles (post-amendment):
  I.   Ephemerality                                          (redefined 2.0.0)
  II.  Least Privilege, Immutable Runtime                     (redefined 2.0.0)
  III. Least Exposure                                        (redefined 2.0.0)
  IV.  Deterministic Identity                                (redefined 2.0.0)
  V.   Durable Spec, Disposable Code                         (redefined 2.0.0)
  VI.  Least Dependencies                                    (redefined 2.0.0)

Sections:
  "Platform & Interface Constraints"     (kept — genuine scope decisions:
                                          editor-agnostic SSH+tmux, single operator)
  "Development Workflow & Quality Gates" (TRIMMED to constitutional policy —
                                          "verify before trust" (reconciled with
                                          the reframed Principle V) and "spec and
                                          docs track behavior". Concrete mechanics
                                          — CI suite composition, uv build,
                                          Trusted Publishing, commit-push cadence —
                                          relocated to CLAUDE.md.)

Templates reviewed:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate is
     generic ("Gates determined based on constitution file"); no hardcoded
     principle names, so it remains aligned. No edit required.
  ✅ .specify/templates/spec-template.md — no constitution references; aligned.
  ✅ .specify/templates/tasks-template.md — no constitution references; aligned.
  ✅ CLAUDE.md — hard constraints + decisions already encode these principles,
     including the uv/PyPI packaging facts now formalized in Principle VI.

Deferred TODOs: none.
-->

# agent-container Constitution

A containerized development environment that runs interactive and headless AI
coding agents (Claude Code, Codex, pi-coding-agent) inside disposable
containers, driven over SSH + tmux and managed by a single CLI. This
constitution encodes the non-negotiable rules that keep it disposable, minimal,
deterministic, spec-driven, and continuously delivered. It supersedes convenience
and habit.

## Core Principles

### I. Ephemerality

A container is disposable: it holds short-lived working copies and nothing
durable. No correctness may rest on its storage surviving — in-container
persistence is a convenience, never a contract. Durable state MUST live in an
authoritative store beyond the container, kept current in small, continuous
increments, so nothing of value is ever *only* local. Containers MUST be cheap
to create and destroy; the system actively favors the short-lived over the
long-lived.

**Rationale:** a container discardable at any instant without loss is resilient
by construction — recreation becomes a non-event, and host loss, corruption, and
drift cease to be failure modes.

### II. Least Privilege, Immutable Runtime

A container runs untrusted agent code. It MUST hold no more privilege than its
work requires and MUST NOT be able to escalate beyond it. Its runtime is fixed
at build and immutable thereafter — everything the container needs is provisioned
before it runs, and nothing reshapes the running system from within — so the
container is reproducible, its blast radius bounded, and its behavior independent
of who launched it, when, or on which host runtime.

**Rationale:** confining untrusted code to least privilege on a runtime it cannot
alter turns the container into a predictable, disposable unit — mutation,
escalation, and host-specific surprise cease to be failure modes.

### III. Least Exposure

The dual of least privilege: whatever the system reveals — data, secrets,
credentials, network surface, identity — MUST be exposed no more widely than its
use demands. Each thing is granted only to the actor that needs it and carried
only on channels others cannot observe; nothing rests where it need not, and
nothing is visible more broadly than required. Exposure is minimized in both
scope and reach, even against convenience.

**Rationale:** what is never exposed cannot be stolen, misused, or relied upon —
narrow exposure shrinks both the blast radius of a leak and the number of places
one can begin.

### IV. Deterministic Identity

Many containers coexist on one host as independent, non-colliding instances.
Everything that distinguishes one from another — name, addresses, storage, keys —
MUST derive deterministically from a single identifier, so any part of the system
can recompute it rather than store and risk desynchronizing it. That derivation
has exactly one authoritative definition; no consumer may reinvent it. And it is
a **stable contract**: the values computed for an existing container MUST NOT
change without a migration path, or a live container is silently orphaned — its
own tooling can no longer find it, and its identity shifts beneath a connected
operator.

**Rationale:** identity derived from one deterministic source makes parallelism
collision-free by construction and keeps every consumer — launcher, tooling,
orchestration — in lockstep without shared mutable state; stability protects the
containers already built on it.

### V. Durable Spec, Disposable Code

The specification is the artifact of record; code is a disposable rendering of it
— regenerated and replaced, never patched in place. What must endure lives in the
spec, so changing behavior means changing the spec and re-deriving the code.
Verification follows: it targets the spec's intended behavior, not the code's
internals — an inverted pyramid, weighted toward validation and acceptance checks
that survive regeneration, light on implementation-coupled tests that do not.

**Rationale:** code that is disposable, like the container that runs it, cannot
anchor durable confidence — tests bound to its internals die with each rewrite;
validating the spec's behavior outlives any single implementation.

### VI. Least Dependencies

The implementation relies on as little as it can — the fewest external packages,
the least coupling, nothing pulled in that the materials already at hand can do.
Reach first for what is present before adding a dependency; add nothing on
speculation. Every dependency MUST earn its place against doing without, because
each is borrowed complexity and borrowed risk — a surface that can break, drift,
or constrain. What you do not depend on, you never have to maintain, replace, or
trust.

**Rationale:** fewer dependencies mean code that is cheaper to understand,
regenerate, and replace (Principle V), and a smaller surface to break or
exploit — reliance is the quiet cost that compounds.

### VII. Continuous Deployment

`main` is always releasable, and releasing is automatic — never a manual act.
Every change that lands on `main` and alters the shipped software is published on
its own, with nothing human between merge and release. The version is semantic
and derived from the nature of the change: what users receive advances it and
ships; what they do not (docs, chores, internal churn that ships identically)
cuts no release. A change is not done until it is released.

**Rationale:** when every merge ships, `main` cannot be allowed to rot — it must
stay green and releasable at all times; the gap between "merged" and "in users'
hands" collapses to zero, and the version becomes a truthful, automatic record of
what changed.

### VIII. Defaults Belong at the Surface

A default is a decision made on the operator's behalf, so it MUST be made where
they can see it: at a flag, at the caller of a settings reader, at a record
constructor — never substituted for absent data deep inside an implementation. A
reader reports **absence**; the surface decides what absence means. Every default
MUST be **named**, so that it is greppable, auditable, and changeable in exactly
one place; an unnamed literal repeated across decision sites is a policy with no
owner. **Absent, defaulted, and declared-empty are three different facts** and
MUST stay distinguishable — a reader that collapses them destroys information
only the caller can interpret. Rendering absence for a human (`?`, `-`, `unknown`)
is not a default; that IS the surface.

**Rationale:** a default buried in an implementation is invisible to everything
downstream, and invisible decisions are the ones that turn out to be wrong at the
worst moment. This principle was ratified after a concrete failure: an accessor
answered `localhost` for a host record with no address, so a **remote** host was
classified as local, never queried, and never reported unreachable — an operator
would have read a complete-looking listing with a host silently missing. Nothing
was broken except a policy nobody could see. Naming and surfacing defaults also
makes them reviewable: what an operator can find, they can question.

## Platform & Interface Constraints

- **Editor-agnostic, SSH + tmux only.** The canonical attach path is
  `ssh user@host -t tmux attach`. No `.devcontainer/` configs, no VSCode-locked
  tooling, no design that assumes a particular editor client.
- **Single operator.** One operator (the user) is assumed; multi-user / multi-
  tenant access controls, and Kubernetes/cluster orchestration, are out of scope
  unless explicitly requested.

## Development Workflow & Quality Gates

- **Verify before trust.** No change is trusted until its intended behavior has
  been checked; verification is validation-first (Principle V) and cheap enough
  to run on every change.
- **Spec and docs track behavior.** The specification, README, `docs/`, and
  CLAUDE.md MUST be updated in the same change as any change to behavior, scope,
  the identity contract, or the security posture — stale spec or docs are defects.
- **The threat model tracks the feature.** `docs/threat-model.md` MUST be
  reconciled in the same change as any feature that alters a trust boundary, a
  credential path, or the network surface — recording which threats the change
  mitigates, which it leaves open, and which it newly introduces. Its maintenance
  table names every feature; a feature that lands without updating its row has not
  landed.

  **Rationale:** a security posture asserted once at design time and never
  revisited becomes a claim rather than a description, and the gap is invisible
  precisely because the document still reads as current. Recording what is *not*
  mitigated is the load-bearing half — an honest list of open risks is what makes
  the mitigated ones believable.

Concrete workflow mechanics (CI suite composition, `uv build`, Trusted Publishing
on `v*` tags, the commit-and-push cadence) live in CLAUDE.md.

## Governance

This constitution supersedes other practices when they conflict. Amendments MUST
be made by editing this file with a documented rationale, a semantic version
bump, and synchronized updates to any dependent templates and guidance
(`.specify/templates/*`, CLAUDE.md).

**Versioning policy (semantic):**
- **MAJOR** — removing or redefining a principle, or any backward-incompatible
  governance change.
- **MINOR** — adding a principle/section or materially expanding guidance.
- **PATCH** — clarifications, wording, and non-semantic refinements.

**Compliance:** every PR and review MUST verify compliance with these
principles; deviations MUST be justified in the change (see the plan template's
Constitution Check / Complexity Tracking). Unjustified complexity is rejected.
Runtime, day-to-day development guidance lives in **CLAUDE.md**, which MUST stay
consistent with this constitution.

**Version**: 2.3.0 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-08-21
