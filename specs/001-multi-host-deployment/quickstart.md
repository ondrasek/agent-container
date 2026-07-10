# Quickstart / Validation: Multi-Host Deployment

Runnable scenarios that prove the feature end-to-end, mapped to spec user stories and success criteria. The local scenarios run in the acceptance tier (`pytest -m acceptance bin/tests`); Hetzner is opt-in and tokened (never CI).

## Prerequisites

- `agent-container` installed (editable dev install) or run via `uv run --script bin/agent-container`.
- A working local container runtime + a docker context (macOS: Lima; Linux: local docker/podman). `docker context ls` shows the context you'll register.
- For Hetzner scenarios only: `HCLOUD_TOKEN` in the environment (read at runtime; never passed on argv) and a Hetzner SSH key id.

## Scenario A — Local host: register, deploy, attach, teardown (US1 / SC-001, SC-008)

```bash
agent-container host add local --driver docker --docker-context <your-context> --default
agent-container host ls                     # local shown, marked default
agent-container up alpha                     # no --host → default 'local'
agent-container list                         # alpha running, host=local
```

**Expected**: a compose file exists at `$XDG_STATE_HOME/agent-container/local/alpha.compose.yaml`, is human-readable JSON-as-YAML, and lists the 7 volumes + `secrets`/`configs` (SC-008). `up` prints the attach address+port.

```bash
agent-container attach alpha                  # ssh dev@localhost -p <port> -t tmux attach -t main
# ... detach (Ctrl-b d), then:
agent-container down alpha                     # compose down; port released before return
agent-container up alpha                       # immediate recreate must NOT fail on a stale port (FR-020)
```

**Expected**: attach lands in tmux; after `down` the 7 volumes remain; immediate re-`up` succeeds.

## Scenario B — Inspect the artifact & secrets discipline (SC-006, SC-008)

```bash
cat "$XDG_STATE_HOME/agent-container/local/alpha.compose.yaml"
```

**Expected**: `secrets.ssh_host_key.file` and `configs.ssh_authorized_keys.file` reference local paths — **no key material inline**; no secret appears in the file, on any `compose` argv, or in the built image (SC-006). Private key is a `secret`, authorized_keys a `config`.

## Scenario C — Hetzner: provision → deploy → attach → destroy (US2 / SC-002, SC-003, SC-009) *(opt-in)*

```bash
agent-container host add hz1 --provider hetzner --create \
    --server-type cax11 --location nbg1 --ssh-key <key-id>
# tool: allocate → cloud-init installs docker + authorizes key → wait reachable → register
agent-container up beta --host hz1             # image builds ON the server (no local image transfer)
agent-container attach beta --host hz1          # ssh dev@<public-ip> -p <port> -t tmux attach
```

**Expected**: one flow yields an attachable cloud agent (SC-002); only source + small identity crossed the wire, image built remotely (SC-003); the injected identity arrived via secrets/configs (proven by reachability).

**Partial-failure check (SC-009)**: simulate a bootstrap failure (e.g. invalid server-type) → the tool reports failure and leaves **no** billable server running.

## Scenario D — Safe teardown & lifecycle split (US3 / SC-005) *(opt-in for cloud; local-analog available)*

```bash
agent-container up gamma --host hz1            # second container on hz1
agent-container host rm hz1 --destroy          # REFUSED: server still hosts beta + gamma
agent-container down beta --host hz1            # container gone; server + gamma untouched
agent-container down gamma --host hz1
agent-container host rm hz1 --destroy          # now empty → server destroyed, entry removed
```

**Expected**: destroy refused while containers exist (SC-005); tearing down a container never affects the server or siblings; a `--reuse`/existing-ssh host's server is never destroyed.

## Scenario E — Multi-host no-collision (SC-004)

```bash
agent-container up alpha --host local
agent-container up alpha --host hz1            # same NAME, different host — allowed
agent-container list                           # two 'alpha', distinct hosts, no port/volume/name clash
```

**Expected**: identical names coexist across hosts with zero collision (separate daemons; per-host state).

## Regression / migration checks

- **Legacy attach**: a pre-existing `~/.config/agent-container/hosts.conf` entry is attachable as an `existing-ssh` host (deprecation window).
- **Identity stability**: a container created before this feature keeps the same port/volume names; its state relocates under `.../local/` transparently (R6).
- **Podman local parity**: Scenario A repeated with `--driver podman --connection <name>` on a Linux box.

## Automated coverage

- Unit/contract: registry round-trip + legacy synthesis; per-host identity + flat→`local/` migration; compose-model builder (structure, secrets/configs, no inline secret); driver argv builders; provisioner token-never-on-argv.
- Acceptance (`-m acceptance`): Scenario A end-to-end locally (docker + podman); Scenarios C/D behind an opt-in tokened marker.
