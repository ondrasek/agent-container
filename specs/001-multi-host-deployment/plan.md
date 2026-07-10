# Implementation Plan: Multi-Host Deployment (named hosts, drivers, provisioners, compose run)

**Branch**: `001-multi-host-deployment` | **Date**: 2026-07-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-multi-host-deployment/spec.md`

## Summary

Introduce a **host abstraction** to `agent-container`: a *host* is a named target backed by a *driver* (a container-runtime context — local endpoint or `ssh://` remote) with optional *provisioning* (allocate a cloud server via a provider). The imperative `docker run` path (`launch_container`) is replaced by a **generated declarative compose project** per container, run via `<runtime> --context <host> compose -f <state>/<name>.compose.yaml -p agent-container-<name> up -d`. Images build **on the target host** over its context (no registry). The static `hosts.conf` address book is superseded by a **host registry** (single source of truth). Injected SSH identity moves from `docker run` bind mounts to compose **`secrets`/`configs`** so it transfers over a remote context. Cloud provisioning (Hetzner) is confined to a **provisioner** that creates a server, installs the runtime via cloud-init, and yields an `ssh://` context.

The load-bearing insight from the spec: **docker context is the universal runtime; a provider is a provisioner that yields a context** — so local and remote share one run/build/attach path and all provider-specific code is isolated to provisioning.

## Technical Context

