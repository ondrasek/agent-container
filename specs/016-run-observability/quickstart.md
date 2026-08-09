# Quickstart: Run Observability (Feature 016)

Runnable validation. Each step names what it proves and **what a wrong answer looks like**, because
several of these fail in ways that resemble success.

**Prerequisites**: a working `agent-container` install, a container runtime, and an environment you
are willing to destroy.

---

## S1 — A headless run leaves a record

```bash
agent-container up demo --mode headless --agent claude --task "print ok" --foreground
agent-container runs list demo
```

**Expected**: one record, with an outcome from the headless vocabulary. (C1)

---

## S2 — The record survives teardown — the feature itself

```bash
agent-container down demo --purge -y
agent-container runs list demo
```

**Expected**: the record is **still there**. (C3, FR-001, SC-001)

If it is gone, nothing else in this feature matters — stop here.

---

## S3 — A DETACHED run is ingested on next contact

```bash
agent-container up demo2 --mode headless --agent claude --task "print ok"   # no --foreground
# ... the CLI is not attached when this ends ...
agent-container runs list demo2
```

**Expected**: the record is present after the next command touches that host. (SC-002a)

This is the case the whole design is shaped around — detached is the *default* headless mode, and a
design that only recorded foreground runs would miss it.

---

## S4 — A killed run still records

```bash
agent-container up demo3 --mode headless --agent claude --task "sleep 600"
docker kill "$(agent-container status demo3 --json | jq -r .container)"
agent-container runs list demo3
```

**Expected**: a record with `outcome: stopped`. (C5, SC-008)

**A wrong answer that looks right**: no record at all. `docker kill` sends SIGKILL, which runs no
trap — the pending record written at *start* is what makes this survivable. If S4 produces nothing,
the start-side write is missing, and every abnormal run is being lost silently.

---

## S5 — Commit-without-push is loud

```bash
# in a run that commits but does not push
agent-container runs show <run-id>
agent-container runs show <run-id> --json | jq '.repository | {commits, pushed}'
```

**Expected**: `pushed: false`, flagged visibly in both renderings. (C8, FR-005, SC-003)

**Check the distinction**: with no upstream configured, `pushed` must be **`null`**, not `false`.
`false` means "committed and did not push" — the failure Constitution I exists to prevent — and
conflating it with "could not tell" makes the loudest signal in the feature unreliable.

---

## S6 — The repository states are records, not errors

```bash
# an ephemeral workspace with no clone
agent-container runs show <run-id> --json | jq -r '.repository.state'
```

**Expected**: `no-repository` — not `null`, not an error, not a crash. (C7)

Research R4 measured the three ordinary states that must each be reportable: no upstream
(`git rev-parse @{u}` exits 128), detached HEAD (`symbolic-ref -q` exits 1), and no repository
(exits 128).

---

## S7 — Unknown usage is unknown, not zero

```bash
agent-container runs show <run-id> --json | jq '.usage'
```

**Expected**: `{"reported": false}` for an agent that reported nothing. (C9, SC-004)

**A wrong answer that looks right**: `0`. A false zero silently understates every total it enters,
and a total that is quietly wrong is worse than one that admits a gap.

---

## S8 — An interactive session cannot be `finished`

```bash
agent-container up demo4 --agent claude   # interactive
agent-container attach demo4              # then detach
agent-container runs list demo4 --json | jq -r '.[]?.outcome // .runs[].outcome'
```

**Expected**: `ended`. Never `finished` or `failed` — a session has no completion semantics.
(C5, FR-003, SC-002)

---

## S9 — Teardown ingests BEFORE it removes

```bash
agent-container up demo5 --mode headless --agent claude --task "print ok"
agent-container down demo5 --purge -y      # the record is still pending on the volume
agent-container runs list demo5
```

**Expected**: the record survives. (C4, FR-001b)

**Ordering is the property.** A drain that runs after volume removal is not a late drain, it is no
drain — and the environment being destroyed is the single most likely moment for the record to
matter.

---

## S10 — Concurrency loses nothing

```bash
for n in c1 c2 c3 c4 c5; do
  agent-container up "$n" --mode headless --agent claude --task "print $n" &
done; wait
for n in c1 c2 c3 c4 c5; do agent-container runs list "$n" --json | jq '.runs | length'; done
```

**Expected**: `1` for each — five complete, non-interleaved records. (C12, SC-006)

---

## S11 — The record does not pretend to be the logs

```bash
agent-container runs show <run-id>
```

**Expected**: the record is a summary and points at `logs` for detail. (C15, FR-014)

---

## S12 — The task text is recorded verbatim, and you were told

```bash
agent-container runs show <run-id> --json | jq -r '.task'
```

**Expected**: exactly what was passed to `--task`.

This is the one free-text field and the one place a credential can arrive (research R9,
`docs/threat-model.md`). Every other field is tool-generated or git-derived. The tool does **not**
redact: a redactor that misses one value converts caution into misplaced confidence. Do not put
credentials in a task.


---

## S13 — Which of these runs changed this file? (SC-007)

```bash
# after at least five runs against one environment
agent-container runs list demo --changed src/auth/session.py
agent-container runs list demo --changed src/auth/session.py --json | jq -r '.runs[].run_id'
```

**Expected**: exactly the runs that touched that file, newest-first — verified with **N ≥ 5** runs
present. (C16, SC-007)

**It must work with the repository absent.** Delete or move the clone and run it again: the answer
is unchanged, because the paths were captured when the run ended rather than resolved from SHAs now
(research R11). The same property is why a later rebase does not erase the answer.

**A wrong answer that looks right**: a confident empty result. If any candidate record has
`paths_truncated: true`, the command must say the answer is uncertain rather than report nothing
found — the path may have been in the part that was cut.
