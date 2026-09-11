<!--
SYNC IMPACT REPORT
==================
Version change: 2.5.0 → 2.6.0   (MINOR)

- **Principle X. Surgical Change — ADDED.** Governs the SCOPE OF A DIFF: every changed
  line traces to the request that prompted it; adjacent code, comments and formatting
  are left as found; pre-existing dead code is reported rather than removed; a change
  cleans up only the orphans it created itself.
- The principle is written about the diff, NOT about regeneration, because Principle V
  makes code a disposable rendering that a re-derivation may legitimately replace
  wholesale. What it forbids is the unrequested edit riding along with a requested one.
- **The load-bearing-comments invariant is now written down.** It was real practice and
  recorded nowhere: the comments in `bin/agent-container` and `bin/tests/*` are the only
  account of failures found by MEASUREMENT, so brevity is not an improvement to them.
- Adopted after installing the Karpathy coding guidelines as a plugin skill. Only the
  surgical-change rule was additive: simplicity and speculative generality are already
  Principle VI plus Governance ("Unjustified complexity is rejected"), and success
  criteria are already "Verify before trust" plus Principle V. Those are REFERENCED
  here, deliberately not restated — a duplicated rule drifts from its original.
  ✅ .specify/templates/plan-template.md — Constitution Check is generic ("[Gates
     determined based on constitution file]"); no principle enumeration to update.
  ✅ .specify/templates/spec-template.md, tasks-template.md, checklist-template.md —
     no constitution references; aligned.
  ✅ CLAUDE.md — pointer added under "Conventions for future work", paid for by pruning
     a parenthetical that duplicated the `_acc_base()` docstring; measured with a
     tokenizer to stay under the file's own 2000-token cap.

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

Principle IX is this principle applied to one recurring question — *how* a secret
reaches a container — because "no more widely than its use demands" was not specific
enough to rule out a mechanism that looked like a narrowing and was not.

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

### IX. Secrets Travel to the Container, Not Through Its Description

A container's deployment description — the compose model, its generated file, and
anything else the tool writes to plan a deployment — MUST NOT carry secret material.
Secrets are DELIVERED to a container that is already running, over SSH TO THAT
CONTAINER — its own sshd, which therefore runs in every mode. **Not over the
container runtime's channel**, even when that channel happens to be SSH: the
runtime's transport is whatever the operator configured their context to be, so the
tool could only CHECK it, never provide it. A `tcp://` context would carry the
plaintext in the clear. Over the container's own sshd the transport is SSH by
construction and the daemon never sees the value at all.

Both directions are established WITHOUT the tool holding anything it minted. The
container is verified by the host key it generated itself, whose public half the tool
captured and pinned. The tool is authenticated by an operator-DECLARED identity that
the environment's key collection authorises — the tool MUST NOT generate a private
key for this, because a tool-minted key is a standing credential granting entry to
every environment it deploys, which is a worse exposure than the delivery gap it
would close. An undeclared identity is a refusal, never a fallback to a weaker
channel. Public material (authorised keys, host fingerprints,
non-secret configuration) MAY ride the deployment description, because it is public.

Concretely, a secret MUST NOT be: inlined into the deployment description; written to
a staging file that the description references; or placed on argv. It MUST be pushed to
the running container and land only where that container reads it.

Once delivered, a secret MAY and generally MUST **persist**, because a container that
lost its credentials on restart could not survive a reboot, a daemon restart, or a
restart policy — nothing would be present to re-deliver them. Persistence is
conditional on RECONCILIATION and the two MUST NOT be separated: whatever holds a
secret MUST be removed when the operator stops declaring it, or the declaration stops
being the authority and the system can hold a credential its configuration says is
gone. Storage MUST therefore be per-secret and named, so that one can be withdrawn
without disturbing the others — and the tool MUST expose that withdrawal itself, since
a runtime cannot remove storage a running container holds.

