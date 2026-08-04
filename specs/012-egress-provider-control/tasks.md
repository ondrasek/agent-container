# Tasks: Egress and Provider Control

**Input**: Design documents from `/specs/012-egress-provider-control/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/egress-contract.md](./contracts/egress-contract.md),
[quickstart.md](./quickstart.md)

**Tests**: Included. This project's quality gate is a hard CI gate and the feature's core claims
(enforcement strength, `NO_PROXY` precedence, identity) are exactly the kind that pass in
appearance and fail in substance — the recurring failure shape in this repo is **a check that
passes while the thing it names is broken**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3

## Path Conventions

Single-file CLI. Nearly everything lands in `bin/agent-container`; tests in `bin/tests/`; docs in
`docs/`. There is no new module (plan, Structure decision).

---

## Scope decision carried from the plan — read before starting

**US3 / FR-010 is DEFERRED to after Feature 016**, for two independent reasons:

1. Durable egress records need a volume, and a **tenth** per-container volume is an identity
   migration, not an edit (research R9). The identity lock fails on it *by design*.
2. That store and its ingestion machinery are shared with Feature 016, which is the expected first
   mover (research R5). The dependency is **not** one-way: whichever feature ships the store first
   pays the migration, and the other consumes it.

US3's tasks are written below and marked deferred so the work is *recorded*, not forgotten. The
shipped scope of this feature is **US1 + US2** — both P1, neither depends on FR-010.

---

## Phase 1: Setup

**Purpose**: Pin the one genuinely open decision — which proxy — by running it, not reading about
it. This is the project's established pattern (Feature 010's opencode probe, this feature's R1).

- [X] T001 Capture the pre-feature identity baseline into `bin/tests/test_pure_logic.py` context: run `agent-container list --json` and record container name, port and the nine volume names in the scratchpad, so T033's diff has something to compare against (quickstart S1)
- [X] T002 Evaluate candidate forward-proxy images against C3's four hard criteria — allowlists on the `CONNECT` target, **refuses with a status rather than dropping**, runs **rootless**, injects **no CA certificate** — and record the result plus rejected candidates in `specs/012-egress-provider-control/research.md` as R10
- [X] T002a Re-run the **Constitution VI** justification against the image T002 actually chose, and record it in `plan.md`'s Complexity Tracking. The current entry justifies "a proxy image" generically; VI requires every dependency earn its place, which cannot be assessed against a placeholder — image size, provenance, maintenance status and update cadence are all properties of the concrete choice
- [X] T003 Prove the chosen image satisfies C3 **by running it**: start it with a one-host allowlist, `curl` an allowed host (expect success) and a disallowed host (expect **curl exit 56**, never `%{http_code}` — R10a measured that it reads `000` for a refusal and a drop alike), and confirm with `tcpdump`/handshake inspection that the TLS session is end-to-end. Record the transcript in R10

**Checkpoint**: the proxy is chosen on evidence, and the R1a risk (drop vs refuse) is closed.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: The facts and the schema every story rests on. Nothing in US1 or US2 can be built or
tested without these.

- [X] T004 [P] Add the provider→hosts mapping table (`PROVIDERS`) to `bin/agent-container`, versioned with the tool, covering the providers the four supported agents use (research R6, data-model §1)
- [X] T005 [P] Add the built-in-default-provider fixture (`AGENT_BUILTIN_DEFAULT`) to `bin/agent-container`, one entry per member of `AGENTS`, recording whether the agent answers with no operator credential and which provider it reaches (data-model §3; opencode's value is Feature 010's probe result)
- [X] T006 [P] Add the proxy-adherence fixture (`AGENT_HONOURS_PROXY`) to `bin/agent-container`, one entry per member of `AGENTS`, all four `True` per research R1 (data-model §4)
- [X] T007 Add cross-file agreement tests in `bin/tests/test_pure_logic.py` proving `AGENT_BUILTIN_DEFAULT` and `AGENT_HONOURS_PROXY` each cover **exactly** `AGENTS` — a fifth agent added without probing must **fail**, and must default to *not known to honour* so `strict` refuses it
- [X] T008 Add a proof in `bin/tests/test_guards_can_fail.py` that T007's guard actually fails on drift: append a synthetic fifth agent to `AGENTS` in a copy and assert the guard raises. The repo's recurring failure is a guard that passes while the thing it names is broken
- [X] T009 Extend `validate_environment` in `bin/agent-container` with the optional `egress` key: `providers` (a list whose entries are **either** a known name **or** a `{name, hosts}` mapping, FR-001a) and `enforcement` (via `_enum_field`), dying before any action and naming the offending file+field (contract C1)
- [X] T009a Implement the **replacement** semantics in `bin/agent-container`: where an entry carries `hosts:`, the tool's mapping for that entry is **discarded**, not extended (FR-001b, research R6a)
- [X] T009b Reject malformed host lists in `bin/agent-container` — an entry with a scheme, path or port must `die` naming the field rather than being accepted and then never matching (contract C1)
- [X] T010 Add schema tests in `bin/tests/test_agent_as_code.py` for every C1 row: `egress` not a mapping, `providers` a bare **string** (must die naming the field, **not** iterate characters), unknown name in short form (dies listing the known set), unknown name in **long** form (**accepted** — hosts are authoritative), long form without `hosts` (dies), a URL in `hosts` (dies), unknown key inside a provider mapping, unknown key inside `egress`, bad `enforcement` enum
- [X] T010a Add a test in `bin/tests/test_compose.py` proving `hosts:` **replaces** rather than extends: declaring `{name: anthropic, hosts: [gw.corp]}` must produce an allowlist containing `gw.corp` and **not** the vendor's own hosts. Additive-vs-replacing is invisible in a passing deployment, which is why it gets a test rather than a doc line (FR-001b)
- [X] T011 Add tests in `bin/tests/test_agent_as_code.py` pinning the **three distinct declaration states** — `egress` absent (unrestricted), `providers: []` (air-gapped), `providers: [x]` (constrained). Absent must **never** coerce to empty; that would turn every existing environment air-gapped on upgrade (data-model §2)

**Checkpoint**: the schema accepts and rejects correctly; the per-agent facts are enforced by tests
rather than by comments.

---

## Phase 3: User Story 1 — Declare which providers an environment may use (P1)

**Goal**: A declared provider set is enforced by a proxy the tool deploys; anything undeclared is
refused rather than silently allowed.

**Independent test**: declare one provider, confirm the agent reaches it normally, then confirm an
undeclared provider does not succeed silently (quickstart S2, S3).

### Blockers found by the Phase 3 design fan-out — settle these first

Each was **verified against the real code**, not inferred. They change signatures, so they precede
T012.

- [X] T011a **Decide and record the single mechanism by which `up` sees the declaration.** `do_up` (`bin/agent-container:3126`) never calls `load_project_spec`; the declaration lives only on the `apply` path. Yet quickstart S2/S4/S6/S8 all drive the feature via `agent-container up dev`. Three design agents proposed three incompatible mechanisms. Every downstream signature depends on this — T012's parameter, T019's location, T021's call site, T022's log point. **Decide before writing code**, and cover `do_redeploy` (`:3387`), which duplicates the precheck sequence rather than routing through `do_up`
- [X] T011b Create `image/egress/` — Dockerfile (Alpine + tinyproxy, uid 65534) and `.dockerignore`. **It does not exist**; T002/T003 evaluated and chose it but committed no artifact, so any enforceability predicate keyed on its presence is vacuously false today. Use `FilterType` (not the deprecated `FilterExtended`) and drop `FilterCaseSensitive Off`, which is a documented no-op
- [X] T011c Generate filter entries **anchored and escaped** — `^<re.escape(host)>$`. tinyproxy matches filter lines with `regexec` **unanchored**, so a bare `api.anthropic.com` also permits `api.anthropic.com.attacker.net`. **This is the security boundary of the whole feature**; it gets its own test with that exact attacker string
- [X] T011d Cap total hostname length in `HOSTNAME_RE` (`:4971`). It accepts a **731-character** host (verified) because the label group repeats unbounded; tinyproxy reads its filter with a 512-byte `fgets` and regcomps each chunk, so one over-long entry becomes a prefix pattern **plus** a suffix pattern — silent over-permission reachable through the FR-001a `hosts:` path
- [X] T011e Replace `_yaml_service_keys` (`:2240`) with `yaml.safe_load`. The column-0 regex scanner returns `[]` for `services: {agent: {...}}` (flow style) and for a quoted `"agent":` key — both verified — so an operator override can set `agent.environment.NO_PROXY`, win the merge as the second `-f`, and defeat C6 entirely. PyYAML is already the sanctioned dependency
- [X] T011f Make `resolve_provider_hosts` unable to confuse **absent** with **empty**, and refuse the fourth state (`egress:` with `enforcement:` but no `providers`) — data-model §2. Presence must live in the type, not in one caller's discipline
- [ ] T011g Add the effective allowlist to drift detection. `env_reconcile`/`env_desired_config` (`:5237`) compare only mode/agent/clone-url, so editing `egress.providers` and re-running `apply` reports **matching** and never redeploys — the declaration changes and the running proxy does not. Hostnames only, never a credential
- [X] T011h Keep the proxy container out of the environment-scanning surface. Compose names an unnamed service's container `<project>-<service>-1` → `agent-container-acme-egress-1`, which starts with `CONTAINER_PREFIX`; **six** sites treat any `agent-container-*` container as an environment (`:1104`, `:2674`, `:3481`, `:3511`, `:2700`, and the wizard pickers)
- [ ] T011i Ensure teardown covers the proxy on the **fallback** path. `down_container` (`:3210`) issues a project-scoped `compose down`, but its fallback (`:3229`) does `rm -f <container_name(name)>` plus explicit volume removal — that branch strands a proxy container

### Compose model

- [X] T012 [US1] Extend `build_compose_model` in `bin/agent-container` to emit a second `egress` service — with the allowlist derived from the declaration — **only** when a declaration is present and enforceable (contract C2)
- [X] T013 [US1] Set `HTTPS_PROXY`/`HTTP_PROXY` on the `agent` service in `build_compose_model` to point at the `egress` service (contract C2, FR-007a)
- [X] T014 [US1] Add a test in `bin/tests/test_compose.py` proving the generated model is **byte-identical to today** when no declaration is present — the FR-004/FR-012 guarantee that existing environments keep working
- [X] T015 [US1] Add tests in `bin/tests/test_compose.py` proving the `egress` service appears with the right allowlist for a non-empty declaration, and appears with an **empty** allowlist for `providers: []` (FR-011 — zero providers is coherent, not degenerate)
- [ ] ~~T016~~ **DROPPED** — contradicted by T020e, which deliberately inspects the override to detect proxy redefinition. Keeping both would pin "never look at the override" against "look at the override". The surviving half (proxy is emitted into the *generated* file) is covered by T014/T015. Original text: add a test proving the proxy is emitted into the generated file and that `resolve_sidecar_override` is untouched — the operator's `<name>.services.yaml` stays operator-owned and still rides as the second `-f` on top (research R4)
- [X] T017 [US1] Add a test in `bin/tests/test_pure_logic.py` proving the identity is unchanged: nine volumes, same names, same container name, same port. A tenth volume means FR-010 leaked into this feature (research R9)

### `NO_PROXY` — the silent-failure case

- [ ] T018 [US1] Make the tool set `NO_PROXY` itself, to the minimum needed for in-container traffic, in `bin/agent-container` (contract C6, research R3)
- [ ] T019 [US1] Refuse **any** operator-supplied `NO_PROXY` while a declaration is enforced, naming the file and the variable, in `bin/agent-container`. **Attempt no subset comparison** — a "is this wider?" check across `*`, `.suffix`, IP, CIDR and port forms would err permissively and reproduce the bypass it exists to prevent (contract C6, research R3)
- [ ] T020 [US1] Add tests in `bin/tests/test_compose.py` for C6's two rows — any operator `NO_PROXY` under an enforced declaration (refused, names the file), and no declaration (tool sets nothing). Present-or-absent, not a comparison. This is the feature's most likely silent failure and gets its own test, not a doc line

### Enforcement mode

- [ ] T021 [US1] Implement the `advisory` / `strict` decision in `bin/agent-container`: advisory deploys and states the declaration is unenforced; strict refuses, naming the agent and why (FR-007b, data-model §5)
- [ ] T022 [US1] Make the **effective** mode visible before deploying, in `bin/agent-container` (FR-007b)
- [ ] T023 [P] [US1] Add tests in `bin/tests/test_agent_as_code.py` covering the four cells of data-model §5's mode table, including strict refusing on a proxy that cannot start (SC-004a — zero deployments proceeding with an unenforceable declaration)

### All egress, not just providers (scope decision, 2026-08-04)

- [X] T020a [US1] Implement `egress.allow` in `bin/agent-container` — non-provider hosts, with `*.domain` meaning domain-and-subdomains (FR-001c/FR-001d), folded into the same effective allowlist as `providers`
- [X] T020b [P] [US1] Add tests for `allow` in `bin/tests/test_agent_as_code.py`: plain host, `*.` form, and that `*.example.com` does **not** match `example.com.attacker.net`
- [X] T020c [US1] **Refuse or warn at deploy when HTTPS push is configured and the remote's host is not in the effective allowlist** (FR-003c) — refuse under `strict`, warn under `advisory`, naming the host to add. **This is the task that protects Hard Constraint #1.** Verified by probe: under `providers: [anthropic]`, `git ls-remote https://github.com/…` returns `CONNECT tunnel failed, response 403`
- [X] T020d [P] [US1] Add a test in `bin/tests/test_compose.py` proving T020c fires for an HTTPS remote absent from the allowlist and stays silent for an SSH remote (which ignores `https_proxy`) or when the host is declared
- [ ] T020e [US1] Report an operator override that redefines the `egress` service, set `enforced` false, and refuse under `strict` (contract C2). Permitted but never silent — claiming enforcement for a proxy the tool did not configure is the overclaim SC-004 exists to prevent

