# Research: Agent-Operable CLI (Phase 0)

Decisions resolving the plan's unknowns. Every one extends an existing surface — this feature
adds an output mode and two commands, not a parallel system.

## R1 — A versioned envelope, emitted from one place

- **Decision**: Every `--json` payload is wrapped in a fixed envelope carrying a **schema
  version**, and is written by **one helper** (`emit_json(...)`) rather than by each command:

  ```json
  { "schema": "agent-container/v1", "ok": true, "data": { … } }
  { "schema": "agent-container/v1", "ok": false, "error": { … } }
  ```
- **Rationale**: FR-006 requires an inspectable version. A single emitter means 23 commands
  cannot drift into 23 payload shapes, and the version/`ok` discipline is applied in exactly
  one place. `ok` lets an agent branch without inspecting the exit code (it should check both).
- **Alternatives rejected**: a bare payload per command (no version — the thing FR-006
  forbids); a version *field inside* each command's data (repeats the problem per command).

## R2 — `--json` on 23 commands without 23 hand-rolled payloads

- **Decision**: Each command declares its own `--json` option (per FR-001 — no global flag),
  but the option only **sets a module-level output mode**; the command then calls the shared
  emitter with plain data. Human rendering (rich tables, prose) stays behind the
  `if json_mode` branch that already exists on the three current commands.
- **Rationale**: The flag must be per-command (clarified), but the *work* per command is one
  option declaration plus handing a dict to the emitter. Existing `do_host_ls`/`do_host_show`/
  `do_list` already have exactly this shape, so this is generalization, not invention.
- **Alternatives rejected**: a Typer callback setting a global (contradicts the clarified
  per-command choice); each command formatting its own JSON (guarantees drift).

## R3 — Structured errors vs the Feature 005 eval contract (the one real tension)

- **The tension**: Feature 005 established that on the **print/emit** surfaces
  (`host env`, `attach --print`) an error yields **empty stdout + non-zero**, precisely so
  `eval $(…)` executes nothing. FR-003/004/005 want a *structured failure* an agent can read.
  Emitting an error payload on stdout for those commands would break the eval contract.
- **Decision**: **Scope the two rules to the surfaces they protect.**
  - **Eval surfaces** (`host env`, `attach --print`/`--ssh-config`) keep 005's rule
    unchanged: an error produces **empty stdout**, non-zero. They do not take `--json`.
  - **`--json` mode**: the failure descriptor is written to **stdout** as the envelope with
    `"ok": false`, exit non-zero. It is structured output, not human text, so stdout is its
    correct home and the agent has one stream to read.
  - The human prose message continues to go to **stderr** in both cases, unchanged (FR-019).
- **Rationale**: The rules never actually conflict, because no eval surface takes `--json` —
  but that is only true by construction, so it must be stated and tested rather than assumed.
- **Alternatives rejected**: error JSON on stderr (splits the agent's reading across two
  streams for no benefit); applying empty-stdout-on-error to `--json` (leaves the agent with
  nothing to parse, defeating FR-003).

## R4 — Failure codes: one optional parameter, adopted incrementally

- **Decision**: `die(msg, *, code=..., entity=..., remedy=...)` — all optional. `Fatal` carries
  them; `cli()` renders them. Call sites without a code fall back to a generic
  `"unspecified"` code, so **nothing breaks on day one** and ~100 call sites are annotated
  progressively, highest-traffic first (the failures an agent actually hits: no host, port
  busy, credential missing, unreachable daemon, spec invalid).
- **Rationale**: One chokepoint (`cli()`) already catches every `Fatal`, so the rendering is a
  single-site change. Making the metadata optional avoids a 100-site big-bang edit that would
  be unreviewable and regression-prone.
- **Honest limitation**: SC-002 says *every defined failure class* has a code — so the
  **defined set** is what tasks must enumerate and cover; un-annotated call sites remain
  generic until adopted. That is a deliberate staging choice, not an oversight, and the
  generic fallback is itself a stable, documented code.
- **Alternatives rejected**: an exception subclass per failure class (dozens of classes in a
  single-file tool); parsing codes out of message text (exactly the brittleness FR-003 exists
  to remove).

## R5 — `context` is a serializer over the Feature 007 engine

- **Decision**: `context` builds the existing `EnvSnapshot` via `build_snapshot(...)` and
  serializes it — stages with their tri-state status, the active target, containers, orphan
  volumes, detected problems, plus `recommend_next_step()` as the suggested next step. It adds
  **project conventions** (Feature 006 discovery: which `.agent-container/` governs, which env
  file applies) and **credential locators** (Feature 008 sources, by reference).
- **Rationale**: FR-009 asks for exactly what 007 already computes, and that engine is
  **pure** — so the serializer is unit-testable from a constructed snapshot with no daemon.
  Reusing it also guarantees `context` and the wizard can never disagree about state.
- **Bounded probing**: inherits 007's single-active-target scope (FR-017 there), so `context`
  does not fan out to every registered host.
- **Never-fails discipline** (FR-010): an unreachable host is a *described state* inside a
  successful payload, not an error — 007's snapshot already models `unusable` distinctly from
  `absent`, which maps directly.
- **Alternatives rejected**: a fresh assessment path (guarantees divergence from the wizard);
  aggregating N command outputs (slow, and duplicates the state model).

## R6 — The skill template is an embedded constant, not a packaged data file

- **Decision**: The `SKILL.md` body lives as a **string constant in the script**, rendered at
  install time.
- **Rationale**: The tool must work as a standalone `uv run --script bin/agent-container`.
  Completions ship as package data via `force-include`, but that path only exists for a
  *wheel* install — a script-mode run has no package data. An embedded constant works in both
  modes, which is the same reason `REPO_ROOT` resolution is defensive.
- **Content requirement**: the template must satisfy **FR-012c** — instruct the agent to pass
  `--json` on every invocation, and **every example inside it carries the flag**. This is
  testable by asserting no example line invokes the tool without `--json`.
- **Alternatives rejected**: a packaged data file (breaks script mode); fetching the template
  (network dependency, and unacceptable for an offline-capable CLI).

## R7 — Drift detection that cannot clobber operator edits

- **Decision**: The generated `SKILL.md` frontmatter carries a tool-owned marker — the
  generator identity and a **checksum of the generated body**. On install/update:
  - file absent → write, report;
  - present, marker matches a body we generated → **idempotent no-op** or clean version
    update;
  - present, **marker missing or checksum mismatch** → **refuse**, report the difference, and
    require explicit intent (FR-014).
  Removal deletes only what the tool wrote, keyed by that marker (FR-015).
- **Rationale**: A checksum in the file itself needs no sidecar (which would be residue,
  against FR-015) and detects both hand edits and a stale version. The Agent Skills standard
  requires `name`/`description` at minimum and tolerates additional frontmatter keys, so a
  namespaced marker key is standard-conformant.
- **Alternatives rejected**: a sidecar state file (residue, and drifts from the artifact);
  mtime comparison (unreliable across checkouts and copies); overwriting always (violates
  FR-014 outright).

## R8 — Machine-readable help by introspecting the command tree

- **Decision**: Help in machine-readable form is produced by walking the existing Typer
  command tree (names, parameters, help text) and emitting it in the envelope — not by
  maintaining a second, hand-written description of the CLI.
- **Rationale**: A hand-maintained catalogue drifts from the real commands the moment one is
  added; introspection cannot. Satisfies FR-008 without a parallel source of truth.
- **Alternatives rejected**: scraping formatted `--help` text (the brittleness FR-008 exists
  to eliminate); a static hand-written manifest (drift).
