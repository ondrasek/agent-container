# Phase 0 Research: `doctor` — Preflight Validation

Every decision below was checked against the code as it exists today, not against the spec's
assumptions about it. Two of them contradict what a plain reading of the spec would produce.

---

## R1 — Read-only is a CONSTRAINT ON REUSE, and it is the hardest part of this feature

**Decision**: `doctor` composes its own read-only readers. It MUST NOT call the deploy path's
setup helpers, however convenient they look.

**Finding**: the functions a deploy calls first are exactly the ones that mutate.

| Helper | What it does | Verdict for `doctor` |
|---|---|---|
| `migrate_flat_state()` | relocates `STATE_DIR/<name>.*` into `STATE_DIR/local/` | **forbidden** — moves files |
| `drain_host_records()` | starts a throwaway container per environment to ingest records | **forbidden** — creates containers |
| `record_inventory_creation()` | writes a durable inventory entry | **forbidden** — writes |
| `ensure_tunnel()` | starts an SSH socket-forward for a provisioned host | **see R2** |
| `resolve_deploy_host()`, `read_state_port()`, `pinned_host_key()` | pure reads | permitted |

`migrate_flat_state()` is the trap. It is the first line of `do_up`, `do_redeploy` and `do_list`,
it is idempotent, and it is *documented as safe to call repeatedly* — so it reads as harmless and
is not. It relocates files on disk, which SC-002 measures directly.

**Rationale**: FR-002 says "no file … created, modified or removed", and SC-002 verifies it by
diffing filesystem, container, volume and registry state around the run. A single reused helper
defeats the whole feature, and it defeats it *silently* — everything still reports correctly.

**Alternative rejected**: a "dry-run flag" threaded through the existing helpers. That puts the
read-only guarantee in N places where each new caller can forget it, and the guarantee is the
feature. Composition from pure readers keeps it structural.

**Consequence for tasks**: a test that runs `doctor` against a project and asserts a byte-identical
state tree is worth more than any number of per-check tests, and it must exist before the checks
are built out — otherwise it is written to pass whatever was implemented.

---

## R2 — An SSH tunnel is permitted; a container is not

**Decision**: `doctor` MAY call `ensure_tunnel()` for a provisioned host. It MUST NOT start,
create or remove any container, volume or image.

**Rationale**: without the socket-forward, every provisioned host reads *unreachable* — a false
negative on the exact check FR-012 asks for, and worse than not checking at all. The forward
creates no file, container, volume, image or registry entry (the closed list FR-002 names), it is
scoped to the process, and it disappears when the command exits.

**This is a judgment call and it is recorded as one.** A stricter reading of "changes nothing"
would forbid spawning any process. The line drawn here is: **nothing that outlives the command**.
If the operator disagrees, the fallback is to report provisioned hosts as *unknown* with a remedy
naming the manual check — which is honest, just much less useful.

---

## R3 — Credential *resolvability* cannot mean *resolution*

**Decision**: `doctor` never calls `resolve_credential_value()`. It checks what can be checked
without side effects, and reports the rest as **unknown**.