**Language/Version**: Python ≥ 3.14 (host CLI tool; the operator-machine floor, not the container's baked Python). Single PEP 723 script `bin/agent-container`.

**Primary Dependencies**: Typer + questionary + rich (unchanged). **No new runtime Python dependency is added** — compose YAML is emitted as JSON (a valid YAML subset) via stdlib `json`; the host registry is stdlib `json`; Hetzner provisioning uses stdlib `urllib.request`. External *tools* invoked (not Python deps): `docker`/`podman` CLI (already), `ssh` (already), and cloud-init on the provisioned server.

**Storage**: Local operator machine only. Host registry as JSON at `~/.config/agent-container/hosts.json` (supersedes `hosts.conf`). Per-(host,container) state under `$XDG_STATE_HOME/agent-container/<host>/<name>.{port,compose.yaml,host_key,authorized_keys}`. No database. Durable container state lives in per-container volumes on the host (Constitution I).

**Testing**: pytest inner loop — `test_pure_logic.py` (identity, registry parse), `test_command_construction.py` (compose-file content + invocation argv, replacing the old `docker run` argv assertions), `test_cli.py`, `test_packaging.py`; shell suites for entrypoint/completions; `-m acceptance` real-container tier (`test_acceptance.py`) extended with a compose-run local scenario. Hetzner provisioning is validated behind an opt-in acceptance marker requiring a token (never in CI).

**Target Platform**: Operator machine macOS (docker-first, Lima) or Linux (podman-first); target hosts are Linux container runtimes (local context or remote Hetzner VPS running Debian 12 + docker).

**Project Type**: Single-file CLI (the existing structure), extended with internal modules-as-sections (driver/provisioner/compose-generation) kept within the one PEP 723 file to preserve the single-file packaging contract, OR promoted to a small package if the file exceeds a maintainable size — see Structure Decision.

**Performance Goals**: Not throughput-bound. Targets: local deploy → attachable in the time to build+start a container; remote provision → attachable cloud agent in a single flow (SC-002); teardown releases the port before returning (FR-020, existing `wait_port_released`).

**Constraints**: Rootless target container (no runtime apt, sshd as `dev` on 2222 — unchanged). Secrets never baked, never on argv (Constitution III). Podman-compatible locally; docker-context is the primary remote path (see research). No external image registry (FR-016). No new stored long-lived secret.

**Scale/Scope**: Single operator; N containers across ≥2 hosts without collision (SC-004). First provider: Hetzner only. Legacy `hosts.conf` read for a deprecation window.

## Constitution Check

*GATE: evaluated against constitution v2.1.0. Re-checked after Phase 1 design.*

| Principle | Impact & compliance | Verdict |
|-----------|--------------------|---------|
| **I. Ephemerality** | Compose keeps the disposable-container model; `down` keeps volumes, only purge removes them; restart-on-crash reattaches to a fresh session. Remote hosts *strengthen* ephemerality (host loss is a non-event). | ✅ |
| **II. Least Privilege, Immutable Runtime** | Runtime still baked (build-on-host uses the same Dockerfile, no runtime apt). Provisioned server installs docker via cloud-init at *provision* time, not container runtime. Rootless container unchanged. | ✅ |
| **III. Least Exposure** | Provider token + SSH host key never baked, never on argv — delivered as compose `secrets` (private) / `configs` (public), read from files. Token passed via env/file to `urllib`, not argv. | ✅ (verified in design) |
| **IV. Deterministic Identity** | Identity derivation stays single-sourced and recomputed from the name; now **namespaced per host** (each host is a separate daemon, so project-name/port collisions across hosts are structurally impossible). Existing local containers: migration path documented (see research). | ✅ with migration note |
| **V. Durable Spec, Disposable Code** | Spec is the artifact of record (this feature); the generated compose file is a derived, regenerable artifact. Tests move toward validating compose-file *content* + acceptance, away from `docker run` argv internals. | ✅ (directional) |
| **VI. Least Dependencies** | **Zero new Python deps**: compose-as-JSON (stdlib `json`), registry JSON (stdlib), Hetzner via stdlib `urllib`. Docker-context + compose is plain docker CLI (not Desktop-specific). Podman parity retained locally. | ✅ (see Complexity Tracking for the docker/podman remote asymmetry) |
| **VII. Continuous Deployment** | No release-process change; feature ships incrementally by user story (P1 mergeable alone). `docs:`/`feat:` commits drive semver as usual. | ✅ |

**Platform & Interface Constraints**: editor-agnostic SSH+tmux attach preserved (attach flow unchanged, now host-address-aware); single operator assumed. ✅

**Gate result**: PASS. One documented asymmetry (docker-context is the smoother remote path vs podman connections) tracked below — not a violation (no Docker-Desktop-only feature; podman stays supported locally).

## Project Structure

### Documentation (this feature)

```text
specs/001-multi-host-deployment/
├── plan.md              # This file
├── research.md          # Phase 0 — 8 decisions (compose-as-JSON, driver seam, Hetzner-via-urllib, ...)
├── data-model.md        # Phase 1 — Host/Driver/Provisioner/Deployment entities, registry + compose schema, identity
├── quickstart.md        # Phase 1 — local + Hetzner + safety validation scenarios
├── contracts/
│   ├── cli-commands.md   # host add|ls|show|rm, up --host, down, attach — user-facing command contracts
│   ├── driver.md         # internal Driver contract (build/run/connect/reachable-address)
│   └── provisioner.md    # internal Provisioner contract (create/destroy/install-runtime → context)
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

The project is a **single PEP 723 script** (`bin/agent-container`) shipped as the `agent_container` wheel module (packaging contract in `pyproject.toml`). This feature is a substantial addition (host registry, driver seam, compose generation, Hetzner provisioner). **Structure Decision**: keep the single-file contract but organize the new logic into clearly-sectioned function groups within `bin/agent-container` (mirroring today's section comments), because the wheel `force-include` maps exactly one file to `agent_container/__init__.py` and splitting into a package would break the non-editable single-file packaging (Constitution VI — don't add packaging machinery). If the file grows past maintainability, promoting to a package is a separate, deliberate migration (out of scope here).

```text
bin/agent-container            # extended: driver seam, compose gen, host registry, Hetzner provisioner
  ├─ (existing) identity        # container_name/volume_name/port_for_name → namespaced per host
  ├─ (existing) runtime detect  # detect_runtime → per-host runtime+context resolution
  ├─ (new) host registry        # load/save hosts.json; Host record; supersede hosts.conf (read legacy)
  ├─ (new) driver               # DockerContextDriver (primary), PodmanConnectionDriver (local parity)
  ├─ (new) compose generation   # emit <name>.compose.yaml (JSON) with volumes + secrets/configs
  ├─ (new) provisioner          # HetznerProvisioner via urllib + cloud-init
  ├─ (changed) do_up/down       # generate compose → `<rt> --context H compose up -d/down`
  └─ (changed) attach           # host-address-aware ssh target
bin/tests/
  ├─ test_pure_logic.py         # + registry parse, per-host identity, compose-model builders
  ├─ test_command_construction.py # compose-file content + `compose` invocation argv (replaces run argv)
  ├─ test_acceptance.py         # + local compose-run scenario; Hetzner behind opt-in marker
  └─ (shell suites unchanged)
Dockerfile / entrypoint.sh      # unchanged by 001 (build-on-host uses the same image)
docs/decisions/                 # + ADR: host/driver/provisioner + compose run mechanism
completions/                    # updated: `host` subcommands + `--host` option; read hosts.json
```

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|------|------------|--------------------------------------|
| **Docker-context primary for remote; podman connections secondary** | `docker --context ssh://` + `compose` is the smoothest uniform local/remote path; podman's `system connection` + `podman compose` differ in flags and remote-build maturity | Forcing full podman remote parity now would gate the headline cloud feature on the weaker toolchain path; local podman stays fully supported, so no constitutional "Docker-Desktop-only" violation — the asymmetry is remote-only and documented |
| **Compose generation replacing `docker run`** | Spec mandates a declarative, inspectable artifact (FR-013) and secrets/configs that transfer over a remote context (FR-015) | Keeping imperative `docker run` cannot express secrets/configs transfer to a remote daemon nor a human-inspectable artifact; a registry-based image push (to avoid remote build) adds a dependency (Constitution VI) |
| **New host registry file (`hosts.json`)** | A driver-backed host needs structured fields (driver kind, context ref, provisioning state) the flat `KEY=VALUE` `hosts.conf` can't model | Extending `hosts.conf` KV would encode structured/nested host records as brittle flat keys; JSON is stdlib read+write, zero-dep, and supersedes the address book cleanly |
