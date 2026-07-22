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
any action**. On a syntactic or semantic error the tool **refuses to act**, names
the **offending file and field**, and makes **no partial change**.

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
| host-side-only read | The spec is read **only** from the operator's host-side `.agent-container/`; a container's copy is never trusted. A spec change is a host-side git edit the operator reviews. |
| read-only in-container | When a deployed container's `/workspace` contains `.agent-container/`, the compose model adds a bind `<host-side .agent-container>:/workspace/.agent-container:ro` — **kernel-enforced read-only for every uid** (the rootless agent cannot escalate past it). |
| refuse-if-writable | The tool **refuses to deploy** if that subtree would be agent-writable. |

## Compose-model contract

| Aspect | Contract |
|--------|----------|
| workspace | as Feature 004 (persistent/bind/ephemeral); clone-on-start populates a repo that may carry `.agent-container/` |
| `.agent-container` bind | when present, added as a **read-only** bind over `/workspace/.agent-container` (FR-020) |
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
