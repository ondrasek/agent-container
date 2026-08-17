# Quickstart: `doctor` — Preflight Validation

Runnable scenarios that prove the feature. **S1 and S5 are the ones that matter** — the first
because read-only is the whole premise, the second because a diagnostic that fails open is worse
than none.

Prerequisites: a checkout, `uv`, and a container runtime. Where a scenario needs a broken project,
it says how to break it.

---

## S1 — It changes NOTHING (C1, FR-002, SC-002)

The gate. Land it before any check is built out, or it gets written later to pass whatever exists.

```sh
cd <a project with .agent-container/>
find . ~/.local/state/agent-container ~/.config/agent-container -type f -exec shasum {} \; \
  | sort > /tmp/before
docker ps -a --format '{{.Names}}' | sort >> /tmp/before
docker volume ls --format '{{.Name}}' | sort >> /tmp/before

agent-container doctor

find . ~/.local/state/agent-container ~/.config/agent-container -type f -exec shasum {} \; \
  | sort > /tmp/after
docker ps -a --format '{{.Names}}' | sort >> /tmp/after
docker volume ls --format '{{.Name}}' | sort >> /tmp/after
diff /tmp/before /tmp/after && echo "CLEAN"
```

**Expect**: `CLEAN`. Zero difference.

**Run it against a project on the pre-011 layout too** — that path is where a deploy would call
`migrate_flat_state()`, which relocates files and reads as harmless.

## S2 — Every problem in one pass (C2, FR-003, SC-001)

Break three things at once: rename `.agent-container/` to the pre-011 layout, point a credential
at a nonexistent file, and register a host that does not answer.

```sh
agent-container doctor; echo "exit=$?"
```

**Expect**: **all three** named in one run. Not the first. Not one per run.

## S3 — Every finding names a remedy (C3, FR-004, SC-003)

```sh
agent-container doctor --json | jq -r '.data.findings[] | select(.remedy == null or .remedy == "")'
```

**Expect**: empty. A finding without a remedy is a defect, not a terse finding.

## S4 — The layout remedy is byte-identical to the deploy's (C4, SC-008)

```sh
agent-container doctor --json | jq -r '.data.findings[] | select(.check_id=="layout") | .remedy' > /tmp/d
agent-container up demo 2>&1 | tail -5 > /tmp/u    # fails on the same layout
grep -F -f /tmp/d /tmp/u && echo "SAME STRING"
```

**Expect**: `SAME STRING`. Not "similar wording" — the same text, because it comes from the same
producer.

## S5 — A check that cannot complete is `unknown`, never `pass` (C5, FR-006)

Register a host at an unroutable address (`10.255.255.1`) so the reachability check cannot answer.

```sh
agent-container doctor --json | jq -r '.data.checks[] | select(.id=="host-reachability") | .status'
```

**Expect**: `unknown`. Never `pass`.

**This is the scenario the feature exists to get right.** A diagnostic reporting healthy is what
stops an operator looking further.

## S6 — Advisory does not fail the run; blocking does (C6, C7, FR-011, SC-004)

```sh
# advisory only (e.g. a stale image, everything else fine)
agent-container doctor; echo "advisory exit=$?"     # expect 0
agent-container doctor && agent-container up demo   # expect the chain to PROCEED

# now a blocking problem (pre-011 layout)
agent-container doctor; echo "blocking exit=$?"     # expect 1
```

**Expect**: `0` then `1`. `doctor && up` must stay viable, or the command stops being run.

## S7 — Exit codes never exceed 2 (C7, R4)

```sh
for scenario in healthy advisory blocking broken-invocation; do : ; done
agent-container doctor --json | jq -r '.data.exit_code'
```

**Expect**: only `0`, `1` or `2` — ever. **`3` means *pending registration* tool-wide** (Feature
019, in `--help` and pinned by a test). A `doctor` returning 3 tells an automated caller something
false about an SSH key.

## S8 — No prompt (C8, FR-009)

Declare a credential with `source: onepassword` against an **approval-gated** item.

```sh
agent-container doctor
```

**Expect**: it returns without any system dialog. The credential check reports the resolver
binary's presence, and *unknown* beyond that.

**Watch the screen, not just the exit code** — this is the one scenario whose failure is a UI
event a test cannot see.

## S9 — No credential value anywhere (C9, FR-010, SC-006)

```sh
agent-container doctor --json | grep -F "$(cat ~/.config/agent-container/demo.anthropic.key)" \
  && echo "LEAK" || echo "clean"
agent-container doctor 2>&1 | grep -F "$(cat ~/…/demo.anthropic.key)" && echo "LEAK" || echo "clean"
```

**Expect**: `clean` both times. By design the value is never *retrieved*, which is stronger than
never printed.

## S10 — One bad check does not silence the rest (C10, C12, FR-008, SC-005)

With one unreachable host registered alongside a reachable one:

```sh
agent-container doctor --json | jq -r '.data.checks[] | select(.id=="host-reachability") | "\(.entity): \(.status)"'
```

**Expect**: both hosts listed — one `pass`, one `unknown`/`fail` as unreachable. Never one host
suppressing the other, and never the unreachable one silently absent.

## S11 — Outside a project it still works (C11, FR-007)

```sh
cd /tmp && agent-container doctor; echo "exit=$?"
```

**Expect**: machine-level checks reported, a plain statement that no project was found, and exit
**0** if the machine is fine. **Not an error** — this is US3's scenario, a new machine.

## S12 — Image freshness, and unstamped means unknown (C13, FR-012a/b)

```sh
# an image built BEFORE stamping shipped
agent-container doctor --json | jq -r '.data.checks[] | select(.id=="image-freshness") | .status'
# expect: unknown

agent-container build
agent-container doctor --json | jq -r '.data.checks[] | select(.id=="image-freshness") | .status'
# expect: pass
```

Then confirm the label is real and local:

```sh
docker image inspect localhost/agent-container:latest \
  --format '{{index .Config.Labels "org.opencontainers.image.version"}}'
```

**Expect**: the building CLI's version — and **never** `0.0.0+unknown`. When the version cannot be
resolved the label is **omitted**, landing the image in the *unknown* bucket where it belongs.

## S13 — A healthy environment's own port is not a conflict (C14, R10)

```sh
agent-container up demo
agent-container doctor demo --json | jq -r '.data.checks[] | select(.id=="port-availability") | .status'
```

**Expect**: `pass`. The port is derived from the name, so a running environment always holds
"its" port — reporting that as a conflict would fail `doctor` on every healthy deployment.

## S14 — All clear is brief (C16, FR-014, SC-007)

```sh
agent-container doctor | wc -l
```

**Expect**: one screen. Findings plus a one-line summary of the passes — not a wall of green.
The `--json` view still carries every check, including passes, because a program cannot otherwise
tell "checked and fine" from "never asked".

---

## What "done" looks like

**S1 and S5 are the point.** S1 is an absence — nothing changed — and an absence is the one thing a
working report never demonstrates. S5 is the difference between a diagnostic and a false
reassurance.

S4 is the one that rots quietly: two remedy strings agree on the day they are written and drift
invisibly afterwards, because both still read correctly on their own.