**Rationale:** ratified after a wrong turn that this constitution had not ruled out.
A compose `configs: {file:}` entry is materialised as a bind and resolved on the
DAEMON side, so it cannot reach a daemon that does not share the operator's
filesystem — measured, not assumed. The obvious repair was to inline the material
instead, which fixes reachability by writing every credential into a file that
describes the deployment, persists as its record, is parsed by several code paths,
and is read long after the credential was needed. It trades a functional bug for a
durable exposure, and it was *nearly* shipped because each step looked like an
improvement on the one before.

The error was treating delivery as a property of the DESCRIPTION. A deployment
description is a plan: it is written before anything exists, kept afterwards, and
read by whatever wants to know what was deployed. Nothing with that lifetime should
hold a secret. The container, by contrast, is a running peer with its own identity
and its own authenticated channel — reachable without the daemon seeing any local
file, which is what made the original mechanism fail. Delivering over that channel
is both the more secure answer and the more portable one, and the two are not in
tension here: the same property that keeps the secret out of the plan is what lets it
reach a daemon that shares nothing.

### X. Surgical Change

A change is scoped by its request. When code is edited in place, every changed line
MUST trace to the request that prompted it. Adjacent code, comments, formatting and
naming MUST be left as found: no opportunistic reformatting, no refactoring of what is
not broken, no restyling toward a convention the file does not already hold. Existing
style wins over the author's preference, including when the author would have chosen
otherwise. Pre-existing dead code MUST be reported, not deleted — its removal is a
change of its own and belongs to a request that asks for it. The orphans a change
creates itself — imports, variables and helpers it has just made unused — MUST be
removed by that same change, because those are its own mess.

This governs the DIFF, not regeneration. Principle V makes code a disposable rendering
of the spec, and a re-derivation MAY legitimately replace a whole module; what is
forbidden is the unrequested edit that rides along with a requested one.

Inline comments in this repository are LOAD-BEARING HISTORY, not commentary. They record
failures found by MEASUREMENT and the reasoning that produced the current shape: why a
health probe reads a record back instead of trusting a 200, why a process scan must
exclude its own shell, which of two addresses a two-address bug was measured at. They
MUST NOT be shortened, summarised, or removed for brevity or simplicity. A comment
changes only when the behaviour it describes changes, and then it changes to describe
the new behaviour — never to say less.

Assumptions MUST be surfaced rather than silently chosen: where a request admits more
than one reading, the reading taken is named; where a simpler approach exists, it is
offered; where something is genuinely unclear, it is asked before it is guessed.
Simplicity and speculative generality are governed by Principle VI and by Governance's
rejection of unjustified complexity; success criteria are governed by "Verify before
trust" under Development Workflow & Quality Gates. This principle references them and
does not restate them.

**Rationale:** an unrequested edit is unreviewable. A reviewer reading a diff cannot
distinguish the change that was asked for from the one that was volunteered, and the
volunteered one arrives with no request, no rationale and no test — so it is trusted
by default precisely because nobody knew to doubt it. Scope discipline is what keeps a
diff readable as an argument for itself.

The comments clause is the same lesson pointed at this codebase's actual record. The
fix for an ingest health probe that reported a discarding stack as healthy is four
lines of shell beneath sixteen lines explaining which process-ID ordering made the
break take under one container runtime and silently miss under the other. Delete the
explanation as clutter and the next reader re-derives the defect from scratch, or
reintroduces it — the code is short, but the reason it is THAT code is not recoverable
from reading it.

What is mechanically checkable about simplicity is already ENFORCED and needs no
principle: `scripts/quality-gate.sh` runs a complexity ceiling (`xenon --max-absolute
B --max-modules A --max-average A`), dead-code detection (`vulture`), simplification
(`refurb`) and lint (`ruff`) on every change, in the same script CI runs. What remains
for a principle is exactly the part tooling cannot check — whether a line that passes
every gate should have been written at all.

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

**Version**: 2.6.0 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-09-11
