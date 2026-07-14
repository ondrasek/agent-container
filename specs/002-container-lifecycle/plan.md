# Implementation Plan: Container Lifecycle Engine (net-new verbs on a configured host)

**Branch**: `002-container-lifecycle` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-container-lifecycle/spec.md`

## Summary

Feature 002 owns the **verbs that act on a container already deployable via Feature 001's compose engine**. Much of the spec is **already shipped in 0.5.0** and is *inherited, not rebuilt*: deploy + idempotent reconcile (`up`), dispose (`down`), wipe-volumes (`down --purge`), logs (`logs`), the local-view of `list`, per-host deterministic identity, build-on-host, and port-release-before-return. This plan covers **only the net-new work**:

1. **Pause/reclaim** — `stop` / `start` verbs (compose `stop`/`start`, acting on the whole project so sidecars move as one unit). *(FR-006)*
2. **Image-aware redeploy** — `redeploy` verb: rebuild the image on the host and recreate the container **preserving the 7 volumes** (`compose up -d --build --force-recreate`), while a no-change deploy stays an idempotent no-op. *(FR-008/FR-010)*
3. **Wipe (incl. image)** — `wipe` verb = dispose + remove volumes + remove the locally-built image (`compose down --volumes --rmi local`) behind explicit confirmation. Extends the destroy ladder above `down --purge`. *(FR-009)*
4. **Live state reconciliation** — make `list` truthful by querying each **registered remote host's daemon** live (via `host_ps_rows`/`ensure_tunnel`) and reconciling against per-host state files (the T030 work deferred from 001 US3), so status is correct after a reboot/crash/out-of-band change; a `--local` flag keeps the fast local-only view. *(FR-011/FR-012)*
5. **Sidecar/helper services** — a deployment may declare helper services that share its lifecycle, delivered as a compose **override file** merged into the generated project (`compose -f <generated> -f <override>`). *(FR-004)*

Plus cross-cutting: **per-container lifecycle serialization** (FR-017) via a state-dir lock, and **fail-fast** on unreachable/incapable hosts (FR-015, largely inherited).

**Load-bearing insight:** the host daemon is the **authoritative source of running state**; the tool's state files + generated compose are *regenerable caches*. Every verb recomputes identity from the name (Constitution IV) and reads truth from the host (Constitution I).

## Technical Context

**Language/Version**: Python ≥ 3.14 (host CLI). Single PEP 723 script `bin/agent-container`. Unchanged from 001.

**Primary Dependencies**: Typer + questionary + rich. **No new Python dependency** — new verbs are more `compose` subcommand argv + stdlib `json` (compose-as-JSON) + stdlib `fcntl`/lockfile for serialization. External tools: `docker`/`podman` CLI + compose v2 (already required).

**Storage**: Local operator machine only. Reuses the per-`(host,container)` state under `$XDG_STATE_HOME/agent-container/<host>/<name>.{port,compose.yaml,…}`. New: an optional per-deployment **sidecar override** compose file (operator-supplied, discovered like `.env`); a short-lived **lock file** per `(host,name)` for FR-017. No database.

**Testing**: pytest inner loop — extend `test_command_construction.py` (new `stop`/`start`/`redeploy`/`wipe` + sidecar-merge argv), `test_host_cli.py`/a new `test_lifecycle.py` (reconcile logic, lock behavior), and `test_acceptance.py` (real-container stop→start→redeploy→wipe; live-reconcile after out-of-band change; sidecar up/down as a unit). Acceptance is the authoritative tier; Hetzner-tokened variants stay opt-in.

**Target Platform**: Operator machine macOS (docker/Lima) or Linux (podman); target hosts are Linux compose-capable runtimes (local context or 001-provisioned remote).

**Project Type**: Single-file CLI — extend `bin/agent-container` with sectioned function groups (per 001's Structure Decision), no package split.

**Performance Goals**: Not throughput-bound. New concern: **`list` latency** — live reconciliation adds one `ps` round-trip per registered remote host; bounded per-host and skippable via `--local` so one slow/unreachable host never hangs or breaks the listing.

**Constraints**: Zero new Python deps; compose is the run mechanism; no external image registry; rootless target container; the per-host on-disk identity contract (name/port/volumes/state paths) is unchanged and single-sourced. No new stored long-lived secret.

**Scale/Scope**: Single operator; N containers on one host; live-reconcile across the registry's hosts. Out of scope: pools of identical instances (instance-suffixed identity), cross-host batch orchestration.

## Constitution Check

*GATE: evaluated against constitution v2.1.0. Re-check after Phase 1 design.*

| Principle | Impact & compliance | Verdict |
|-----------|--------------------|---------|
| **I. Ephemerality** | Reinforced: dispose is a non-event (volumes kept), wipe is the explicit destructive act, and **live-host-as-truth** means a container discarded/recreated out of band is reflected, not masked by a stale local record. | ✅ |
| **II. Least Privilege, Immutable Runtime** | Redeploy rebuilds on the host with the same Dockerfile (no runtime apt); no new privilege. Rootless target unchanged. | ✅ |
| **III. Least Exposure** | No new secret; sidecar override is operator-supplied config, not baked; identity injection continues per 001. | ✅ |
| **IV. Deterministic Identity** | Every verb **recomputes** name→port/volumes/project (FR-012); no reliance on stored identity; sidecars live under the same project so they inherit the deterministic key. | ✅ |
| **V. Durable Spec, Disposable Code** | The generated compose (+ sidecar merge) is a derived, regenerable artifact; running truth is read from the host, not the artifact (FR-014). Verification is acceptance-weighted. | ✅ |
| **VI. Least Dependencies** | Zero new Python deps; new verbs are compose argv + stdlib json + stdlib file lock. | ✅ |
| **VII. Continuous Deployment** | Ships incrementally by user story; `feat:` commits drive semver as usual. | ✅ |

**Platform & Interface Constraints**: editor-agnostic SSH+tmux attach unchanged; single operator. ✅

**Gate result**: PASS — no violations, no new complexity to track. The one judgment call (live reconciliation adds `list` latency) is bounded + opt-out, not a constitutional issue (see research R4).

## Project Structure

### Documentation (this feature)

```text
specs/002-container-lifecycle/
├── plan.md              # This file
├── research.md          # Phase 0 — R1-R6 (net-new decisions)
├── data-model.md        # Phase 1 — lifecycle-state, sidecar service, reconciliation model (refs 001 entities)
├── quickstart.md        # Phase 1 — stop/start/redeploy/wipe/reconcile/sidecar validation scenarios
├── contracts/
│   └── cli-commands.md   # net-new command contracts (stop/start/redeploy/wipe, list --local, sidecars)
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

