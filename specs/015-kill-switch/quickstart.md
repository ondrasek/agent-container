# Quickstart: Validating the Kill Switch (Feature 015)

Runnable scenarios. Each names the contract (`C#`) and criterion (`SC-###`) it validates.
Requirements and field detail live in [spec.md](./spec.md), [data-model.md](./data-model.md) and
[contracts/](./contracts/kill-contract.md).

**Prerequisites**: a working runtime, at least two registered hosts (one of which you can make
unreachable), and a populated inventory — Feature 014 must have recorded the environments.

**Read S2 first.** It is the one scenario whose failure is invisible in an otherwise green run.

---

## S1 — Everything stops (C1, SC-001)

```sh
agent-container up alpha && agent-container up beta
agent-container kill
agent-container list
```

**Expect**: both stopped, exit `0`, and a per-environment report. Nothing needed a confirmation
prompt — the stopping form is recoverable and speed is its value.

## S2 — An unreachable host is UNDETERMINED, never stopped (C3, SC-002)

**The scenario this feature exists for.** Deploy to two hosts, make one unreachable (drop its network,
stop its daemon, or point its context at a dead endpoint), then:

```sh
agent-container kill --json | jq '.data.results[] | {name, host, outcome}'
echo "exit=$?"
```

**Expect**: the reachable host's environments `stopped`; the unreachable host's environments
`undetermined`; **zero** entries on the unreachable host reported `stopped`; overall **non-zero** exit.

**Fails if** the unreachable host's environments are reported `stopped` or omitted entirely. Both look
like success from the summary line, which is why this scenario asserts on the per-environment data.

## S3 — One failure does not abort the rest (C2)

Same setup as S2.

**Expect**: the reachable host's environments are stopped **even though** the other host failed. A run
that aborts on the first failure leaves an operator worse off than doing it by hand.

## S4 — Bounded by the slowest host, not the sum (C5, SC-002a)

With N hosts, one unreachable, time the invocation:

```sh
time agent-container kill --host-timeout 10
```

**Expect**: roughly one timeout, **not** N. With three hosts and a 10s timeout, ~10s and not ~30s.

## S5 — `stopped` was OBSERVED (C4, SC-002b)

```sh
agent-container kill --json | jq '.data.results[] | select(.outcome=="stopped")'
docker ps --filter "name=agent-container-" --format '{{.Names}}'
```

**Expect**: every environment reported `stopped` is absent from the **running** listing. The container
still exists (`docker ps -a` shows it) — that is correct for a stop, and verifying against `ps -a`
would wrongly report failure.

## S6 — Incomplete means failure (C6, SC-003)

Any run from S2.

**Expect**: non-zero exit and an explicit statement that something was not stopped or not confirmed.
**Zero** runs may report success while anything is unstopped or undetermined.

## S7 — Stop preserves volumes; destroy asks first (C7, SC-005, SC-006)

```sh
agent-container kill                       # stop
docker volume ls | grep agent-container-   # volumes intact

agent-container kill --destroy             # no -y
echo "exit=$?"
docker volume ls | grep agent-container-   # STILL intact
```

**Expect**: after the stopping form, all volumes present. The destroying form without confirmation
exits non-zero having destroyed **nothing**.

## S8 — Preview affects nothing (C9, SC-007)

```sh
docker ps -a --format '{{.Names}} {{.Status}}' | sort > /tmp/before
agent-container kill --preview
docker ps -a --format '{{.Names}} {{.Status}}' | sort > /tmp/after
diff /tmp/before /tmp/after && echo "unchanged"
```

**Expect**: identical, and the preview listed exactly what a real run would target.

## S9 — A container we did not create is untouched (C10, SC-004)

```sh
docker run -d --name agent-container-impostor alpine sleep 300
agent-container kill
docker ps --filter "name=agent-container-impostor" --format '{{.Names}}'
```

**Expect**: `agent-container-impostor` **still running**. It matches the naming convention and is
absent from the inventory, so it is not ours — Feature 014 reported such containers without claiming
them, and this feature must not act on them.

## S10 — Repeatable (C11, SC-008)

```sh
agent-container kill && agent-container kill; echo "exit=$?"
```

**Expect**: the second run exits `0`, reporting `already-stopped`. Nothing to stop is an unambiguous
success, not an error.

## S11 — Scope, and what it excluded (C12)

```sh
agent-container kill --host vps1
agent-container kill --host nosuchhost
```

**Expect**: the first affects only `vps1`'s environments and **says what it excluded**. The second
says the scope matched nothing rather than silently doing nothing.

## S12 — Unreadable refuses; empty succeeds (C14, SC-009)

```sh
chmod 000 "${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/inventory"
agent-container kill; echo "exit=$?"          # REFUSES, naming the store
chmod 755 "${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/inventory"

mv .../inventory .../inventory.bak
agent-container kill; echo "exit=$?"          # succeeds: "nothing recorded"
```

**Expect**: unreadable → non-zero refusal naming the store, and **no** fallback to live enumeration.
Absent → exit `0` saying *nothing recorded* — and saying that this means nothing **recorded**, not
nothing **exists**. Confusing those at this moment reads as reassurance.

---

## What "done" looks like

**S2 is the feature.** A kill switch that stops the reachable things and says so is easy; one that
tells the truth about the host it could not reach is the whole point. S5 and S6 are its supports:
without observation, `stopped` is a guess, and without a non-zero exit, an incomplete run ends the
investigation.
