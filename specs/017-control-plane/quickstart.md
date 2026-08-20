# Quickstart: Control-Plane Container

**S1, S4 and S9 are the ones that matter.** S1 is the feature; S4 is the secret that must exist
nowhere; S9 is the check that stays green while an image goes unexamined.

Prerequisites: a checkout, `uv`, a container runtime, and a second device with an SSH client.

---

## S1 — Manage from a device with nothing installed (C1, FR-002, SC-001)

```sh
agent-container up cp1 --role control-plane --hosts local
agent-container ssh-key show cp1          # authorise this where cp1 must reach
# then, from a phone or a borrowed laptop:
ssh dev@<host> -p <port>
agent-container list
agent-container stop some-env
```

**Expect**: a working, configured CLI on arrival — no configuration on that device. **This is the
feature**; anything less is an empty container.

## S2 — An unreachable host is named, not omitted (C2, SC-002)

Register a host at an unroutable address, then from inside `cp1`:

```sh
agent-container list --json | jq -r '.data.unreachable_hosts[]?'
```

**Expect**: the host named. A short list that looks complete is worse than an error — the operator
acts on absence.

## S3 — The private key never leaves, and no channel accepts one (C3, FR-007)

```sh
agent-container exec cp1 -- ls -l ~/.ssh/id_ed25519
agent-container exec cp1 -- head -1 ~/.ssh/id_ed25519   # must show it is ENCRYPTED
grep -rl "PRIVATE KEY" ~/.local/state/agent-container ~/.config/agent-container || echo "clean"
```

**Expect**: `0600`, encrypted at rest, and `clean` on the operator's disk.

## S4 — The passphrase exists NOWHERE but your password manager (C4)

Capture it at deploy, then hunt for it everywhere:

```sh
PASS='<the passphrase printed once>'
grep -rl "$PASS" ~/.local/state/agent-container ~/.config/agent-container ~/.local/share/agent-container
agent-container runs show --json | grep -c "$PASS"
docker logs agent-container-cp1 2>&1 | grep -c "$PASS"
agent-container list --json | grep -c "$PASS"
```

**Expect**: no files, and `0` from every count. **Verified by hunting, not by reading the print
statement** — this is the narrow Constitution III exception in this feature, and the only proof is
absence.

## S5 — Locked when nobody is attached; usable again after reboot (C5, FR-012)

```sh
agent-container stop cp1 && agent-container start cp1
ssh dev@<host> -p <port>     # supply the passphrase again
agent-container list
```

**Expect**: it comes back **locked**, and works once the passphrase is supplied. No reconfiguration,
and no need for the operator's own machine.

## S6 — Deploying grants nothing (C6, FR-007b)

Deploy `cp2` and, **without authorising its key anywhere**, try to reach a host:

```sh
agent-container up cp2 --role control-plane --hosts local
ssh dev@<host> -p <port2> -- agent-container list
```

**Expect**: it reaches nothing. Capability begins where the public key is authorised — which is what
makes nesting safe and revocation meaningful.

## S7 — Revocation is one command (C7, SC-005)

```sh
agent-container revoke cp1
ssh dev@<host> -p <port> -- agent-container list      # from inside cp1
```

**Expect**: access ended, without editing N hosts by hand.

## S8 — Stop-everything from inside excludes itself, and SAYS SO (C9, SC-010)

```sh
ssh dev@<host> -p <port>
agent-container panic --destroy -y ; echo "exit=$?"
agent-container list          # cp1 must still be here
```

**Expect**: `cp1` reported as **excluded** — explicitly, naming how to stop it instead — and still
running. A silent skip is not a pass: only the report is checkable, and it is the one container whose
stopping makes the report undeliverable.

## S9 — The second image has NO agents, and the census covers it (C12, SC-009)

Two halves, and the second is the one that rots:

```sh
# the built image, not the build definition
docker run --rm --entrypoint sh localhost/agent-container-control-plane:latest \
  -c 'for a in claude codex pi opencode; do command -v $a && echo "LEAK: $a"; done; echo done'

# and the source census must cover EVERY Dockerfile
uv run --no-project --with pytest ... pytest bin/tests/test_pure_logic.py -k dockerfile
```

