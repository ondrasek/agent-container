# Quickstart: Agent-as-Code (Feature 006)

Runnable validation scenarios mapped to the Success Criteria in [spec.md](./spec.md).
Prereqs: a built image and (for most) a reachable host. Scenarios needing a real
model backend are opt-in/tokened; the mechanics (discover / validate / plan /
apply-idempotent / destroy-scoped / spec-integrity) are verifiable without a real
agent.

## Scenario A — Declare and apply reaches the environment (US1, SC-001)

```bash
mkdir -p acme/.agent-container && cd acme
cat > .agent-container/project.yaml <<'YAML'
environments:
  - name: acme
    host: local
    container:
      mode: interactive
      agent: claude
      workspace: persistent
YAML
agent-container apply          # discover -> validate -> plan -> confirm -> up
```

**Expected**: the tool reports the project root + host, previews the plan, and on
confirm the declared container is running — no other command issued.

## Scenario B — Idempotent apply (US1, SC-002)

```bash
agent-container apply          # against the already-satisfied spec
```

**Expected**: "no changes" — reality already matches; nothing is mutated.

## Scenario C — Invalid spec is refused with no partial change (US1)

```bash
printf '\n  bad: [unterminated\n' >> .agent-container/project.yaml
agent-container apply
```

**Expected**: refuses to act, names the offending file + field, changes nothing.

## Scenario D — No spec present falls back to today's behavior (US1, FR-004)

```bash
cd /tmp && agent-container list        # no .agent-container up the tree
```

**Expected**: the declarative model is inert; the tool behaves exactly as today.

## Scenario E — Credentials by reference, no plaintext in the dir (US2, SC-004/005)

```bash
# reference an API key via env + an encrypted-at-rest key via a decrypt command:
#   credentials:
#     - { name: ANTHROPIC_API_KEY, source: env, var: ANTHROPIC_API_KEY }
#     - { name: OPENAI, source: encrypted, path: .agent-container/openai.age, decrypt: "age -d -i ~/.age/key" }
export ANTHROPIC_API_KEY=sk-...
agent-container apply
grep -rIl "sk-" .agent-container/ ; echo "exit=$?"    # no plaintext secret in the dir
agent-container apply   # with ANTHROPIC_API_KEY unset -> fails, names the missing source
```

**Expected**: secrets are injected at runtime; **no** plaintext value appears in the
directory / logs / argv; a missing source fails before any change and names it; a
git-tracked plaintext secret is refused with remediation.

## Scenario F — Status/diff shows drift; apply converges; destroy is scoped (US3, SC-006/007)

```bash
agent-container status                 # per-resource: matching / drifted
# out-of-band change the running container, then:
agent-container status                 # reports the drift with a delta
agent-container apply                  # converges; reports what changed
agent-container destroy                # removes ONLY the declared/owned resources
```

**Expected**: drift is reported; apply converges; destroy leaves unrelated
containers and referenced hosts untouched.

## Scenario G — Spec integrity: the agent cannot modify `.agent-container/` (FR-020)

```bash
# a repo whose workspace carries .agent-container/ is deployed; inside the container:
agent-container attach acme
# in the container:
echo x >> /workspace/.agent-container/project.yaml    # -> Read-only file system
```

**Expected**: the write **fails** (read-only, kernel-enforced) — the agent cannot
re-govern itself; the tool would have refused to deploy a writable spec subtree.

## Scenario H — Declarative host binding (US4, SC-003)

```bash
# host = "hz1" (referenced) -> deployed onto hz1; destroy never deprovisions hz1
# host = { provision = "hetzner", ... } -> provisioned first, then deployed;
#   destroy --deprovision removes the spec-created host
```

**Expected**: a referenced host is treated as externally owned (never deprovisioned);
a provisioned host is created before deploy and removed only on explicit intent.

## Success signal

All scenarios pass: a directory + external secret sources apply to a running
environment in one command (idempotent), invalid specs are refused cleanly, absent
specs are inert, secrets never hit the directory, drift is visible and convergeable,
destroy is scoped, and the in-container `.agent-container/` is read-only — matching
SC-001…SC-007 + the FR-020 integrity guarantee.
