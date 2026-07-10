# Contract: Provisioner (internal)

A Provisioner allocates/deallocates a server for a provider and yields a `docker`-driver Host. All provider-specific concerns (API, tokens, server types, cloud-init) are confined here — adding a provider is a new Provisioner, not a change to the run/build/attach path.

## Operations

| Operation | Signature (conceptual) | Contract |
|-----------|------------------------|----------|
| `create` | `(params, token) → Host` | Allocate a server; supply **cloud-init user-data** that installs the container runtime and authorizes the operator's SSH public key; poll until SSH-reachable and the runtime responds; return a Host `{driver:"docker", context:"ssh://root@<ip>", address:"<ip>", provisioning:{provider, server_id, server_type, location, created:true}, created_by_tool:true}`. |
| `destroy` | `(host, token) → None` | Deallocate the server named by `provisioning.server_id`. Precondition (enforced by caller): `created_by_tool` **and** no containers remain on the host (FR-009/010). |
| `cleanup_on_failure` | `(partial, token) → None` | If `create` fails after allocation, destroy the half-provisioned server so no unusable billable server is left running (FR-011, SC-009). |

## Parameters (Hetzner, first provider)

`server_type` (e.g. `cax11`), `location` (e.g. `nbg1`), `ssh_key` (Hetzner key id/name for initial access), plus the runtime **token**.

## Invariants

- **Token handling** (Constitution III): Bearer token read from runtime env/file; passed to `urllib` request headers; **never** on argv, never baked, never persisted to `hosts.json`.
- **Explicit allocation** (FR-007): `create` is only reached via `--create`; `--reuse` bypasses the provisioner entirely (`created_by_tool=false`).
- **Runtime installed at provision time** (Constitution II): docker is provisioned by cloud-init before the host is registered — not by any container-runtime step.
- **Idempotent-ish failure** (FR-011): any post-allocation failure triggers `cleanup_on_failure`; the operator is always told the outcome.
- **Transport**: stdlib `urllib` only (Constitution VI); no `hcloud`/SDK dependency.

## Extension point

A future provider implements the same three operations returning a `docker`-driver Host with an `ssh://` context. The registry, driver, compose generation, and attach flow are unchanged — the provisioner is the only provider-aware code.