### Error attribution

- [ ] T023a [US1] Implement FR-003b as an **ordering-and-vocabulary invariant**, not a new check: credential resolution already fails naming the credential and its source, so ensure the egress code cannot re-attribute that failure to the `egress` declaration, and thread environment context into the message. **Do NOT infer that a declared provider requires a credential** — no such mapping exists (`PROVIDERS` is provider→hosts; `CRED_PROVIDER` is credential→provider for delivery routing and covers 2 of 5), and any inference false-positives on a provider reached without one, which is the very case Feature 010 found
- [ ] T023b [P] [US1] Add a **negative** test in `bin/tests/test_credentialing.py`: a credential failure names the credential and its source and mentions neither `egress` nor any provider name (FR-003b)

### Lifecycle

- [ ] T024 [US1] Verify `down`, `redeploy` and `wipe` tear the proxy down with no new step, because it shares the compose project — add the assertion to `bin/tests/test_lifecycle.py` (contract C2, quickstart S9)
- [ ] T025 [US1] Handle the headless-foreground consequence in `bin/agent-container`: `--abort-on-container-exit --exit-code-from agent` stops every service when any exits, so a crashing proxy aborts the run. Fail-closed and correct — **state it** in `docs/execution.md` rather than let a headless user discover it (research R4)

