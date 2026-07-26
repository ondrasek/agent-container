# Phase 0 Research: opencode as a Supported Agent

**Feature**: 010-opencode-agent | **Date**: 2026-07-26

All facts below were checked against **opencode's own documentation** (`opencode.ai/docs`),
not inferred from third-party summaries or from how the other three agents behave.

---

## R1 (CRITICAL) — The recorded clarification is factually wrong

The Session 2026-07-26 clarification records, as a *verified* fact:

> Its configuration lives in **one directory**, and that directory is **overridable by an
> environment variable**.

**Both halves are false.** opencode splits its state across two XDG locations:

| What | Path | Persists what |
|---|---|---|
| Config | `~/.config/opencode/` | `opencode.json`, `tui.json`, `agents/`, `commands/`, `modes/`, `plugins/`, `skills/`, `themes/` |
| Data | `~/.local/share/opencode/auth.json` | credentials written by `opencode auth login` |

And `OPENCODE_CONFIG_DIR` does **not** relocate the config — it adds an *additional search
directory* for agents/commands/modes/plugins. Only `OPENCODE_CONFIG` relocates, and it names a
**single config file**, not a directory.

**Consequence**: mounting one volume at `~/.config/opencode` — the literal design the
clarification approved — would persist config but **silently lose the interactive-login
credential** on every recreate. That breaks US1 acceptance scenario 3, US2 acceptance scenario 3,
and SC-002, and it would pass any test that only checks `opencode.json`.

**This requires spec amendments before `/speckit-tasks`** — see "Required spec amendments" below.

