<!--
SYNC IMPACT REPORT
==================
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
     change MUST be mirrored in the shell completions. Prevents orphaning live
     containers/volumes, which would silently violate Principle I.
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
  "Platform & Interface Constraints"     (Idiomatic-Python bullet promoted out)
  "Development Workflow & Quality Gates"

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
constitution encodes the non-negotiable rules that keep that system safe,
reproducible, and parallel by construction. It supersedes convenience and habit.

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
change without a migration path, or a live container is silently orphaned
(violating Principle I).

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

## Platform & Interface Constraints

- **Editor-agnostic, SSH + tmux only.** The canonical attach path is
  `ssh user@host -t tmux attach`. No `.devcontainer/` configs, no VSCode-locked
  tooling, no design that assumes a particular editor client.
- **Single operator.** One operator (the user) is assumed; multi-user / multi-
  tenant access controls, and Kubernetes/cluster orchestration, are out of scope
  unless explicitly requested.

## Development Workflow & Quality Gates

- **Green before commit.** The full suite (hermetic pytest + shell suites +
  self-test) MUST pass, and non-trivial runtime changes MUST be exercised
  against a real build, before a change is committed.
- **CI is the gate.** `ci.yml` runs the pytest and shell suites plus `uv build`
  on every push/PR; releases go to PyPI via Trusted Publishing (OIDC, no stored
  secrets) on `v*` tags, re-running the suite first.
- **Docs track code.** README, `docs/`, and CLAUDE.md MUST be updated in the same
  change when behavior, setup, the on-disk contract, or the security posture
  changes. Stale docs are treated as defects.
- **Commit and push.** Consistent with Principle I, work is committed and pushed;
  the commit-and-push discipline is a property of agent configuration, not
  enforced by hooks alone.

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

**Version**: 2.0.0 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-07-08