Single PEP 723 script `bin/agent-container` (packaging contract in `pyproject.toml`). Net-new logic slots into the existing sections; **inherited** functions are extended, not rewritten.

```text
bin/agent-container
  ├─ (extend) driver seam       # + driver_stop_argv / driver_start_argv (compose stop/start),
  │                             #   driver_down_argv gains --rmi local for wipe
  ├─ (extend) compose gen       # build_compose_model merges an optional sidecar override file
  ├─ (new) lifecycle verbs      # do_stop / do_start / do_redeploy / do_wipe (compose subcommands)
  ├─ (extend) gather_rows       # live-reconcile registered remote hosts (host_ps_rows) + state files
  ├─ (new) per-(host,name) lock # serialize lifecycle ops (FR-017), stdlib file lock
  ├─ (new) Typer commands       # stop / start / redeploy / wipe ; list gains --local
  └─ (existing) do_up/down/list/logs  # INHERITED from 001 — referenced, extended minimally
bin/tests/
  ├─ test_command_construction.py  # + stop/start/redeploy/wipe + sidecar-merge argv
  ├─ test_lifecycle.py             # (new) reconcile logic + lock behavior (hermetic)
  └─ test_acceptance.py            # + stop→start→redeploy→wipe; live-reconcile; sidecar-as-unit
README.md / CLAUDE.md            # updated for the new verbs + live-reconcile + sidecars (FR-019)
```

**Structure Decision**: keep the single-file contract (the wheel `force-include` maps one file to `agent_container/__init__.py`; splitting breaks non-editable packaging — Constitution VI). New logic is sectioned function groups mirroring 001.

## Complexity Tracking

*No Constitution violations — table intentionally empty.* The only added surface is a per-deployment sidecar override file and a per-op lock file; both are stdlib, optional, and derive their identity from the existing name contract, so they introduce no new authoritative state.
