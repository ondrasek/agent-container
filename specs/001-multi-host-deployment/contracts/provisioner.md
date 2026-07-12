# Contract: Provisioner (internal)

A Provisioner allocates/deallocates a server for a provider and yields a `docker`-driver Host. All provider-specific concerns (API, tokens, server types, cloud-init) are confined here — adding a provider is a new Provisioner, not a change to the run/build/attach path.

## Operations

| Operation | Signature (conceptual) | Contract |
|-----------|------------------------|----------|
| `create` | `(params, token) → Host` | Allocate a server; supply **cloud-init user-data** that installs the container runtime (docker-only — root SSH authorization is via the provider's ssh_keys API, which injects into root; cloud-init's `ssh_authorized_keys` does **not** on this image). Authorize **two** keys on root: a tool-generated, file-based **automation key** (for the tool's unattended docker access) and the **operator key** (for interactive `attach`). Poll until docker answers over an **ssh local-socket forward** that presents the automation key with every option as a CLI arg (`ssh -i <automation_key> -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=accept-new -N -L <sock>:/var/run/docker.sock root@<ip>`) — so it signs unattended regardless of the operator's `~/.ssh/config`/agent (e.g. an approval-gated 1Password key). Create a **named local docker context** targeting the forwarded socket (`docker context create <name> --docker host=unix://<sock>`) so `docker --context <name>` (deploy/ps/down) is unchanged; the tunnel is (re)established per command and torn down at exit. Return a Host `{driver:"docker", context:"agent-container-<name>", address:"<ip>", provisioning:{provider, server_id, server_type, location, connection:"ssh-forward", ssh_key_id, automation_ssh_key_id, created:true}, created_by_tool:true}`. |
| `destroy` | `(host, token) → None` | Deallocate the server named by `provisioning.server_id`; delete **both** uploaded keys (`ssh_key_id` operator + `automation_ssh_key_id`), the local automation keypair, the tunnel, and the docker context. Precondition (enforced by caller): `created_by_tool` **and** no containers remain on the host (FR-009/010). |
| `cleanup_on_failure` | `(partial, token) → None` | If `create` fails after allocation, destroy the half-provisioned server (and the keys/automation-key/tunnel) so no unusable billable server or dangling key is left (FR-011, SC-009). |

## Parameters (Hetzner, first provider)

`server_type` (e.g. `cax11`), `location` (e.g. `nbg1`), `ssh_key` (Hetzner key id/name for initial access), plus the runtime **token**.

## Invariants

- **Token handling** (Constitution III): Bearer token read from runtime env/file; passed to `urllib` request headers; **never** on argv, never baked, never persisted to `hosts.json`.
- **Explicit allocation** (FR-007): `create` is only reached via `--create`; `--reuse` bypasses the provisioner entirely (`created_by_tool=false`).
- **Runtime installed at provision time** (Constitution II): docker is provisioned by cloud-init before the host is registered — not by any container-runtime step.
- **Idempotent-ish failure** (FR-011): any post-allocation failure triggers `cleanup_on_failure`; the operator is always told the outcome.
- **Unattended automation, least exposure** (Constitution III): the tool's own machine→server access uses a dedicated, file-based automation key passed as ssh CLI args — never the operator's interactive/agent key, which is authorized only for `attach` (as `dev@host:port`, so the automation stanza never affects it). The automation key is generated locally, authorized on root, and destroyed with the host.
- **Transport**: stdlib `urllib` only (Constitution VI); no `hcloud`/SDK dependency.

## Extension point

A future provider implements the same three operations returning a `docker`-driver Host whose context targets the tool's ssh socket-forward (`connection:"ssh-forward"`, `unix://<sock>`). The registry, driver, compose generation, and attach flow are unchanged — the provisioner is the only provider-aware code.
