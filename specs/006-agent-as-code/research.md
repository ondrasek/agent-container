# Research: Agent-as-Code (Feature 006)

Decisions resolving the plan's unknowns. This feature is **additive** and reuses
001 (host registry/driver/provisioner), 002 (lifecycle), 003 (credential injection),
004 (execution/workspace/clone-on-start), 005 (emit seam) — it orchestrates them
from a declarative directory. All four `/speckit-clarify` decisions and the FR-020
spec-integrity decision are folded in.

**Ground truth (verified in `bin/agent-container`):** `tomllib` is already imported
for reading `pyproject.toml`; the tool has **no YAML reader** (compose is emitted as
JSON, a YAML subset, precisely to avoid a YAML dependency). `do_up`/`compose_up_exec`,
the host registry (`load_registry`/`registry_hosts`), the Hetzner provisioner, and
the deterministic identity (`container_name`/`volume_name`/`port_for_name`) all
exist and are the internals the reconcile layer drives.

---

## R1 — Spec format: YAML via PyYAML (the recorded Constitution-VI exception)

**Decision** (operator's choice): the `.agent-container/` declarative files are
**YAML**, parsed with **PyYAML** using **`yaml.safe_load` only** (never `yaml.load`,
which can construct arbitrary objects — eval-safety). PyYAML is **the one new
third-party dependency**, added to the PEP 723 inline metadata, `pyproject.toml`,
and the test `--with` pins. This is a deliberate Constitution-VI deviation recorded
in the plan's Complexity Tracking.

**Rationale**: YAML is the format operators expect for "as-code" declarative config
(Compose/k8s/Terraform-adjacent) and is far more comfortable than TOML for the
deeply-nested, list-heavy environment schema (multiple environments, nested
host/container/credential blocks). The operator chose it explicitly. PyYAML is a
single, mature, ubiquitous parser that earns its place; the schema/validator sits
**above** the loader, so the parser is swappable if ever needed.

**Alternatives rejected**: TOML via stdlib `tomllib` (dependency-free and already
in-project, but awkward for the nested/list schema and not the expected format — the
operator chose YAML, so the one dep is justified); JSON (valid YAML but hostile to
hand-author); a bespoke parser (reinvents a wheel, worse than a vetted dep).

**Security note**: `yaml.safe_load` is mandatory — the spec is operator-authored but
may be committed in a repo, so the loader must never construct arbitrary Python
objects. Asserted in tests.

**Validation**: unit — a valid YAML spec parses to the model; an invalid one reports
the offending file + field with no partial change; `yaml.load` (unsafe) is never
used.

---

## R2 — Discovery: upward walk to the `.agent-container/` marker

**Decision** (clarify Q2): `find_project_root()` walks **upward** from the working
directory to the nearest ancestor containing a `.agent-container/` directory,
returns it, and every operation **reports** the selected root (FR-001/019). No
`.agent-container/` anywhere up the tree → the declarative model is inert and the
tool behaves exactly as today (FR-004). More than one candidate is impossible by
construction (the *nearest* ancestor wins, deterministically).

**Rationale**: a marker directory is git-independent, unambiguous, and mirrors the
`.git`/`.terraform` discovery operators already know; the nearest-ancestor rule is
deterministic regardless of the working subdirectory.

**Alternatives rejected**: a bare marker *file* (Clarifications considered — a dir
namespaces multiple spec files and the RO-mount target cleanly); the git root
(ties discovery to git; the feature must work without git).

**Validation**: unit — run from nested subdirs resolves the same root; absent →
inert/today's behavior; the chosen root is reported.

---

## R3 — Reconcile model: plan → apply/status/destroy over existing internals

**Decision**: the declarative layer is an **orchestrator** over the imperative
internals, not a second implementation. Flow: **discover → parse+validate →
compute a plan** (per declared resource: absent / matching / drifted vs live) →
**preview + confirm** (honoring the 004 headless/non-interactive convention) →
**apply** by calling the existing `do_up`/`compose_up_exec` (and host
registry/provisioner for US4). `apply` is **idempotent** — a matching plan makes no
change. `status`/`diff` prints the plan without mutating. `destroy` removes exactly
the owned resources (R4). Partial failure reports precisely what changed (FR-010).

**Rationale**: reusing the proven internals keeps one implementation (Constitution
V/VI) and makes the declarative model a thin, testable computation (plan) plus
existing effects.

**Alternatives rejected**: a parallel deploy path (duplicates 001–004, drifts);
a one-shot generator that emits imperative commands (loses idempotence/drift — the
"as code" model requires reconcile, per the spec assumption).

**Validation**: unit — `compute_plan` classifies absent/matching/drifted from a
declared spec + a stubbed live view; acceptance — apply reaches the declared state
and a second apply is a no-op.

---

## R4 — Ownership & drift: derived from the deterministic identity, no state file

**Decision** (clarify Q3): a declared resource's **name** maps to the tool's
existing **deterministic identity** (`container_name(name)`, the volume set,
`port_for_name`, the host record) — "owned" = a resource with that identity exists;
drift = the declared config vs the live container's config; `destroy` removes only
those identities and **nothing else** (FR-009/SC-007). **No Terraform-style
state/lock file** is written.

**Rationale**: Constitution IV already makes identity the single deterministic
source; deriving ownership from it means nothing new to persist, desync, or leak,
and teardown is provably scoped. It also fits Ephemerality — the directory + the
running containers are the only state.

**Alternatives rejected**: a state file recording created resources (precise across
renames, but adds tracked state that can desync/leak and something new to store — a
poor fit for a project that avoids persistence); label-scanning only (weaker than
the deterministic name→identity map already in hand).

**Validation**: unit — declared names map to the expected identities; `destroy`
targets only owned identities; a same-named unrelated container is untouched.

---

## R5 — Credential resolution: references + in-memory decrypt command

**Decision** (clarify Q1): a credential is declared as a **reference to a source**,
resolved at apply and injected via Feature 003's runtime channels (never disk/
log/registry/argv, FR-013/014):
- **env** — an environment-variable name;
- **file** — an external file *outside* the tracked directory;
- **keychain** — an OS secret store (macOS `security find-generic-password -w …`;
  Linux `secret-tool lookup …`) — per-OS command, resolved in memory;
