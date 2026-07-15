# Quickstart: Agent Provisioning & Credentialing (Feature 003)

Runnable validation scenarios proving the feature end-to-end. Each maps to
Success Criteria in [spec.md](./spec.md). Prereqs: a built image (`agent-container
build`) and a reachable host (local context is fine). Scenarios needing a real
model backend or a real git remote are **opt-in** (tokened) and never run in CI.

## Scenario A — Autonomous non-interactive push over SSH (US1, FR-001/SC-001)

```bash
agent-container up acme --push-key ~/.ssh/agent_push_ed25519 \
                        --known-hosts ~/.ssh/known_hosts.github
# inside the container:
agent-container attach acme
git clone git@github.com:you/repo.git && cd repo
echo x >> f && git add f && git commit -m "test" && git push
```

**Expected**: clone and push complete with **zero** prompts — no passphrase, no
host-key confirmation (`GIT_SSH_COMMAND` uses `IdentitiesOnly` + the seeded
known_hosts).

## Scenario B — Two keys stay distinct (US1, FR-002/SC-008)

```bash
agent-container up acme --host-key ~/kh --push-key ~/pk
agent-container attach acme
# in the container:
cat /run/agent-container/push_ed25519_key | ssh-keygen -lf -   # push key fp
cat ~/.ssh/hostkeys/ssh_host_ed25519_key.pub | ssh-keygen -lf - # host key fp
```

**Expected**: two different fingerprints; the inbound host key is on the `~/.ssh`
volume, the outbound push key is only under `/run` (never on the volume).

## Scenario C — Push key leaves no durable copy (US1/US4, FR-012/SC-004)

```bash
agent-container up acme --push-key ~/pk
agent-container wipe acme -y
# on the host:
for v in $(docker volume ls -q | grep agent-container-acme); do
  docker run --rm -v "$v":/v busybox grep -rl "PRIVATE KEY" /v || true
done
```

**Expected**: no match — the push key never rested on any persistent volume; the
operator's `~/pk` is the sole durable copy.

## Scenario D — Model/API credential reaches the backend (US2, FR-005/SC-002) — opt-in tokened

```bash
# with a real key in .env (ANTHROPIC_API_KEY=...) OR delivered as a file-secret
agent-container up acme
agent-container attach acme
claude -p "print ok"        # or: codex exec "print ok"
```

**Expected**: the agent performs a backend-requiring operation. Then confirm the
key is not on any command line, not literal in the compose file, not in an image
layer, not on a persistent volume (SC-003). *(Tokened — never in CI.)*

## Scenario E — Credential off every observable surface (US2, FR-011/SC-003)

```bash
agent-container up acme
ps -ef | grep -i "sk-\|api_key" || echo "not on argv"
grep -RiE "sk-|PRIVATE KEY" ~/.local/state/agent-container/*/acme.compose.yaml || echo "not inlined"
docker image history localhost/agent-container:latest | grep -i key || echo "not baked"
```

**Expected**: no secret on argv, no secret inlined in the deployment description,
no secret in an image layer.

## Scenario F — Canonical config fresh; runtime state persists (US3, FR-007/008/SC-005)

```bash
mkdir -p agent-container.acme.config/.claude
echo '{"model":"opus"}' > agent-container.acme.config/.claude/settings.json
agent-container up acme
# edit locally, redeploy:
echo '{"model":"sonnet"}' > agent-container.acme.config/.claude/settings.json
agent-container redeploy acme
agent-container attach acme && cat ~/.claude/settings.json          # -> sonnet (fresh)
# runtime state survives recreation:
# (write history in the container) then:
agent-container down acme && agent-container up acme
# -> prior history still present from the -claude volume
```

**Expected**: the edited canonical file reflects in the container after redeploy;
previously-written runtime state survives recreation.

## Scenario G — Rotation + missing-material fail-fast (US4, FR-015/016, SC-006/007)

```bash
# rotation:
agent-container redeploy acme          # after editing a local secret -> new value in effect, old copy gone
# fail-fast:
agent-container up beta --push-key ~/does-not-exist
```

**Expected**: rotation takes effect with no baked/persisted copy of the old value;
the missing-key deploy **fails before the container is created** (no
partially-credentialed agent runs).

## Success signal

All scenarios pass with every secret injected at runtime, ephemeral where
FR-012 applies, absent from argv / image / deployment description / persistent
volumes, delivered only to the one deployment that needs it, and rotatable by a
local edit + redeploy — matching SC-001…SC-008.