**Sources**: [Config | OpenCode](https://opencode.ai/docs/config/) ·
[CLI | OpenCode](https://opencode.ai/docs/cli/)

---

## R2 — Persistence design: two volumes (per-container set 7 → 9)

**Decision**: give opencode **two** named volumes, both mounted at their native paths:

| Volume | Mount |
|---|---|
| `agent-container-<name>-opencode` | `/home/dev/.config/opencode` |
| `agent-container-<name>-opencode-data` | `/home/dev/.local/share/opencode` |

**Rationale**: zero cleverness in the load-bearing persistence path. Both paths stay native, so
the clarification's actual *intent* — "anything an operator reads in opencode's documentation
works verbatim inside the container" — is fully honored. The asymmetry (one agent, two volumes)
is a property of **opencode**, which genuinely splits config from data per XDG, not an
inconsistency in our design. Feature 011 is already chartered to revisit layout for all four
agents together.

**Alternatives considered and rejected**:

- **One volume at `~/.local/share/opencode` + symlink `~/.config/opencode` into it.** Keeps the
  set at 8, but puts a symlink in the path every config read and every atomic
  write-temp-then-rename crosses. Cleverness in the one place that must not surprise us.
- **One volume + `OPENCODE_CONFIG` pointing into it.** Contradicts the clarification's explicit
  "no environment override is needed", and `OPENCODE_CONFIG` names a *file*, so `agents/`,
  `skills/`, and `themes/` would still not persist.
- **One volume at `~/.config/opencode` only** (what the clarification literally approved).
  Rejected: loses credentials — see R1.

**Impact on FR-007**: the requirement is "every place that states the number or names of those
volumes MUST be updated consistently". That holds with nine; only the spec's own *narrative*
"seven → eight" needs correcting.

---

## R3 — Mount-point parents must exist in the image, owned by `dev`

The container is rootless with no runtime `sudo`. When a named volume is mounted at a path whose
**parent does not exist in the image**, the runtime creates the parent, and ownership is not
guaranteed to be `dev` — an unwritable agent directory that fails only at runtime.

`~/.config` already exists in the image (it is the parent of the `tmux` volume mount), which is
the precedent. `~/.local/share` does **not**.

**Decision**: the Dockerfile MUST create `~/.config/opencode` and `~/.local/share/opencode`
owned by `dev`, in the same layer that creates the other agents' directories.

---

## R4 — Install mechanism (FR-003)

**Decision**: `npm install -g opencode-ai` in the existing Dockerfile npm layer, alongside the
other agent CLIs. No new install machinery; nothing fetched at runtime (Constitution II).

---

## R5 — Headless invocation (FR-005)

**Decision**: `opencode run "<task>"` — the documented non-interactive form ("useful for
scripting, automation … without launching the full TUI"). Dispatch becomes
`opencode) exec opencode run "${t}" ;;`, matching `claude -p` / `codex exec` / `pi -p`.

**NOT VERIFIED — must be proven, not assumed**: opencode's docs **do not state** whether
`opencode run` exits non-zero on failure. FR-005 requires the container's exit status to reflect
the agent's outcome, so this is load-bearing. It is resolved by an **acceptance-tier probe
against the real image**, not by a documentation claim. If `opencode run` turns out to always
exit 0, FR-005 is unsatisfiable as written and the spec must say so rather than the tests
pretending otherwise.

---

## R6 — Credential delivery (US2, FR-010/FR-011)

opencode's credential precedence is: **config file `options.apiKey`** → **environment variables**
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …) → **auth store** (`~/.local/share/opencode/auth.json`).

**Decision**: deliver an injected key via **the process environment only**, exported by the
entrypoint from Feature 003's ephemeral injected file (`INJECT_APIKEY_DIR`, under
`/run/agent-container/…`). Never on argv, never written to a volume.

This makes opencode's injection the **simplest of the four** — codex and pi need an ephemeral
`$HOME`-style redirect (`CODEX_HOME`/`PI_CODING_AGENT_DIR`) specifically to stop `auth.json` from
landing on their volume; opencode needs no redirect because an env-delivered key is never written
to the auth store at all. Strictly less exposure, not more.

The on-volume `~/.local/share/opencode/auth.json` therefore remains **operator-interactive-login
only**, exactly matching the rule already established for the other three agents.

---

## R7 — Single-sourcing the agent list (FR-002)

The supported-agent set is currently encoded independently in **four** places across **three
languages**: `AGENTS` in `bin/agent-container` (Python), the `case` dispatch and error text in
`entrypoint.sh` (shell), the install and directory layers in the `Dockerfile`, and the docs.

**Decision**: `AGENTS` in `bin/agent-container` is the **canonical list**; agreement with
`entrypoint.sh` and the `Dockerfile` is enforced by a **hermetic test that parses those files**
and asserts the sets match.

This is **detection, not prevention** — and that is a deliberate, stated limit. True
single-sourcing across Python + shell + Dockerfile would require build-time code generation, a
new dependency and a new failure mode, for a list that changes roughly once per year
(Constitution VI). A parsing test converts "the four lists silently drifted" from a production
surprise into a red gate, which is the outcome FR-002 actually exists to buy.

---

## R8 — FR-013 is net-new, not an update

The shell completions **do not offer agent names at all today** — not three, not any. FR-013
("completions MUST offer all four agent names") therefore requires *adding* value completion for
`--agent`, not extending an existing list. Small, but it is new scope rather than a one-line edit,
and it is the kind of item that gets mis-sized because the requirement is phrased as a change.

---

## R9 — FR-009 (pre-upgrade teardown) is likely already satisfied — prove it anyway

`down`/`wipe` route through `compose down --volumes`, which reconciles by project label rather
than by an enumerated list, and the explicit volume paths already tolerate absence because the
workspace volume became conditional in Feature 004. So no new tolerance logic is expected.

**But FR-009 is the feature's stated headline risk**, and "expected to already work" is exactly
the reasoning that lets a regression through. It gets a dedicated test that creates an
environment on the **old** volume set and tears it down on the **new** code.

One concrete stale artifact exists and must be fixed: a comment in `bin/agent-container` reads
"`--volumes` also drops the **seven** named volumes".

---

## Required spec amendments (blocking `/speckit-tasks`)

1. **Clarifications § Session 2026-07-26** — replace the "configuration lives in one directory,
   overridable by an environment variable" claim with the R1 finding (config and auth are split;
   `OPENCODE_CONFIG_DIR` is a search path, not a relocation).
2. **Overview** and **Assumptions** — "seven to eight" / "seven → eight" become **seven → nine**,
   with the two-volume rationale from R2.
3. **FR-006** — state that *both* opencode's native config directory and its native data
   directory persist, so the credential written by an interactive login survives recreation.
4. **FR-005** — note that the exit-status guarantee is contingent on `opencode run` propagating a
   non-zero status, verified at the acceptance tier (R5).