**Checkpoint**: US1 is independently deliverable and testable. Run quickstart S2, S3, S5, S6, S9.

---

## Phase 4: User Story 2 — The default-provider path is explicit (P1)

**Goal**: An operator learns that an agent has a built-in provider it will reach without their
credential — the specific defect that motivated the feature — rather than discovering it from
traffic.

**Independent test**: with no credential and no declaration, confirm the tool states that the
selected agent has a built-in default and what that implies (quickstart S4).

- [ ] T026 [US2] Emit the disclosure at deploy, **once**, for an environment with no declaration whose agent has a built-in default, in `bin/agent-container` — stating that the agent can reach a provider without the operator's credential, **which** provider where known, and that `egress.providers` is how to constrain it (contract C4, FR-006)
- [ ] T027 [US2] Add tests in `bin/tests/test_cli.py` proving the disclosure fires when there is no declaration **and** the agent has a default, and does **not** fire when a declaration exists or the agent has no default — noise trains operators to ignore it (contract C4)
- [ ] T027a [US2] Report at **deploy time** when the selected agent's built-in default provider is **not in the declared set**, in `bin/agent-container` (FR-003a). Both facts are known without running the agent, so waiting for a runtime refusal would be withholding. Covers spec US2 acceptance scenario 2, which had no task
- [ ] T027b [P] [US2] Add a test in `bin/tests/test_cli.py` for T027a — fires when the default is outside the declared set, silent when it is inside or when nothing is declared (FR-003a)
- [ ] T028 [US2] Implement the enforcement-strength statement in `bin/agent-container`: a proxy refuses clients that honour it, does **not** stop a process that dials directly, and **which** agents are known to honour it — currently all four (contract C5, FR-008)
- [ ] T029 [US2] Add a test in `bin/tests/test_cli.py` asserting the strength statement names the adherence set and contains **no** phrasing implying packet-level or absolute enforcement. SC-004's failure mode is satisfying the requirement in appearance
- [X] T030 [P] [US2] Extend the `--json` envelope in `bin/agent-container` with `egress.providers`, `egress.hosts`, `egress.enforcement`, `egress.enforced`, `agent.builtin_default_provider`, `agent.honours_proxy` (contract C7, FR-005/FR-013)
- [X] T031 [P] [US2] Add tests in `bin/tests/test_agent_interface.py` proving the `--json` fields report the **effective** allowlist — including `host_source` — so an operator sees the mapping before a refusal rather than after, and an operator `hosts:` override is reflected rather than the tool's default (research R6/R6a, FR-001b). Reporting the default while enforcing an override would state a permission set the proxy does not enforce

