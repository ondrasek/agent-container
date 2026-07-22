# Contract: Agent-as-Code (Feature 006)

The declarative model layered over the imperative CLI. Only the net-new surface is
specified; host/registry/provisioner (001), lifecycle (002), credential inject
channels (003), and the execution/workspace surface (004) are inherited and driven,
not reimplemented.

## CLI surface (active only when a `.agent-container/` root is discovered)

| Command | Meaning |
|---------|---------|
| `agent-container apply` | Discover → validate → **preview the plan** → on confirm, converge reality to the spec (idempotent). Reports the root + host(s) chosen. |
| `agent-container plan` / `status` | Print the per-resource plan (absent/matching/drifted) and mutate **nothing**. |
| `agent-container destroy` | Remove exactly the **owned** resources (by deterministic identity); a **referenced** host is never deprovisioned; a **provisioned** host only with explicit intent (e.g. `--deprovision`). |

With **no** `.agent-container/` up the tree, these are inert and the tool behaves
exactly as today (FR-004). Every operation **reports the project root and the host**
it selected (FR-019). Confirmation honors the existing headless/`-y` convention
(FR-007).

## Discovery contract

`find_project_root()` walks **upward** from cwd to the nearest ancestor holding a
`.agent-container/` directory; that is the root (deterministic regardless of the
working subdirectory). None found → declarative model inert. The selected root is
printed.

## Validation contract (FR-003)

The spec is parsed (**`yaml.safe_load`** — never `yaml.load`) and validated **before
any action** against the pinned schema below. On a syntactic or semantic error the
tool **refuses to act**, names the **offending file and field**, and makes **no
partial change**.

### Schema (pinned — the validator enforces this)

| Path | Required | Type / allowed values |
|------|----------|-----------------------|
| `environments` | **yes** | non-empty list |
| `environments[].name` | **yes** | string, matches the existing container-name charset (`validate_name`) — unique within the project |
| `environments[].host` | **yes** | a host name (string), **or** a table `{ provision: "hetzner", server_type, location, … }` (US4) |
| `environments[].container` | no | table (below); absent → tool defaults |
| `…container.mode` | no | `interactive` \| `headless` (default `interactive`) |
| `…container.agent` | no | `claude` \| `codex` \| `pi` (default `claude`) |
| `…container.workspace` | no | `persistent` \| `bind` \| `ephemeral` (default `persistent`) |
| `…container.task` | no | string (`@file` allowed) |
| `…container.repo` | no | URL string (clone-on-start) |
| `…container.env_file` | no | path string (non-secret env) |
| `environments[].credentials` | no | list of references (below) |
| `credentials[].name` | **yes** | string |
| `credentials[].source` | **yes** | `env` \| `file` \| `keychain` \| `encrypted` |
| source detail | **yes** (per source) | `env`→`var`; `file`→`path` (outside the tracked dir); `keychain`→`service`+`account`; `encrypted`→`path`+`decrypt` |

Unknown top-level or unknown per-block keys are a validation error (named), not
silently ignored. Enum violations name the field and the allowed set.

## Precedence contract (FR-018)

When the spec and the global registry name the same host with different settings,
the **spec wins for its scope** — the tool applies the spec's definition, overrides
the registry entry for this invocation, and **reports** the override. Never a silent
merge.

## Credential contract (FR-011..016)

| Source | Resolution |
|--------|-----------|
| `env` | read the named env var at apply |
| `file` | read an external file **outside** the tracked dir |
| `keychain` | OS store — macOS `security find-generic-password -w`, Linux `secret-tool lookup` |
| `encrypted` | run the operator's **decrypt command** (`sops -d` / `age -d`) — plaintext **in memory only** |

- Resolved at apply, injected via the **003 runtime channels**; **never** written to
  disk, log, registry, or argv (FR-013/014).
- A **missing/unavailable** source → **fail before any change**, naming it (FR-016).
- A **git-tracked plaintext** secret within the project → **refused** with remediation
  (ignore / externalize / encrypt); the detection boundary is documented (FR-015).

## Spec-integrity contract (FR-020) — the agent cannot re-govern itself

| Guarantee | Contract |
|-----------|----------|
| host-side-only read (load-bearing) | The spec is read **only** from the operator's host-side `.agent-container/`; a container's copy is **never** trusted. A spec change is a host-side git edit the operator reviews — an agent edit / `git push` cannot re-govern. |
| read-only in-container (defense-in-depth) | The declared spec files are delivered **read-only** via the **Feature 003 compose-`configs` channel** (each file a `config` targeting `/workspace/.agent-container/<rel>`) — compose configs mount **read-only** and, **unlike a host bind, work over a remote context** (the 001/003 lesson). Kernel-enforced for every uid. |
| refuse-if-writable (M3) | Before deploy, the tool **verifies** every declared `.agent-container/` file is delivered via a **read-only** channel and that no writable `/workspace` mount exposes it RW; it **refuses to deploy** otherwise. |

## Compose-model contract

| Aspect | Contract |
|--------|----------|
| workspace | as Feature 004 (persistent/bind/ephemeral); clone-on-start populates a repo that may carry `.agent-container/` |
| `.agent-container` delivery | when the workspace carries it, the declared spec files ride the existing `injected_configs` channel as **read-only** compose `configs` targeting `/workspace/.agent-container/<rel>` (FR-020) — remote-context-safe, never a host bind |
| env / credentials / restart / mode | threaded from the declared `[environment.container]` via the existing `ExecSpec` + 003 inject channels — no new inject mechanism |

## Idempotence & scope contract

- `apply` on a **matching** spec makes and reports **zero** changes (FR-006/SC-002).
- `destroy` removes **only** owned identities; unrelated containers and referenced
  hosts are untouched (FR-009/SC-007).
- On partial failure, the tool reports **exactly** what changed and what did not
  (FR-010).

## Documentation contract

Any change to the declarative model, the `.agent-container/` schema, the credential
sources, or the integrity guarantee updates `README.md`, `CLAUDE.md`, the relevant
`docs/`, and this spec in the same change.
