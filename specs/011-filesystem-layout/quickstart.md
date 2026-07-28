# Quickstart: Validating the Filesystem Layout

**Feature**: 011-filesystem-layout | **Date**: 2026-07-27

Runnable validation. Contract detail is in
[contracts/layout-contract.md](./contracts/layout-contract.md); the move table is in
[data-model.md](./data-model.md).

## Prerequisites

- A container runtime with Compose v2 (Podman on Linux, Docker on macOS).
- A checkout — `build` needs one.
- A second host registered (or a remote context) for the remote-build scenario.

---

## Tier 1 — Gate (hermetic, no container)

```bash
scripts/quality-gate.sh
```

Covers, for this feature:

- `--self-test` doctests — **identity unchanged** (C6): container name, port corpus, and all nine
  volume **names**
- resolution order, project then user (C2)
- the refusal firing on superseded names and **not** on `./.env` (C3)
- the checkout marker recognising `image/Dockerfile` (C4)

---

## Tier 2 — Real container (acceptance)

```bash
pytest -m acceptance bin/tests
```

### S1 — Identity is byte-identical (C6, SC-003) — run this first

```bash
agent-container list --json          # before and after the change, same names
```

**Expected**: container name, port and all nine volume names identical. **If any name differs,
stop** — the feature has violated its own binding constraint and nothing else matters.

### S2 — A consolidated project deploys (US1, C2)

```bash
mkdir -p .agent-container
printf 'FOO=bar\n' > .agent-container/dev.env
agent-container up dev
```

**Expected**: deploys, and the env file is picked up from the project level.

### S3 — Discovery works from a subdirectory (C1)

```bash
mkdir -p src/deep/nested && cd src/deep/nested
agent-container status
```

**Expected**: identical result to running from the project root.

### S4 — Superseded files are refused, not ignored (C3) — the safety case

```bash
printf 'sk-ant-xxx' > ./agent-container.dev.anthropic.key   # the OLD location
agent-container up dev
```

**Expected**: **refuses**, naming the file and where it belongs. It must **not** deploy an agent
without the credential. Silent success here is the failure this whole requirement exists to
prevent.

```bash
rm -f .agent-container/dev.env                 # no agent-container env resolves
printf 'GH_TOKEN=x\n' > ./.env
agent-container up dev
```

**Expected**: **refuses** — otherwise the token silently never reaches the container.

```bash
printf 'FOO=bar\n' > .agent-container/dev.env  # an agent-container env DOES resolve
agent-container up dev
```

**Expected**: **deploys, no refusal** — the stray `./.env` may be Compose's and is not ours to
complain about.

### S4a — An explicit env file, anywhere, stacking in order (C2a)

```bash
printf 'A=1\nB=1\n' > ~/.env
printf 'B=2\n'       > /tmp/override.env
agent-container up dev -e ~/.env -e /tmp/override.env
```

**Expected**: deploys with `A=1` and **`B=2`** — later `-e` wins. The discovery chain is not
consulted. Repeat against a **remote** host: it must behave identically, because compose reads
env files client-side.

```bash
agent-container up dev -e /tmp/nope.env
```

**Expected**: fails fast, naming the missing path.

Then confirm no value leaked into the generated artifact:

```bash
grep -r "B=2" "$XDG_STATE_HOME/agent-container/"      # expect: no hits
```

### S4b — Plaintext credentials are user-level only (C2b, FR-001f)

```bash
printf 'sk-ant-xxx' > .agent-container/dev.anthropic.key    # inside the committed directory
agent-container up dev
```

**Expected**: the key is **not discovered**. `.agent-container/` travels with the repository and
Feature 008 settled that the repo holds a locator, never a value — so the directory holds no
secret values, and the tool does not teach operators to put one there.

```bash
rm .agent-container/dev.anthropic.key
printf 'sk-ant-xxx' > ~/.config/agent-container/dev.anthropic.key
agent-container up dev
```

**Expected**: discovered and injected, as before. Confirm it reaches the agent and appears on no
volume.

### S5 — The build context contains only the image sources (US2, C4)

```bash
agent-container build agent-container:test          # local
agent-container up dev --host <remote>              # remote — context crosses the network
```

**Expected**: both succeed. Inspect the transferred context: **only** `image/` contents. This is
the scenario that matters most — a remote build ships the context to someone else's daemon.

### S6 — A tree without image sources fails clearly (C4)

```bash
cd /tmp/not-a-checkout && agent-container build foo:bar
```

**Expected**: names what was expected (`image/Dockerfile`) and where — **not** a traceback, and
not a confusing "no checkout" message while standing inside one.

### S7 — Shell env survives the mount-point move (C5)

```bash
agent-container attach dev     # inside: echo 'export X=1' >> ~/.agent-env/env
agent-container down dev
agent-container up dev
agent-container attach dev     # inside: cat ~/.agent-env/env  → still there
```

**Expected**: content persists. The volume name never changed, so this is a relocation, not a
migration. Also confirm `dev` can **write** the new mount point — that is the Feature 010 trap.

### S8 — Full teardown leaves nothing (FR-011)

```bash
agent-container wipe dev -y
<runtime> volume ls | grep agent-container-dev    # expect: no output
```

---

## Tier 3 — Documentation (FR-014, SC-006)

```bash
grep -rn "project directory" docs/ CLAUDE.md README.md     # expect: no hits
grep -rn "agent-container\.<name>\." docs/ README.md        # expect: migration notes only
```

**Expected**: one authoritative layout map; the settled vocabulary used consistently.

---

## Definition of done

| Check | Source |
|---|---|
| Identity byte-identical | S1 — **the blocking one** |
| Gate green | Tier 1 |
| S2–S8 pass | Tier 2 |
| One layout map, no superseded names | Tier 3 |
| Commit marked breaking | `!` / `BREAKING CHANGE` (research R8) |
