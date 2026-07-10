# Phase 0 Research: Multi-Host Deployment

Decisions that resolve the plan's technical unknowns. Each: **Decision → Rationale → Alternatives rejected → Validation** (how the choice is proven in the acceptance tier, since some rest on runtime behavior).

## R1 — Universal runtime targeting: docker context (primary), podman connection (local parity)

**Decision**: Model "where the runtime runs" as a **context reference** on the host record. The **DockerContextDriver** targets it with `docker --context <ctx>` (context = a local endpoint or `ssh://user@host`). A **PodmanConnectionDriver** targets `podman --connection <name>` for local parity. Remote deployment is validated on the docker path first; remote podman is best-effort.

**Rationale**: `docker context` + `ssh://` is the single mechanism that makes build/run/attach identical for local and remote with no registry and no custom transport. It is plain docker CLI (not Docker-Desktop-specific), so it honors the "stay podman-compatible / no Desktop-only features" rule for the *local* case while giving the smoothest remote path. The driver seam is exactly where this asymmetry is absorbed.

**Alternatives rejected**: (a) Custom SSH-tunnel-to-daemon transport — reinvents docker contexts. (b) Full podman remote parity up front — gates the headline cloud feature on `podman system connection` + `podman compose`, whose remote-build behavior is less mature; deferred, not precluded. (c) Registry push/pull to avoid remote build — adds a registry dependency (Constitution VI).

**Validation**: acceptance scenario builds+runs a compose project against a local context (both docker and podman); a Hetzner acceptance scenario (opt-in, tokened) proves `ssh://` context build-on-remote.

## R2 — Compose emitted as JSON (a valid YAML subset), zero YAML dependency

**Decision**: Generate the per-container compose file as **JSON** written to `<state>/<host>/<name>.compose.yaml`, using stdlib `json`. Compose (v2) parses it because JSON is valid YAML.

**Rationale**: Constitution VI — avoid adding PyYAML or a hand-rolled YAML serializer. `json.dumps(indent=2)` is deterministic, safe (no code execution, no `$`/backtick foot-guns the current `hosts.conf` parser warns about), and diff-friendly. The file remains human-readable/inspectable (FR-013, SC-008).

**Alternatives rejected**: (a) PyYAML — a new runtime dep for output we can produce with stdlib. (b) String-templated YAML — fragile quoting/escaping, exactly the injection surface JSON avoids. (c) `.json` extension — works, but `.compose.yaml` reads as what it is and both parse identically.

**Validation**: unit test asserts the generated structure (services/volumes/secrets/configs) and that `docker compose -f <file> config` accepts it (acceptance).

## R3 — Host registry storage: `hosts.json` (stdlib), supersedes `hosts.conf`

**Decision**: Persist the host registry as a single JSON document at `~/.config/agent-container/hosts.json`: `{ "hosts": { "<name>": {driver, context, provisioning, address, ...} }, "default": "<name>" }`. On read, if `hosts.json` is absent but legacy `hosts.conf` exists, synthesize read-only degenerate "existing-ssh" hosts from `FOO_HOST`/`FOO_PORT` pairs (deprecation window).

**Rationale**: Host records are structured/nested; JSON is stdlib read+write (Constitution VI), atomically writable, and the natural single-source-of-truth store (FR-005). The legacy synthesis keeps existing attach targets working (Assumption: legacy compatibility) without auto-migrating them.

**Alternatives rejected**: (a) Extend flat `hosts.conf` KV — structured host records become brittle flat keys. (b) TOML — reading is stdlib (`tomllib`) but *writing* needs a third-party lib (Constitution VI). (c) SQLite — over-engineered for a single-operator file.

**Validation**: pure-logic tests for read/write/round-trip and legacy synthesis; atomic-write (temp + rename) test.

## R4 — Hetzner provisioning via stdlib `urllib`, server bootstrap via cloud-init

**Decision**: The **HetznerProvisioner** calls the Hetzner Cloud REST API with stdlib `urllib.request` (Bearer token from runtime env/file, never argv). Server creation passes **cloud-init user-data** that installs docker and authorizes the operator's SSH public key, so the server comes up as a working `ssh://` docker context. Provisioner returns the context reference + reachable address to register as a host.