**Expect**: no agent on the PATH, and the census **parameterised over every Dockerfile, failing on
one it has no expectation for**. The existing test hardcodes `image/Dockerfile`, so a second image is
invisible to it — the suite stays green while the container holding keys to everything goes
unchecked. Add a third Dockerfile with no expectation and confirm the test **fails**.

## S10 — Version mismatch: silent on patch, refused in one direction (C10, SC-012)

```sh
# control plane one PATCH ahead of an environment
agent-container list                 # expect: NOTHING said about versions
# environment newer than the control plane, across a minor (pre-1.0 = breaking)
agent-container stop that-env        # expect: REFUSED, naming redeploy as the remedy
```

**Expect**: silence on patch; advisory when the control plane is newer; **refusal** when the
environment is newer. `major_on_zero = false`, so pre-1.0 MINOR is the breaking channel.

## S11 — Legible at 80 columns (C11, SC-007)

```sh
stty cols 80; agent-container list; agent-container doctor
```

**Expect**: readable without horizontal scrolling. The motivating client is a phone.

## S12 — Telemetry reaches a collector, from an agent, with no control plane (C13, C16, SC-018)

```sh
docker run -d --name otelcol -p 4318:4318 otel/opentelemetry-collector:latest
# declare the endpoint, deploy a plain AGENT environment, run something
agent-container up plain --task "echo hello" --mode headless
docker logs otelcol | grep -c "plain"
```

**Expect**: the agent's record at the collector **with no control plane deployed**. This is the half
that gets missed if export is built as control-plane plumbing.

## S13 — `task` present by default, absent when excluded — BOTH positions (C13, SC-017)

```sh
agent-container up t1 --task "MARKER-9f3a-do-not-leak" --mode headless
docker logs otelcol | grep -c "MARKER-9f3a"          # expect: >= 1  (default: included)

# now declare the task text excluded, and repeat
agent-container up t2 --task "MARKER-9f3a-do-not-leak" --mode headless
docker logs otelcol | grep -c "MARKER-9f3a"          # expect: 0
```

**Expect**: present, then absent. **Both positions**, because a switch verified in one position may
not be wired at all. Checked at the **receiver**, never by reading the export code.

## S14 — Export is fail-open, and the gap is reported (C15)

Point the endpoint at an unroutable address, or leave the collector undeclared under enforced egress:

```sh
agent-container up f1 --task "work" --mode headless ; echo "exit=$?"
```

**Expect**: the work completes, exit `0`, and the export gap is **reported**. Silence here yields an
empty collector that reads exactly like a quiet system.

## S15 — Correlation survives the exclusion (C17, SC-019)

```sh
RID=$(docker logs otelcol | jq -r 'select(.environment=="t2") | .run_id' | head -1)
agent-container runs show "$RID" | grep -c MARKER-9f3a
```

**Expect**: `1` locally. The run id always exports, so omitting the task text costs nothing but the
convenience of seeing it in the dashboard.

## S16 — Collect works with AND without an endpoint (C-command, FR-009e, SC-015)

```sh
agent-container telemetry collect          # no endpoint configured
# then declare an endpoint and repeat:
agent-container telemetry collect          # endpoint configured
```

**Expect**: both times — the trail gathered from every reachable host, and **every unreachable host
named**. A collection that silently skipped one reads as complete.

**Run it in both configurations, deliberately.** The local record exists unconditionally (FR-009a),
so its retrieval must too; a `collect` that only works without an endpoint would leave an operator
who configured OTLP holding logs with no way to download them.

---

## What "done" looks like

**S4 and S9 are the ones that will be got wrong.** S4 is an absence — the passphrase existing nowhere
— and an absence is what working output never demonstrates. S9 is a test that keeps passing while an
entire image goes unexamined, which is this project's most repeated defect and the one the spec
predicted backwards.

S6 is the quiet load-bearer: if deploying granted anything, nesting and revocation both stop meaning
what the spec says they mean.
