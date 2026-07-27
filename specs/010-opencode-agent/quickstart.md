# Quickstart: Validating opencode as a Supported Agent

**Feature**: 010-opencode-agent | **Date**: 2026-07-26

Runnable validation for this feature. Contract details live in
[contracts/agent-contract.md](./contracts/agent-contract.md); the volume set is in
[data-model.md](./data-model.md).

## Prerequisites

- A container runtime with Compose v2 (Podman on Linux, Docker on macOS).
- A checkout (the image build needs one).
- An opencode-capable provider key for the credential scenarios (`ANTHROPIC_API_KEY` or
  equivalent). The persistence scenarios do not need one.

---

## Tier 1 — Gate (hermetic, no container)

```bash
scripts/quality-gate.sh
```

Must be green before anything else. It covers, for this feature:

- the `per_container_volumes` doctest — the **nine**-volume contract (C5)
- the agent-list agreement test parsing `bin/agent-container`, `entrypoint.sh`, `Dockerfile` (C8)
- `--agent opencode` accepted / invalid values rejected (C1)
- completions offering all four names (C2)

---

## Tier 2 — Real container (acceptance)

```bash
pytest -m acceptance bin/tests
```

On macOS + Lima the work dir must be Lima-shared (defaults to `~/.cache/agent-container-acceptance`;
override with `AGENT_CONTAINER_ACCEPTANCE_TMPDIR`).

### S1 — opencode runs interactively (US1)

```bash
agent-container up ocx --agent opencode
agent-container attach ocx
```

**Expected**: a tmux window named `opencode` with the agent running; `attach` lands on it. A dead
session reports "nothing running" rather than a silent empty shell (Feature 004 behavior,
unchanged).

### S2 — opencode runs headless and its exit status propagates (US1, C3)

```bash
agent-container up ocx --agent opencode --mode headless --foreground --task "print hello"
echo "exit=$?"
```

**Expected**: the CLI's exit status equals the agent's.

**Resolved by research R5** — `opencode run` does propagate a failing status.

**Do not use "no credential configured" as the failing case.** opencode **succeeds** (exit 0)
with no credential, via a built-in default model; that observation would wrongly suggest FR-005
is unsatisfiable. The failing case is a **present-but-invalid** key
(`ANTHROPIC_API_KEY=sk-ant-invalid…`), which exits 1.

### S3 — Both kinds of state survive recreation (US1, C6)

```bash
agent-container attach ocx        # inside: opencode auth login   → writes ~/.local/share/opencode/auth.json
                                  # inside: edit ~/.config/opencode/opencode.json
agent-container down ocx
agent-container up ocx --agent opencode
agent-container attach ocx        # inside: opencode auth list    → credential still present
                                  #         opencode.json edit    → still present
```

**Expected**: **both** survive. Checking only `opencode.json` does not validate this — the
credential is the half the original single-volume design would have lost.

### S4 — Full teardown leaves nothing (US3, C5)

```bash
agent-container wipe ocx -y
<runtime> volume ls | grep agent-container-ocx   # expect: no output
```

**Expected**: zero orphaned volumes, all nine gone.

### S5 — A pre-upgrade environment still tears down (US3, FR-009)

The headline risk. Create an environment whose volume set is the **old seven** (simulated by
creating only those volumes / by using a pre-upgrade `up`), then tear it down with the **new**
code:

```bash
agent-container wipe legacy -y
```

**Expected**: succeeds. The two absent volumes are tolerated, no error, no manual migration.

### S6 — Stale image gives an actionable failure (C4)

Select opencode against an image built before this feature:

**Expected**: a message naming `agent-container redeploy <name>` as the remedy — **not**
`exec: opencode: not found`.

### S7 — Credential exposure (US2, C7)

```bash
printf '%s' "$ANTHROPIC_API_KEY" > ./agent-container.ocx.anthropic.key
agent-container up ocx --agent opencode
grep -r "$ANTHROPIC_API_KEY" .                    # expect: only the .key file the operator wrote
agent-container wipe ocx -y
```

**Expected**: the key reaches the agent, and appears nowhere in command output or tool state; the
operator's local `.key` file is the sole durable copy.

---

## Tier 3 — No regression for the existing three (SC-007, FR-014)

```bash
for a in claude codex pi; do
  agent-container up reg-$a --agent "$a" && agent-container attach reg-$a && agent-container wipe reg-$a -y
done
```

**Expected**: launch, persistence, and teardown identical to before this feature.

---

## Definition of done

| Check | Source |
|---|---|
| Gate green | Tier 1 |
| S1–S7 pass | Tier 2 |
| Existing three unchanged | Tier 3 |
| Four spec amendments landed | [research.md](./research.md) § Required spec amendments |
| No stale volume count anywhere | `grep -rn "seven" CLAUDE.md bin/agent-container docs/` |