**Checkpoint**: US2 is independently deliverable. Run quickstart S4, S7, S8.

---

## Phase 5: User Story 3 — Undeclared egress is recorded (P2) — **DEFERRED**

**Deferred to after Feature 016.** Recorded here so the work is tracked, not forgotten. Do **not**
implement in this feature: T033 would fail, correctly.

- [ ] T032 [US3] **DEFERRED** — Emit egress events from the proxy with the fields in data-model §6 (`timestamp`, `host`, `provider`, `declared`, `decision`) and **nothing more**: no headers, no bodies, no model names. The narrowness is Constitution III holding, not an omission
- [ ] T033 [US3] **DEFERRED** — Persist egress events into the durable per-container store and its ingestion machinery, under **their own schema** — not as rows in a run record, and not behind a tenth volume of this feature's own (research R9, FR-010). If that store does not yet exist, this task is **blocked**, not worked around
- [ ] T034 [US3] **DEFERRED** — Surface events through inspection with **no noise when nothing happened** — silence means nothing occurred (spec US3 scenario 3)

---

## Phase 6: Polish & Cross-Cutting

- [ ] T035 [P] Write `docs/egress.md` covering the declaration, the three states, enforcement modes, the honest strength statement, and the `NO_PROXY` rule
- [ ] T036 [P] Add the providers-vs-credentials distinction to `docs/credentials.md` — declaring a provider must not imply storing its credential in the project (FR-009); they are neighbours in the file, not a hierarchy
- [ ] T037 [P] Update `docs/agent-as-code.md` with the `egress:` block in the example spec
- [ ] T038 Add at most a one-line invariant to `CLAUDE.md` and re-measure the token budget with a real tokenizer — the file is at 1999/2000 and prune-before-adding applies
- [ ] T039 Add acceptance tests in `bin/tests/test_acceptance.py` for quickstart S3 (undeclared refused — assert **curl exit 56**, never `%{http_code}`, which reads `000` for a refusal *and* a drop alike; research R10a), S4 (disclosure), S6 (`NO_PROXY` refused), S10 (rootlessness unchanged) and S11 (a pre-feature environment deploys identically)
- [ ] T039a Add a test in `bin/tests/test_credentialing.py` asserting **no credential value** appears in the generated compose model, the proxy's generated config, or `--json` output, for an environment declaring **both** providers and credentials. Seed a recognisable **sentinel** value through each credential source and assert its absence in every generated artifact. Asserting "no key-shaped string" would test the assertion's imagination; asserting a *known* value is absent tests the actual path (FR-009, SC-007)
- [ ] T040 Re-run the identity check from T001 and diff against the baseline — nine volumes, same names, same port. **This is the blocking check**; if any name drifted, nothing else matters
- [ ] T041 Run `scripts/quality-gate.sh` and the full acceptance tier, then verify every quickstart scenario S1–S11 by hand, **including the lettered ones** (S3a, S9a). Run the **whole** suite, not just the new tests — changing a shared contract is exactly when a pre-existing test still pins the old shape

