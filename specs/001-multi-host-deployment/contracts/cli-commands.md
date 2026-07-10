# Contract: CLI Commands (user-facing)

The CLI is the product's interface (Typer). New/changed commands for Feature 001. Grammar is flag-based (not `key=value` positionals). Exit non-zero with a clear diagnostic on every failure (FR-022).

## `host add <name> [options]`

Register a named host.

| Option | Applies to | Meaning |
|--------|-----------|---------|
| `--driver docker\|podman` | all | Runtime driver. Default `docker`. |
| `--docker-context <ctx>` / `--connection <name>` | docker / podman | Existing local or `ssh://` context / podman connection. |
| `--provider hetzner` | cloud | Selects a provisioner (mutually exclusive with `--docker-context`). |
| `--create` | cloud | Allocate a **new** server (billable; explicit — FR-007). |
| `--reuse <ip>` | cloud | Register against an **existing** server (no allocation; `created_by_tool=false`). |
| `--server-type / --location / --ssh-key <id>` | cloud+`--create` | Hetzner server params. |
| `--default` | all | Make this the default deploy target. |

**Contract**: on success writes a Host to `hosts.json` and prints its resolved record. `--create` provisions (create → cloud-init runtime → wait reachable → register); on any post-allocation failure, cleans up and reports (no orphaned billable server — FR-011). `capability_check` runs at registration for non-cloud hosts; unusable runtime ⇒ fail here, not at deploy (Edge: runtime floor). Provider token read from runtime env/file, never argv (FR-012).

## `host ls`

List registered hosts. Columns: name, driver, address, reachability, provisioning state, `*`=default (FR-003, US3-AS1). `--json` for machine output.

## `host show <name>`

Print one host's full record (FR-003).

## `host rm <name> [--destroy] [--yes]`

Remove a host registration. **Without `--destroy`**: removes only the registry entry (infrastructure untouched — FR-010). **With `--destroy`**: only valid if `created_by_tool`; first enumerates containers on the host's daemon and **refuses if any remain** (FR-009, SC-005); then deallocates the server. Refuses to destroy an `existing-ssh`/`--reuse` host's server (FR-010).

## `up <name> [--host <host>] [options]` *(changed)*

Deploy container `<name>`. `--host` selects the target; omitted ⇒ registry `default` (FR-004). **Behavior change**: generates `<state>/<host>/<name>.compose.yaml` (R2) and runs `<driver> compose -p agent-container-<name> up -d --build` on the host (R7), replacing the imperative `docker run`. Volumes + injected identity (secrets/configs) are in the compose file (FR-013/014/015). On success reports the reachable **address + port** to attach (FR-018). Existing options (`--host-key`, `--authorized-key`, `--window`, env-file) preserved; identity now flows via secrets/configs, not bind mounts.

## `down <name> [--host <host>] [--purge] [--yes]` *(changed)*

`compose down` on the host (keeps the 7 volumes), then `wait_port_released` before returning (FR-020). `--purge` also removes volumes. **Never** touches the server (FR-008). `--host` resolves which host holds the container (defaults to registry default; error if ambiguous across hosts).

## `attach <name> [--host <host>]` *(changed)*

`ssh <user>@<host.address> -p <port> -t tmux attach -t main`. Address comes from the resolved Host (localhost for local, public IP for cloud) — same flow for both (FR-018). Falls back to legacy `existing-ssh` hosts for attach-only targets.

## `list` *(changed)*

Enumerates containers; each row shows its **host**. Reconciles against the host daemons where feasible (full live reconciliation is 002's remit).

## Backward-compatibility

- Pre-existing `hosts.conf` entries are attachable as `existing-ssh` hosts (deprecation window).
- A bare `up <name>` with no registered hosts and no default: create/assume an implicit `local` docker host from `detect_runtime()` (smooth upgrade from today's behavior), and say so.
- Completions updated to offer `host` subcommands and `--host` values read from `hosts.json`.
