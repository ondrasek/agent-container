# Phase 1 Data Model: Multi-Host Deployment

Entities are **local operator-machine records** (registry + state) plus the **generated compose model**. No server-side database. The host's container daemon is the authoritative source for *running* state; local records are regenerable caches (Constitution IV/V).

## Host

The authoritative record of a place containers may run. Persisted in `hosts.json`.

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Unique key; validated like a container name (`validate_name`). |
| `driver` | enum: `docker` \| `podman` \| `existing-ssh` | Selects the runtime driver. `existing-ssh` = legacy address-book host (attach-only, no deploy). |
| `context` | string | Docker context name **or** `ssh://user@host`, or the podman connection name. Empty for `existing-ssh`. |
| `address` | string | Reachable address for attach (host/IP). Local → `localhost`; remote → public IP/DNS. |
| `provisioning` | object \| null | Null for local/existing. For provisioned cloud hosts: `{provider, server_id, server_type, location, created:bool}`. |
| `created_by_tool` | bool | True only if this tool allocated the server (gates `--destroy`). |

**Validation**: `name` unique + valid; `driver` in enum; `docker`/`podman` require `context`; `existing-ssh` requires `address` + a port (from legacy). **State transitions** (provisioned host): `absent → creating → reachable → registered`; failure at any step ⇒ `cleanup` (destroy if `created_by_tool`), never left `creating` silently (FR-011).

## Host Registry

The persisted collection; single source of truth for *where* (FR-005). Stored at `~/.config/agent-container/hosts.json`.

```json
{
  "version": 1,
  "default": "local",
  "hosts": {
    "local": { "driver": "docker", "context": "lima-docker", "address": "localhost", "provisioning": null, "created_by_tool": false },
    "hz1":   { "driver": "docker", "context": "ssh://root@203.0.113.7", "address": "203.0.113.7",
               "provisioning": { "provider": "hetzner", "server_id": 12345678, "server_type": "cax11", "location": "nbg1", "created": true },
               "created_by_tool": true }
  }
}
```

**Rules**: written atomically (temp + `os.replace`); `default` names an existing host (the deploy target when `--host` is omitted); on read, absent file + present `hosts.conf` ⇒ synthesize `existing-ssh` hosts (read-only, deprecation window). Never executes file content (parity with the current `hosts.conf` no-eval rule).

## Driver *(internal contract — see contracts/driver.md)*

Not persisted; resolved from a Host at call time. Abstracts build/run/connect so local and remote share one path.

| Capability | Responsibility |
|-----------|----------------|
| `runtime_argv(host)` | Base argv targeting the host: `["docker","--context",ctx]` or `["podman","--connection",name]`. |
| `compose(host, project, file, *args)` | `runtime_argv + ["compose","-p",project,"-f",file, *args]`. |
| `reachable_address(host)` | Address used for attach (host.address). |
| `capability_check(host)` | Verifies the target has a compose-capable runtime; fails fast at register/first-deploy (Edge: runtime floor). |

## Provisioner *(internal contract — see contracts/provisioner.md)*

Not persisted; provider-specific. Confines all cloud specifics.

| Capability | Responsibility |
|-----------|----------------|
| `create(params) → Host` | Allocate server, cloud-init installs runtime + authorizes operator key, wait reachable, return a `docker`-driver Host with `provisioning`/`created_by_tool=true`. |
| `destroy(host)` | Deallocate the server (only if `created_by_tool`); refuse if containers remain (checked by caller via the driver). |
| Credentials | Provider token injected at runtime (env/file), never baked, never argv (Constitution III). |

## Deployment (container instance)

An agent container bound to exactly one host, identified by `name`. Not a stored record — **derived** from `(host, name)` and materialized as the compose file + volumes on the host.

| Aspect | Derivation (single-sourced, recomputed) |
|--------|------------------------------------------|
| Project name | `agent-container-<name>` (scoped to the host's daemon) |
| Container name | `container_name(name)` (unchanged) |
| Published port | `port_for_name(name)` — unique **per host** (R6) |
| Volumes | the seven `*_volume_name(name)` (unchanged), declared in compose `volumes:` |
| Injected identity | host key → `secrets:`; authorized_keys → `configs:` (R5) |
| State location | `$XDG_STATE_HOME/agent-container/<host>/<name>.{port,compose.yaml,host_key,authorized_keys}` |

## Generated Compose Model

The derived, regenerable artifact (JSON-as-YAML, R2). Shape:

```json
{
  "name": "agent-container-alpha",
  "services": {
    "agent": {
      "container_name": "agent-container-alpha",
      "build": { "context": "<resolved repo>" },
      "restart": "unless-stopped",
      "ports": ["<port>:2222"],
      "volumes": [ "agent-container-alpha-workspace:/home/dev/workspace", "... 6 more ..." ],
      "secrets": [ "ssh_host_key" ],
      "configs": [ "ssh_authorized_keys" ]
    }
  },
  "volumes": { "agent-container-alpha-workspace": {}, "...": {} },
  "secrets": { "ssh_host_key": { "file": "<state>/<host>/alpha.host_key" } },
  "configs": { "ssh_authorized_keys": { "file": "<state>/<host>/alpha.authorized_keys" } }
}
```

**Rules**: regenerated from parameters on every `up` (derived, not authoritative); persisted so `compose down`/`ps`/`logs` are reliable; human-readable; carries **no secret literally** — only `file:` references (Constitution III).

## Legacy Address-Book Entry *(transitional)*

Read-only synthesis of a pre-existing `hosts.conf` `FOO_HOST`/`FOO_PORT` pair into an `existing-ssh` Host (attach-only). Removed after the deprecation window. Not written back.

## Entity Relationships

```text
Host Registry 1─┬─* Host ──(if cloud)── 1 Provisioning
                │            │
                │            └─ resolves to → 1 Driver (docker|podman|existing-ssh)
                │
Host 1─────────*  Deployment  ──derives→  Compose Model (services/volumes/secrets/configs)
                                └─owns→ 7 Volumes + injected identity (secret+config)
```