---

## Dependencies

```text
Phase 1 (T001–T003)  ── proxy chosen by running it
        ↓
Phase 2 (T004–T011)  ── facts + schema; BLOCKS both stories
        ↓
   ┌────┴────┐
   ↓         ↓
Phase 3    Phase 4    ── US1 and US2 are INDEPENDENT after Phase 2
(US1)      (US2)
   └────┬────┘
        ↓
Phase 6 (T035–T041)  ── polish; T039a security, T040 blocking

Phase 5 (US3) ── DEFERRED, blocked on Feature 016
```

- **T003 blocks T012** — do not build the compose model around an unproven proxy.
- **T007/T008 block T021** — `strict` decides on the adherence fixture, so the fixture must be
  guarded before it is trusted.
- **T009 blocks everything in Phase 3 and 4** — nothing can read a declaration that does not parse.
- **T017 and T040 are the same check** at start and end. T040 is blocking.

## Parallel opportunities

| Batch | Tasks | Why safe |
|---|---|---|
| Foundational facts | T004, T005, T006 | three independent tables, no shared logic |
| US2 machine-readable | T030, T031 | separate file from the prose output |
| Docs | T035, T036, T037 | three separate files |

US1 and US2 can be worked by different people in parallel once Phase 2 lands — they touch
different code paths (compose model vs. output/JSON).

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** That gives a declared, enforced provider set. It is
useful alone, and it is where all the risk lives.

**Increment 2 = Phase 4 (US2).** Disclosure and the honest strength statement. Small, and it closes
the specific defect that motivated the feature.

**Increment 3 = Phase 5 (US3), after Feature 016.** Do not pull it forward to feel complete; the
cost is an identity migration plus an ingestion path that gets thrown away.

## Task count

| Phase | Tasks |
|---|---|
| 1 — Setup | 4 |
| 2 — Foundational | 11 |
| 3 — US1 | 30 |
| 4 — US2 | 8 |
| 5 — US3 (deferred) | 3 |
| 6 — Polish | 8 |
| **Total** | **64** (61 in scope, 3 deferred) |
