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

## Validation record (T026)

Each scenario above is codified across three automated tiers — hermetic unit
tests (`bin/tests/test_credentialing.py`, no runtime), the entrypoint shell
harness (`bin/tests/test_entrypoint.sh`), and the real-container acceptance tier
(`pytest -m acceptance bin/tests/test_acceptance.py`). The acceptance tests run
in CI with **dummy** credentials (they exercise delivery/wiring/ephemerality, not
a real backend or remote); the parts that need a **real** git remote or model
backend are the **opt-in/tokened** extensions, outside the CI cost boundary.

| Scenario | Hermetic unit | Shell harness | Acceptance (real container) | Opt-in/tokened extension |
|----------|---------------|---------------|-----------------------------|--------------------------|
| **A** — non-interactive push (SC-001) | `test_stage_push_injection_stages_ephemeral_entries`, `test_do_up_threads_push_material` | push section (`core.sshCommand` + `IdentitiesOnly`) | `test_push_credential_ephemeral_and_distinct` (wiring) | **zero-prompt push to a real remote** |
| **B** — two keys distinct (SC-008) | `test_push_key_distinct_from_host_key` | push key ≠ host key, not on volume | `test_push_credential_ephemeral_and_distinct` (distinct fingerprints) | — |
| **C** — push key leaves no durable copy (FR-012/SC-004) | `test_no_secret_value_inlined_in_compose_model` | key **not** written to `~/.ssh` volume | `test_push_credential_ephemeral_and_distinct` (only under `/run`) | — |
| **D** — API cred reaches backend (SC-002) | `test_discover_apikey_files_*`, `test_stage_apikey_injection_ephemeral_target` | apikey section (Claude helper, Codex/pi `$HOME` redirect) | `test_apikey_injection_ephemeral_and_off_volume` (delivery) | **real backend-reaching call** |
| **E** — off every surface (SC-003) | `test_apikey_value_never_inlined_in_compose_model`, `test_apikey_env_delivery_unaffected` | value not on the `~/.claude`/`~/.codex` volume | `test_apikey_injection_ephemeral_and_off_volume` (argv/compose/volume) | — |
| **F** — canonical fresh; runtime persists (SC-005) | `test_discover_canonical_config_*`, `test_stage_config_injection_targets`, `test_compose_up_exec_threads_canonical_config` | canonical-copy on boot | `test_canonical_config_fresh_redeploy_runtime_state_persists` | — |
| **G** — rotation + fail-fast (SC-006/007) | `test_missing_*_dies_before_any_compose_call`, `test_all_material_staged_locally_before_compose_up`, `test_per_repo_deploy_key_is_just_a_narrower_push_key` | — | `test_secret_rotation_new_value_in_effect_old_gone` | **per-repo deploy key scope** against a real remote (FR-004) |

Secret-bearing config classification (FR-009, the Scenario-F secret sub-case) is
pinned by `test_discover_canonical_config_marks_secret_bearing`.