- **encrypted-at-rest** — a committable encrypted file **plus an operator decrypt
  command** (`sops -d <file>`, `age -d …`) the tool runs, reading plaintext **in
  memory only**; the tool bundles no crypto (Constitution VI).
A missing/unavailable source **fails before any change** and names it (FR-016). A
**git-tracked plaintext** secret within the project (a declared `file`/inline value
that is tracked and not gitignored) is **refused** with remediation (ignore /
externalize / encrypt), and the detection boundary is documented (FR-015).

**Rationale**: references keep secrets out of the (committable) directory; the
decrypt-command reuses whatever the operator already trusts and adds no dependency;
in-memory-only resolution + the 003 ephemeral channels satisfy Least Exposure.

**Alternatives rejected**: bundling age/SOPS (a new dep + format lock-in); storing
resolved secrets in the registry or a state file (violates FR-014); inline secrets
in the spec (the leak the feature exists to prevent).

**Validation**: unit — each source resolves (stubbed) to the inject channel; a
missing source dies naming it; a git-tracked plaintext is refused; the decrypt
command's output never touches disk (asserted).

---

## R6 — Spec integrity: the governing spec is immutable from inside the container

**Decision** (FR-020, operator-raised): an untrusted agent whose workspace *is* a
repo carrying `.agent-container/` MUST NOT be able to modify the spec that governs
it. Two guarantees:
1. **Host-side-only read** — the tool reads the spec **only** from the operator's
   host-side `.agent-container/`, never from a container's copy. A spec change is a
   host-side git edit the operator reviews; an agent's `git push` cannot re-govern.
2. **Read-only delivery via compose `configs`** (defense-in-depth) — when a deployed
   container's `/workspace` carries `.agent-container/`, the tool delivers the
   declared spec files **read-only** through the **Feature 003 `injected_configs`
   channel**: each file rides as a compose **`config`** targeting
   `/workspace/.agent-container/<rel>`. Compose configs mount **read-only** and —
   critically — **work over a remote docker context**, which a host **bind does
   not** (the exact reason 001/003 chose configs over binds for injected material).
   Kernel-enforced for every uid; the rootless agent cannot escalate past it. Before
   deploy the tool **verifies** every declared file is delivered via a read-only
   channel (no writable `/workspace` mount exposes it) and **refuses** otherwise.

**Rationale**: guarantee (1) is load-bearing — since the tool never reads the
container copy, even a rogue in-container file is inert. Guarantee (2) makes the
agent's view consistent and tamper-resistant using the **already-proven,
remote-safe** injection channel rather than a bind that would silently fail on a
remote host. Together they extend Constitution II (immutable runtime) and IV
(identity is the operator's) to the desired-state itself — deterministic, not
heuristic — closing the self-governance / supply-chain hole the operator flagged.

**Alternatives rejected**: a **host bind** `…:/workspace/.agent-container:ro` — the
obvious first idea, but a local bind **resolves empty / fails over a remote context**
(001/003 codified compose-configs for exactly this); chowning to root (the runtime
is rootless — no root, and it would not survive a fresh clone); trusting the
container copy and diffing on push (reactive, not deterministic; a race window).

**Validation**: unit — the compose model delivers each `.agent-container/` file as a
read-only `config` (never a bind), and the verify step refuses a writable-spec
deploy; acceptance — a write to `/workspace/.agent-container` inside the container
**fails**, including over a remote context.

---

## R7 — CLI surface + precedence

**Decision**: net-new declarative verbs, active only when a `.agent-container/` root
is discovered (else today's behavior, FR-004): **`apply`** (converge; preview +
confirm), **`plan`**/**`status`** (print the plan/diff, no mutation), **`destroy`**
(scoped teardown of owned resources). Distinct from the imperative `up`/`down` so
the two models never collide. **Precedence** (clarify Q4): inside a spec directory
the spec **wins for its scope**, overriding a same-named global-registry host, and
the override is **reported** (FR-018) — never a silent merge. Every operation
reports the **root + host** selected (FR-019).

**Rationale**: separate verbs keep the declarative and imperative models legible;
spec-wins matches "the directory is the source of truth for that invocation."

**Alternatives rejected**: overloading `up`/`down` to auto-detect a project
(ambiguous, surprising); a `project` subcommand group (workable, but top-level
verbs read better for the primary workflow — revisit if the surface grows).

**Validation**: unit — the verbs activate on discovery and no-op-to-today when
absent; a spec-vs-registry host conflict resolves spec-wins and reports it;
root+host are reported for every op.
