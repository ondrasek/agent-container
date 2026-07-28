# Contract: Filesystem Layout

**Feature**: 011-filesystem-layout | **Date**: 2026-07-27

The externally-observable contracts this feature changes. Each is testable without reading the
implementation.

---

## C1. Project discovery

| Given | When | Then |
|---|---|---|
| `<root>/.agent-container/` exists | the tool runs from `<root>` | `<root>` is the project root |
| same | the tool runs from `<root>/src/deep/nested` | **the same** `<root>` is the project root |
| no ancestor holds `.agent-container/` | the tool runs | the declarative model is inert; imperative behaviour is unchanged |
| the project is copied to a different absolute path | the tool runs | identical behaviour (FR-015) |

---

## C2. Per-environment file resolution

Resolution order for every per-environment file is **project, then user**:

```text
1. <root>/.agent-container/<name>.<kind>          ← wins
2. ~/.config/agent-container/<name>.<kind>        ← fallback
```

| Kind | Filename |
|---|---|
| env | `<name>.env`, falling back to a shared `.env` at the same level |
| credential | `<name>.<provider>.key` — **user level only** (FR-001f) |
| agent config | `<name>.config/` |
| sidecars | `<name>.services.yaml` |

**The same filename identifies the same thing at both levels** (FR-001a). The `agent-container.`
prefix is gone from the project level — inside `.agent-container/` there is nothing to
disambiguate from.

Full order: `.agent-container/<name>.env` → `.agent-container/.env` →
`~/.config/agent-container/<name>.env` → `~/.config/agent-container/.env`.

**The bare `./.env` is not in the chain.** It belongs to whoever put it there.

### C2b. Plaintext credentials are user-level only

| Given | When | Then |
|---|---|---|
| `~/.config/agent-container/<name>.anthropic.key` | `up` | discovered and injected, as today |
| `.agent-container/<name>.anthropic.key` | `up` | **not discovered** — the project config directory holds locators and non-secret config, never secret values |
| `./agent-container.<name>.anthropic.key` (old layout) | `up` | **refused**, naming the **user-level** path and the locator sources — there is no project-local destination to name |

The directory travels with the repository; Feature 008 settled that the repo holds a locator,
never a value. Consolidating plaintext keys into it would have moved secrets deeper into the
repo, so they are removed instead.

### C2a. Explicit env files (`-e`, repeatable)

| Given | When | Then |
|---|---|---|
| `-e ~/.env` | `up` / `redeploy` | that file is used; the discovery chain is **not** consulted |
| `-e a.env -e b.env` | same | both applied **in order**; `b.env` wins on conflicting keys |
| `-e missing.env` | same | fails fast, naming the path |
| any `-e`, remote host | same | works — compose reads `env_file` **client-side**, so the path never has to exist on the target daemon |
| any `-e` | the artifact is generated | the path is referenced, **never** the values (Constitution III) |

`-e` is the escape hatch for a file outside the project: the tool stops guessing at `./.env`
and gains a way to be told.

---

## C3. The hard cut — refuse, never ignore

| Given | When | Then |
|---|---|---|
| `./agent-container.<name>.env` present | any command resolving per-environment files | **refuse**, naming the file and its destination |
| `./agent-container.<name>.<provider>.key` present | same | **refuse** — MUST NOT deploy an agent without the credential the operator believes is injected |
| several superseded files present | same | **all** are listed in one message, not one per run |
| `./.env` present **and** an agent-container env file resolves | same | **no refusal** — the stray `.env` is someone else's |
| `./.env` present **and** no agent-container env file resolves | same | **refuse** — otherwise the operator's `GH_TOKEN` and keys vanish silently |
| nothing superseded present | same | silent; no migration chatter |

The refusal message names `old path` → `new path` for each offender (FR-005), so the operator can
comply without opening documentation.

**This is the requirement that makes the hard cut safe.** Deleting the old lookup without it is
indistinguishable, from the operator's side, from silently ignoring their credential file.

---

## C4. Build context

| Given | When | Then |
|---|---|---|
| a checkout with `image/` | `build` (local or remote host) | succeeds; produces an equivalent image |
| same | any build | the transferred context contains **only** `image/` — no project files, no secrets, no history |
| a tree with no `image/Dockerfile` | `build` | fails naming what was expected and where (FR-008) |
| `AGENT_CONTAINER_REPO` pointing at a non-checkout | any command needing it | fails actionably, naming the marker files |

**Checkout marker**: `image/Dockerfile` **and** `completions/agent-container.bash`. Both the
function and its `die` text must agree, and the packaging test constructs its fixture from the
same pair.

---

## C5. In-container paths

| Path | Role | Changes? |
|---|---|---|
| `/workspace/.agent-container` | delivered spec, **read-only** | **No** (FR-012) |
| `/home/dev/.agent-container` → `/home/dev/.agent-env` | persistent shell env | **Yes** — mount point only |
| `/run/agent-container` | ephemeral injected secrets | **No** |

The shell-env **volume name** is `agent-container-<name>-shellenv` before and after. The new
mount point MUST exist in the image, **dev-owned**, or the runtime creates it `root:root` and the
rootless user cannot write it.

---

## C6. Identity — unchanged

```text
container_name("acme")        == "agent-container-acme"
port_for_name("acme")         == 2206
per_container_volumes("acme") == [ …all nine, byte-identical… ]
```

Verified for a corpus of names (SC-003). A single differing byte in any **name** fails the
feature — regardless of how tidy the layout became.

---

## C7. Documentation

Exactly **one** authoritative layout map exists (FR-014). A search for superseded names returns
zero hits outside migration notes, and the vocabulary is used consistently: **project root**,
**project config**, **user configuration**, **derived host state**, **image sources**. The term
"project directory" appears nowhere — it is ambiguous between the first two.