**Rationale**: Zero new Python dependency (Constitution VI); token stays off argv (Constitution III). Cloud-init is the standard first-boot bootstrap and keeps runtime-install at *provision* time, not container runtime (Constitution II). Confines all provider specifics to this component (spec's driver/provisioner split).

**Alternatives rejected**: (a) `hcloud` CLI — a clean tool but an extra external dependency the operator must install; REST-direct is self-contained (parity with how the tool already shells only to docker/ssh). (b) Post-boot SSH to `apt install docker` — slower, race-prone, and reintroduces imperative remote setup that cloud-init does declaratively. (c) A prebuilt provider image with docker — provider-specific image management, more moving parts.

**Validation**: opt-in acceptance (tokened, never CI): create → wait-reachable → runtime present → register → deploy → attach → destroy; plus a partial-failure path (create succeeds, bootstrap fails → cleanup, no orphaned server — FR-011).

## R5 — Injected identity as compose `secrets`/`configs`, not bind mounts

**Decision**: The SSH **host key** (private) → compose top-level `secrets:` with a local `file:` source; **authorized_keys** (public) → compose `configs:` with a local `file:` source. The service references them; the entrypoint reads from the mounted paths. Files are staged locally under `<state>/<host>/<name>.{host_key,authorized_keys}` (as today) but referenced by compose, which ships their contents over the context.

**Rationale**: FR-015 — a bind mount resolves on the *remote* filesystem and would come up empty; compose secrets/configs read the operator's local file and transfer it to the remote daemon. Also fixes the prior 0644/uid-mismatch dance (secrets/configs carry their own mode). Private/public split matches Constitution III.

**Alternatives rejected**: (a) Bind mounts — the empty-on-remote trap (the bug this feature exists to avoid). (b) Baking keys into the image — Constitution III violation. (c) `docker exec` to inject after start (today's `inject_keys` live path) — kept only for the live `keys` subcommand; not the deploy path.

**Validation**: command-construction test asserts the compose file carries `secrets`/`configs` with correct sources/modes and no identity bind mount; remote acceptance asserts the container is reachable (proves transfer worked).

## R6 — Per-host identity namespacing (Deterministic Identity, with migration)

**Decision**: Keep the derivation `container_name = agent-container-<name>`, `port = 2200 + hash(name)`, and the seven volume names — but **namespace runtime state per host**: state files move to `<state>/<host>/<name>.*`, and the compose **project name** is `agent-container-<name>` *scoped to that host's daemon*. Because each host is a separate daemon/context, project-name and volume collisions across hosts are structurally impossible; ports only need to be unique *per host*.

**Rationale**: FR-019 (per-host determinism, same name on two hosts) with the least change to the existing single-sourced derivation (Constitution IV). No change to the *values* computed for an existing local container → the identity contract stays stable; only the state-file *location* gains a host segment. Migration: on first run, an existing flat `<state>/<name>.port` is read as belonging to the implicit `local` host and relocated under `<state>/local/`.

**Alternatives rejected**: (a) Host-qualified project names (`agent-container-<host>-<name>`) — unnecessary since daemons are already separate, and it would change values for existing containers (contract break). (b) Global port uniqueness across hosts — impossible/needless; each host owns its port space.

**Validation**: pure-logic tests for per-host paths and the flat→`local/` migration; contract test that identity values for an existing name are unchanged.

## R7 — Remote build over context, no registry

**Decision**: `<rt> --context <ssh-host> compose up -d --build` builds the image on the remote daemon; the build context (the repo, per `do_build`'s existing context resolution) is transferred to the remote daemon by the docker CLI. No registry, no local→remote image transfer.

**Rationale**: FR-016 / SC-003 — only source + small identity crosses the wire, not multi-GB images; the remote pulls base layers on its own fast link. Reuses the existing `--context`/`AGENT_CONTAINER_REPO` build-context resolution.

**Alternatives rejected**: (a) Build local + `docker save`/`load` over SSH — ships the whole image. (b) Build local + registry push/pull — registry dependency (Constitution VI) + credentials surface.

**Validation**: remote acceptance asserts the image is built on the server (no local image transfer) and the container starts.

## R8 — Safe teardown & lifecycle split (server vs container)

**Decision**: `down <name>` runs `compose down` (keeps volumes) then the existing `wait_port_released` before returning. **Deprovisioning a server is a separate explicit `host rm --destroy`** that first enumerates containers on that host (via the host's daemon) and **refuses if any remain**; a host bound to an operator-supplied existing server removes only its registration and never destroys infrastructure.

**Rationale**: FR-008/009/010/020, SC-005 — prevents the expensive "tore down a container and it killed the box hosting others" and "recreate raced a stale port" failure modes. Reuses the already-shipped `wait_port_released` fix.

**Alternatives rejected**: (a) `down` implying server teardown — the exact dangerous coupling the spec forbids. (b) Trusting local state for "is the server empty" — must query the host's daemon live (source of truth), consistent with the sibling 002 spec.

**Validation**: acceptance — two containers on one host; `host rm --destroy` refused; remove one; other + server untouched; then destroy succeeds when empty; existing-server host removal leaves the box alive.

## Open risks (validated in implementation/acceptance, not blocking the plan)

- **Compose v2 remote-context build edge cases** (relative `build.context` paths over `ssh://`) — mitigated by using the resolved absolute repo context; proven in R7 acceptance.
- **podman compose remote** — explicitly out of the validated path (R1); local podman parity only.
- **cloud-init image variance on Hetzner** — pin the Debian 12 image + a minimal, idempotent user-data script; proven in R4 acceptance.
