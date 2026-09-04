# Quickstart: validating the telemetry stack

Runnable checks that prove the feature works end to end. Each maps to a success criterion; the
command output, not the code, is the evidence.

## Prerequisites

- A working runtime (docker or podman) and a host the tool can deploy to.
- Network access to pull the stack image on first run (~1GB).
- For the last scenario only: a real agent credential, as the existing real-agent tier requires.

---

## 1. Nothing to something (SC-001, SC-002)

```sh
agent-container telemetry stack up obs
```

**Expect**: a pull is reported; the command returns only once the ingest accepted a record; the
resolved bind addresses are printed; an `otlp_endpoint` line is printed.

**Verify independently** — that the printed endpoint is the one that works:

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$(agent-container telemetry stack url obs --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["otlp_endpoint"])')" \
  -H 'Content-Type: application/json' -d '{"resourceLogs":[]}'
```

**Expect**: `200`.

---

## 2. The endpoint is the agent's, not yours (SC-003)

Put the printed `otlp_endpoint` into `settings.yaml`, change nothing else, run any environment, then
read it back **through the stack**:

```sh
agent-container up demo --mode headless --agent claude --foreground --task "write /workspace/x.txt"
agent-container telemetry stack url obs        # take the UI address
# query the stack's own API for records from that run
```

**Expect**: the run's records are present. This is the scenario that fails if the operator-facing and
container-facing addresses were conflated — and it fails **silently**, which is why it is a
first-class check rather than an afterthought.

---

## 3. Views without building them (SC-004)

Open the UI address. **Expect**: the tool's dashboards present with no import step, and the run view
answering "what did this run do" for the run from scenario 2 — its agent activity and its container's
resource usage together.

Then break and repair them:

```sh
# delete a dashboard through the UI, then:
agent-container telemetry stack dashboards obs
```

**Expect**: restored, per-dashboard outcome reported, the stack never restarted and the data from
scenario 2 still queryable.

---

## 4. Exposure is a decision, not an accident (SC-005)

```sh
agent-container telemetry stack up obs2                       # default level
```

**Expect**: reachable from the host and from a container on it; **not** from another machine.

```sh
agent-container telemetry stack up obs3 --exposure network
```

**Expect**: refused without `-y` on a non-TTY; with `-y`, a stated warning that the UI is
unauthenticated, shows verbatim task text, and the ingest accepts from anyone who can reach it — and
then reachable from another machine.

---

## 5. Several, and clean removal (SC-006)

```sh
agent-container telemetry stack up a
agent-container telemetry stack up b
agent-container telemetry stack ls
agent-container telemetry stack remove a -y
agent-container telemetry stack ls
```

**Expect**: both run concurrently with distinct ports; after removal `a` is gone and `b` is still
serving; `a`'s collected data is retained (no `--purge`).

Name-collision check:

```sh
agent-container up b            # b is a stack
```

**Expect**: refused, naming the kind that holds the name.

---

## 6. The kill switch knows about it (SC-007)

```sh
agent-container telemetry stack up k
agent-container panic --yes
agent-container telemetry stack ls
```

**Expect**: `k` stopped. On an unreachable host: `undetermined`, never `stopped`.

---

## 7. It is remembered (SC-008)

```sh
agent-container inventory ls --json
```

**Expect**: every stack ever created appears with `kind` and its outcome — including ones already
removed.

---

## 8. Restart keeps the trail (FR-007)

```sh
agent-container telemetry stack remove obs -y     # or stop the container out of band
agent-container telemetry stack up obs
```

**Expect**: when the container exists but is stopped, `up` says it **restarted** an existing stack,
and the data collected before is still queryable.
