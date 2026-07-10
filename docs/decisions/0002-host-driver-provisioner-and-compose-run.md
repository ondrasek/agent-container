# 2. Host / driver / provisioner model and compose run mechanism

Date: 2026-07-10

## Status

Accepted (design). Implemented incrementally per `specs/001-multi-host-deployment/tasks.md`.

## Context

`agent-container` deployed containers imperatively (`docker run …`) to whatever
the local runtime pointed at, and kept a flat `hosts.conf` address book only for
`attach`. Feature 001 (`specs/001-multi-host-deployment/`) generalizes this to
**named hosts** (local or remote), a **compose-based run mechanism**, and
optional **cloud provisioning** — without adding Python dependencies and without
breaking the released single-file packaging contract.

## Decision

The full rationale lives in `specs/001-multi-host-deployment/research.md`
(decisions R1–R8). In brief:

1. **Docker context is the universal runtime** (R1). A *host* carries a driver +
   context; `docker --context <ctx>` (local or `ssh://`) runs build/run/attach
   uniformly. Podman connections give local parity; docker-context is the
   validated remote path. A **provider is a provisioner that yields a context**
   (R4) — all cloud code is confined to provisioning.
2. **Compose replaces `docker run`** (R2). Each container is a generated,
   inspectable compose project, emitted as **JSON** (a valid YAML subset) via
   stdlib `json` — no YAML dependency.
3. **Host registry is `hosts.json`** (R3, stdlib), superseding `hosts.conf`
   (still read to synthesize attach-only `existing-ssh` hosts during a
   deprecation window).
4. **Injected identity → compose `secrets`/`configs`** (R5), not bind mounts, so
   it transfers over a remote context (a bind resolves empty on the remote).
5. **Identity is per-host** (R6): same derivation, state namespaced under
   `<state>/<host>/`, with a one-time flat→`local/` migration (stable contract).
6. **Hetzner provisioning via stdlib `urllib` + cloud-init** (R4); token never
   baked, never on argv (Constitution III).
7. **Remote build over context, no registry** (R7); **safe teardown** splits
   server vs container lifecycle (R8).

## Consequences

- Zero new Python dependencies (stdlib `json` + `urllib`) — honors Principle VI.
- One documented asymmetry: docker-context is the validated remote path; remote
  podman is best-effort (local podman stays fully supported) — not a
  Docker-Desktop-only feature, so no constitutional violation.
- The single-file `bin/agent-container` grows new sections (registry, driver,
  compose generation, provisioner) rather than splitting into a package, to
  preserve the wheel `force-include` packaging contract.
- Mount-path mechanics of compose `secrets`/`configs` (whether an absolute
  `target` is honored for secrets vs configs) are validated in the acceptance
  tier, not assumed — see `research.md` open risks.
