# Quickstart: Validating Egress and Provider Control

**Feature**: 012-egress-provider-control | **Date**: 2026-07-30

Runnable validation. Contract detail is in
[contracts/egress-contract.md](./contracts/egress-contract.md); entities and validation rules are
in [data-model.md](./data-model.md).

## Prerequisites

- A container runtime with Compose v2 (Podman on Linux, Docker on macOS).
- A checkout — the proxy service is generated, so `build` and the compose model both matter.
- At least one real provider credential, to prove the permitted path still works.

---

## Tier 1 — Gate (hermetic, no container)

```bash
scripts/quality-gate.sh
```

Covers, for this feature:

- schema validation: the three states (absent / empty / non-empty), unknown provider name, bare
  string instead of a list, unknown key, bad enum (C1)
- the compose model gains an `egress` service **only** when a declaration is present, and is
  **byte-identical to today** when absent (C2, C8)
- the identity lock still passes — nine volumes, unchanged names (C8)
- `NO_PROXY` precedence: **any** operator value is refused under an enforced declaration, with no
  subset comparison attempted (C6)
- the adherence and built-in-default fixtures agree with `AGENTS` — a fifth agent fails both (C5)

---

## Tier 2 — Real container (acceptance)

### S1 — Identity is unchanged — run this first

```bash
agent-container list --json      # before and after, same names
```

**Expected**: container name, port and all **nine** volume names identical. A tenth volume means
FR-010 was implemented in place rather than deferred (research R9) — **stop**, that is a migration,
not this feature.

### S2 — A declared provider works normally (US1, scenario 1)

```yaml
# .agent-container/environments.yaml
egress:
  providers: [anthropic]
```

```bash
agent-container up dev
agent-container attach dev      # inside: run the agent, ask it something
```

**Expected**: answers normally. Enforcement that breaks the permitted path is not enforcement.

### S3 — An undeclared provider does not silently succeed (US1, scenario 2) — the core case

Inside the container, with the same declaration in place, reach for a provider that is **not**
declared:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://api.openai.com/v1/models
```

**Expected**: **refused, fast** — a clean proxy error, not a hang and not a 200. A hang means the
proxy is dropping rather than refusing (C3, research R1a). A success means the request went around
the proxy — check `NO_PROXY` (S6) before anything else.

### S3a — An indirect endpoint is declarable, and replaces the vendor's hosts (FR-001a/FR-001b)

```yaml
egress:
  providers:
    - name: anthropic
      hosts: [llm.corp.internal]
```

```bash
agent-container up dev
agent-container status dev --json | jq '.egress.hosts, .egress.host_source'
```

**Expected**: the allowlist contains `llm.corp.internal` and **not** `api.anthropic.com`;
`host_source` reads `declaration`. Then, inside the container:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/messages
```

**Expected**: **refused.** An operator who routed through a gateway did so to close the direct
path. If this succeeds, `hosts:` was implemented as additive — the declaration reads as constrained
while the vendor path stays open, which is the silent over-permission this feature exists to
prevent.

### S4 — The built-in default is disclosed (US2, SC-003) — the motivating defect

Remove the `egress:` block entirely and deploy with **no credential at all**:

```bash
agent-container up dev --agent opencode
```

**Expected**: deploys (FR-004 — unrestricted, unchanged), **and** states once that opencode can
reach a provider without your credential. This is precisely what Feature 010's probe observed
silently.

```bash
agent-container up dev --agent opencode    # again
```

**Expected**: no repeat of the disclosure on ordinary subsequent commands. Noise trains operators
to ignore it.

### S5 — Zero providers is coherent, not degenerate (FR-011)

```yaml
egress:
  providers: []
```

**Expected**: deploys; every outbound model call is refused. The container still runs, the shell
still works, git over SSH is unaffected. An air-gapped environment is a supported state, not a
broken one.

### S6 — `NO_PROXY` cannot silently disable enforcement (C6) — the silent-failure case

```bash
printf 'NO_PROXY=*\n' > .agent-container/dev.env
agent-container up dev
```

**Expected**: **refused**, naming the file and the variable. If it deploys, re-run S3 — the
declaration will read as enforced while enforcing nothing, which is worse than no feature at all.

Now the same with a value that *looks* harmless:

```bash
printf 'NO_PROXY=localhost\n' > .agent-container/dev.env
agent-container up dev
```

**Expected**: **also refused.** The tool attempts no judgement about which values are safe — that
comparison is what C6 deliberately does not implement. A refusal here is the feature working, not
being pedantic.

### S7 — Enforcement strength is stated honestly (C5, SC-004)

```bash
agent-container status dev --json | jq '.egress, .agent'
```

**Expected**: shows `enforcement`, `enforced`, the resolved `hosts` for each declared provider,
`honours_proxy`, and `builtin_default_provider`. Read the prose output too and confirm it says a
proxy binds clients that honour it and does **not** stop a process that dials directly. Any
phrasing implying more than that fails SC-004.

### S8 — Strict mode refuses what advisory permits (FR-007b, SC-004a)

Point the environment at an agent not on the adherence list (or stop the proxy image from
starting):

```bash
agent-container up dev            # enforcement: advisory
agent-container up dev            # enforcement: strict
```

**Expected**: advisory deploys and says the declaration is not enforced; strict **refuses**, naming
the agent and why. Zero deployments proceeding with an unenforceable declaration.

### S9 — The proxy dies with the environment (FR-007)

```bash
agent-container down dev
<runtime> ps -a | grep dev        # expect: no proxy container
agent-container wipe dev -y
<runtime> volume ls | grep agent-container-dev   # expect: no output
```

**Expected**: nothing left behind. The proxy is in the same compose project, so this needs no new
teardown step — if it does, it was put in the wrong file (C2).

### S10 — Rootlessness is unchanged (SC-005)

```bash
agent-container attach dev        # inside: id; capsh --print 2>/dev/null || true
```

**Expected**: identical to before the feature. No added capability, no `sudo`, nothing installed at
runtime.

### S11 — Existing environments keep working (FR-012)

Deploy an environment whose spec predates this feature (no `egress:` key at all):

```bash
agent-container up legacy
```

**Expected**: deploys exactly as before, with no proxy service in the generated model — and no
change in effective permissions beyond the one-time disclosure.

---

## Tier 3 — Deferred, and why

**FR-010 / US3 (egress events outlive the container) is not validated here.** It needs durable
per-container storage, which means a tenth volume and therefore an identity migration (research
R9). That store is shared with Feature 016 and should be paid for once, by whichever feature ships
it first — expected to be 016, since the machinery is its subject. **SC-006 is therefore not yet in
force**, rather than silently failing.

If it were implemented in this feature, S1 would fail — which is the guard working, not a bug.

---

## Definition of done

| Check | Source |
|---|---|
| Identity unchanged — nine volumes | S1 — **the blocking one** |
| Gate green | Tier 1 |
| Permitted path works, undeclared path refused fast | S2, S3 |
| Built-in default disclosed once | S4 |
| `NO_PROXY` cannot disable enforcement | S6 — **the silent-failure case** |
| Strength stated honestly, no overclaim | S7 |
| Rootlessness unchanged | S10 |
| Pre-feature environments unchanged | S11 |
| FR-010 deferred deliberately, not forgotten | Tier 3 |