| Source | Checkable without prompting | Reported |
|---|---|---|
| `env` | is the variable set | pass / fail |
| `file` | does the path exist; is it git-tracked plaintext (008's refusal) | pass / fail |
| `keychain`, `onepassword`, `bitwarden`, `command` | is the resolver binary on `PATH` (`op`, `bw`, `argv[0]`) | fail if absent, else **unknown** |

**Rationale**: for manager sources, resolving *is* the prompt. `resolve_credential_value()` runs
`op read` / `bw get` / the operator's own argv, and a 1Password item behind approval will raise a
system prompt — FR-009 forbids exactly that as a side effect of asking a question. It would also
pull the secret into memory for no reason, against FR-010 and Constitution III.

The binary-on-PATH check is not a consolation prize: "the tool that would resolve this credential
is not installed" is a genuine blocking finding, it is free, and it is the most common real
failure on a new machine — which is US3's whole scenario.

**Alternative rejected**: resolving with a non-interactive flag (`op --no-prompt` and friends).
It varies per manager, `command` sources are arbitrary argv with no such contract, and a flag that
*usually* suppresses prompting is not a guarantee — FR-009 is absolute.

**This is why FR-006 exists.** *Unknown* here is the correct answer, not a gap.

---

## R4 — The exit-code range in FR-011 collides with a contract that shipped after the spec

**Decision**: `doctor` returns **exactly 0, 1 or 2**. Never 3 or above.

**Finding**: FR-011 (written 2026-07-29) says "**2 or greater** when `doctor` itself could not
run". Feature 019 has since shipped a tool-wide table, documented in `--help` and pinned by a
test that builds the help text from the constants:

```
0 success · 1 failure · 2 refused (usage error, or a destructive action declined
without -y on a non-TTY) · 3 pending registration
```

`3` is taken and means something a caller may branch on. A `doctor` returning 3 would tell an
automated caller that an environment is awaiting SSH-key registration.

**Resolution**: `2` satisfies FR-011's letter ("2 or greater" includes 2) and the global table
simultaneously — a `doctor` that could not run *is* a case of "could not proceed", and `2` is
already documented as a shared, non-unique code. Nothing above 2 is available.

**Spec follow-up (not applied here — this command is read-only w.r.t. the spec):** FR-011's
"2 or greater" should be narrowed to "exactly 2". The open-ended range is now a trap for whoever
implements it. Raise via `/speckit-clarify 013` or a direct spec edit before `/speckit-tasks`.

---

## R5 — Image freshness needs a stamp that does not exist yet

**Decision**: add an `org.opencontainers.image.version` **label** to `image/Dockerfile`, populated
from a build arg that `build` supplies from `_resolve_version()`. `doctor` reads it back with
`image inspect` — locally, no registry.

**Finding**: `image/Dockerfile` carries **no** version label today (verified), and `build` invokes
`[rt, "build", "-t", tag, ctx]` with no build args. Both need changing, which makes FR-012a a
*build-time* change with a *diagnostic* payoff — the two halves land together or the check reports
`unknown` forever.

**A wrinkle worth stating**: `_resolve_version()` returns `"0.0.0+unknown"` when the tool is
neither installed nor run from a checkout with a readable `pyproject.toml`. Stamping that value
would be worse than not stamping — a meaningless version that *looks* like an answer. When the
version is unresolvable, **omit the label**, which lands the image in FR-012b's *unknown* bucket
where it belongs.

**Alternative rejected**: an `ENV` in the image. A label is inspectable without running the image,
which matters because `doctor` must not start containers (R1).

**Consequence**: every image built before this ships reports **unknown** (FR-012b), permanently,
until rebuilt. The spec already calls this correct rather than unfortunate; the plan agrees.

---

## R6 — `status` is genuinely taken, so FR-001's naming constraint holds

**Decision**: the command is `doctor`. No alias.

**Finding, verified**: `status` is a real Typer command whose docstring reads *"Alias of `plan` —
the current state of each declared environment vs the spec"*, and both call `do_aac_status`. The
spec's premise is accurate rather than assumed.

---

## R7 — `doctor` MUST be in the `--json` set, and a test will enforce it

**Decision**: `doctor` takes `--json` and emits through the Feature 009 envelope.

**Finding**: `NO_JSON_COMMANDS` is `frozenset({"host env", "completions", "attach", "menu"})`,
asserted by two tests. A new command is in the JSON set by default and a test *fails* if the set
drifts — so FR-011's machine-readable half is enforced by machinery that already exists, and
adding `doctor` to the exclusions would require deliberately editing an assertion.

---

## R8 — The layout remedy must be the SAME STRING, not a matching one

**Decision**: the pre-011 layout finding reuses the deploy path's refusal text
(`refuse_superseded_layout`) rather than restating it.

**Rationale**: SC-008 demands **zero divergence** between what `doctor` says and what a deploy
says. Two strings that agree today drift the moment one is edited, and the drift is invisible —
both messages still read correctly in isolation. Sharing the source makes divergence impossible
rather than unlikely, and a test can assert the identity directly.

This generalises to the spec's assumption that "findings should share their wording with the
corresponding deploy-time failure": wherever a deploy already has the message, `doctor` calls the
same producer.

---

## R9 — "All problems in one pass" fights the codebase's `die()` habit

**Decision**: every check returns a `Check` result. No check calls `die()`.

**Finding**: the existing validators — `refuse_superseded_layout`, `validate_credential`,
`resolve_workspace`, `driver_runtime_argv` — all `die()` on the first problem, which raises
`Fatal` and ends the run. That is right for a deploy and fatal for FR-003, which requires **all**
findings from one run.

**Consequence**: where `doctor` reuses a validator for its message (R8), it must call it inside a
`Fatal` trap and convert the exception into a finding. That is a small adapter, and it is also the
only way to satisfy R8 and FR-003 at once — reuse the wording, discard the control flow.

**Alternative rejected**: refactoring the validators to return results instead of dying. A much
larger change to code paths that are correct as they are, and Constitution V says the spec is the
durable artifact — this feature does not need to rewrite four other features to be built.

---

## R10 — Port availability has a definition worth pinning down

**Decision**: a port is a **blocking** finding only when it is bound by something that is *not*
this environment's own container. Bound by its own running container is a **pass**.

**Rationale**: the port is derived deterministically from the name (Constitution IV), so a
redeploy of a running environment always finds "its" port occupied. Reporting that as a conflict
would make `doctor` fail on every healthy running environment — a diagnostic that cries wolf on
the normal case is one nobody runs, which is the failure mode FR-011's exit-code reasoning is
already written to avoid.

---

## Summary of what this feature must NOT do

Collected because each was tempting and each would be wrong:

1. Call `migrate_flat_state()`, or any other "safe, idempotent" helper that touches disk (R1).
2. Resolve a manager-source credential to check that it resolves (R3).
3. Return an exit code above 2 (R4).
4. Stamp `0.0.0+unknown` into an image (R5).
5. Restate a deploy-time remedy in its own words (R8).
6. Let a single check's `die()` end the run (R9).
7. Report a healthy environment's own port as a conflict (R10).
