"""Container lifecycle engine (Feature 002) unit tests — hermetic, no live runtime.

Covers the net-new foundational pieces and the US2 verbs' guard behavior:
the per-(host,name) deployment lock (FR-017), the new compose-subcommand argv
builders (R1/R2/R3), and the verbs' fail-fast/confirmation guards. Real-container
behavior (stop→start→redeploy→wipe, volume preservation) is the acceptance tier.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

H = {"driver": "docker", "context": "lima"}
F = Path("/s/acme.compose.yaml")


# --- deployment lock (FR-017) -------------------------------------------------


def test_deployment_lock_refuses_concurrent(wiz):
    with wiz.deployment_lock("local", "alpha"):
        with pytest.raises(wiz.Fatal, match="another lifecycle operation is in progress"):
            with wiz.deployment_lock("local", "alpha"):
                pass  # pragma: no cover


def test_deployment_lock_independent_pairs_do_not_contend(wiz):
    with wiz.deployment_lock("local", "alpha"):
        with wiz.deployment_lock("local", "beta"):  # different name
            pass
        with wiz.deployment_lock("h2", "alpha"):  # different host
            pass


def test_deployment_lock_releases_on_exit(wiz):
    with wiz.deployment_lock("local", "alpha"):
        pass
    with wiz.deployment_lock("local", "alpha"):  # re-acquire after release
        pass


# --- driver argv builders (R1/R2/R3) -----------------------------------------


def test_driver_stop_start_argv(wiz):
    assert wiz.driver_stop_argv(H, "agent-container-acme", F) == [
        "docker", "--context", "lima", "compose",
        "-p", "agent-container-acme", "-f", "/s/acme.compose.yaml", "stop",
    ]  # fmt: skip
    assert wiz.driver_start_argv(H, "agent-container-acme", F)[-1] == "start"


def test_driver_redeploy_argv_force_recreates(wiz):
    argv = wiz.driver_redeploy_argv(H, "p", F)
    assert argv[-4:] == ["up", "-d", "--build", "--force-recreate"]


def test_driver_down_argv_purge_and_rmi_local(wiz):
    assert wiz.driver_down_argv(H, "p", F)[-2:] == ["down", "--remove-orphans"]
    assert wiz.driver_down_argv(H, "p", F, purge=True)[-3:] == [
        "down", "--remove-orphans", "--volumes",
    ]  # fmt: skip
    assert wiz.driver_down_argv(H, "p", F, purge=True, rmi_local=True)[-5:] == [
        "down", "--remove-orphans", "--volumes", "--rmi", "local",
    ]  # fmt: skip


# --- verb guards (US2) --------------------------------------------------------


def _fix_host(wiz, monkeypatch, *, tunnel=True):
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h=None: ("local", dict(H)))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)


def test_do_stop_without_a_deployment_dies(wiz, monkeypatch):
    _fix_host(wiz, monkeypatch)
    with pytest.raises(wiz.Fatal, match="to stop"):
        wiz.do_stop("ghost")  # no compose file staged for this name


def test_do_start_without_a_deployment_dies(wiz, monkeypatch):
    _fix_host(wiz, monkeypatch)
    with pytest.raises(wiz.Fatal, match="deploy it"):
        wiz.do_start("ghost")


def test_do_wipe_non_tty_refuses_without_yes(wiz, monkeypatch):
    _fix_host(wiz, monkeypatch)
    monkeypatch.setattr(wiz, "is_tty", lambda: False)
    called = {"down": False}
    monkeypatch.setattr(wiz, "down_container", lambda *a, **k: called.__setitem__("down", True))
    with pytest.raises(wiz.typer.Exit):
        wiz.do_wipe("alpha", yes=False)
    assert called["down"] is False  # never destroyed anything


def test_do_wipe_with_yes_routes_to_down_purge_rmi(wiz, monkeypatch):
    _fix_host(wiz, monkeypatch)
    calls: list = []
    monkeypatch.setattr(
        wiz,
        "down_container",
        lambda hn, hr, n, purge, rmi_local=False: calls.append((purge, rmi_local)),
    )
    wiz.do_wipe("alpha", yes=True)
    assert calls == [(True, True)]  # wipe = dispose + volumes + built image


def test_do_up_stays_idempotent_when_already_running(wiz, monkeypatch):
    # US1 regression: the new lifecycle verbs + lock must not perturb `up`'s
    # inherited idempotent no-op (FR-010) — an already-running deployment is not
    # recreated.
    _fix_host(wiz, monkeypatch)
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: {wiz.container_name("alpha")})
    monkeypatch.setattr(wiz, "read_state_port", lambda *a: 2201)
    called = {"up": False}
    monkeypatch.setattr(wiz, "compose_up_exec", lambda *a, **k: called.__setitem__("up", True))
    wiz.do_up("alpha")
    assert called["up"] is False  # idempotent: did not recreate


def test_distinct_names_have_noncolliding_identity(wiz):
    # US1: two distinct names -> distinct project/port/volumes (inherited identity).
    assert wiz.container_name("a") != wiz.container_name("b")
    assert wiz.compose_project("a") != wiz.compose_project("b")
    assert set(wiz.per_container_volumes("a")).isdisjoint(wiz.per_container_volumes("b"))


# --- US3 live reconcile in `list` (FR-011/012, SC-004) ------------------------

REMOTE = {
    "driver": "docker",
    "context": "ssh://root@1.2.3.4",
    "address": "1.2.3.4",
    "provisioning": None,
    "created_by_tool": False,
}


def _reconcile(make_registry, monkeypatch, hosts, ps_by_context):
    """Seed a registry + isolate gather_rows: no local ps, no real tunnel, and
    host_ps_rows dispatched by the host's context to a caller-supplied fn."""
    w = make_registry({"default": None, "hosts": hosts})
    monkeypatch.setattr(w, "ps_agent_container", lambda rt, include_stopped=False, strict=False: [])
    monkeypatch.setattr(w, "ensure_tunnel", lambda *a, **k: None)

    def _host_ps(hrec, include_stopped=False):
        return ps_by_context[hrec.get("context")](include_stopped)

    monkeypatch.setattr(w, "host_ps_rows", _host_ps)
    return w


def _rows_for(rows, host, name):
    return [r for r in rows if r["host"] == host and r["name"] == name]


def test_gather_rows_reconciles_reachable_remote_host(make_registry, monkeypatch):
    w = _reconcile(
        make_registry, monkeypatch, {"vps": dict(REMOTE)},
        {"ssh://root@1.2.3.4": lambda inc: [("agent-container-acme", "img:latest", "Up 3 minutes", "3 minutes ago")]},
    )  # fmt: skip
    w.write_state("vps", "acme", 2250)
    r = _rows_for(w.gather_rows("docker"), "vps", "agent-container-acme")
    assert len(r) == 1
    assert r[0]["status"] == "Up 3 minutes"
    assert str(r[0]["port"]) == "2250" and r[0]["image"] == "img:latest" and r[0]["stale"] is False


def test_gather_rows_dedups_live_over_placeholder(make_registry, monkeypatch):
    w = _reconcile(
        make_registry, monkeypatch, {"vps": dict(REMOTE)},
        {"ssh://root@1.2.3.4": lambda inc: [("agent-container-acme", "img", "Up 1m", "1m")]},
    )  # fmt: skip
    w.write_state("vps", "acme", 2250)  # has a live row -> deduped
    # 'vps' was PROVABLY reconciled (its live ps succeeded), so a state file with no
    # live match means the container is gone -> 'stale', not a static 'on remote host'.
    w.write_state("vps", "ghost", 2251)
    rows = w.gather_rows("docker")
    acme = _rows_for(rows, "vps", "agent-container-acme")
    ghost = _rows_for(rows, "vps", "agent-container-ghost")
    assert len(acme) == 1 and acme[0]["status"] == "Up 1m"
    assert len(ghost) == 1 and ghost[0]["status"] == "stale" and ghost[0]["stale"] is True


@pytest.mark.parametrize("kind", ["fatal", "oserror", "subproc"])
def test_gather_rows_marks_unreachable_kept_not_running(make_registry, monkeypatch, kind):
    import subprocess as _sp

    w = make_registry({"hosts": {"down": dict(REMOTE)}})
    exc = {"fatal": w.Fatal("down"), "oserror": OSError("x"), "subproc": _sp.SubprocessError("b")}[
        kind
    ]
    monkeypatch.setattr(w, "ps_agent_container", lambda rt, include_stopped=False, strict=False: [])
    monkeypatch.setattr(w, "ensure_tunnel", lambda *a, **k: None)

    def _raise(h, include_stopped=False):
        raise exc

    monkeypatch.setattr(w, "host_ps_rows", _raise)
    w.write_state("down", "ghost", 2260)
    r = _rows_for(w.gather_rows("docker"), "down", "agent-container-ghost")
    assert len(r) == 1 and r[0]["status"] == "unreachable" and r[0]["stale"] is False


def test_gather_rows_unreachable_host_with_no_state_still_listed(make_registry, monkeypatch):
    w = _reconcile(
        make_registry, monkeypatch, {"down": dict(REMOTE)},
        {"ssh://root@1.2.3.4": lambda inc: (_ for _ in ()).throw(RuntimeError)},  # placeholder, overridden below
    )  # fmt: skip

    def _raise(h, include_stopped=False):
        raise w.Fatal("down")

    monkeypatch.setattr(w, "host_ps_rows", _raise)
    r = [x for x in w.gather_rows("docker") if x["host"] == "down"]
    assert r and r[0]["status"] == "unreachable"  # synthetic marker; never vanishes


def test_gather_rows_local_only_makes_no_remote_call(make_registry, monkeypatch):
    w = make_registry({"hosts": {"vps": dict(REMOTE)}})
    monkeypatch.setattr(w, "ps_agent_container", lambda rt, include_stopped=False, strict=False: [])
    monkeypatch.setattr(
        w, "host_ps_rows", lambda *a, **k: pytest.fail("--local must not query remote")
    )
    monkeypatch.setattr(w, "ensure_tunnel", lambda *a, **k: pytest.fail("--local must not tunnel"))
    w.write_state("vps", "acme", 2250)
    r = _rows_for(w.gather_rows("docker", local_only=True), "vps", "agent-container-acme")
    assert len(r) == 1 and r[0]["status"] == "on remote host"  # static 0.5.0 view


def test_gather_rows_skips_attach_only_driver(make_registry, monkeypatch):
    legacy = {
        "driver": "existing-ssh",
        "context": "",
        "address": "198.51.100.9",
        "created_by_tool": False,
    }
    w = make_registry({"hosts": {"legacy": legacy}})
    monkeypatch.setattr(w, "ps_agent_container", lambda rt, include_stopped=False, strict=False: [])
    calls: list = []
    monkeypatch.setattr(w, "host_ps_rows", lambda h, include_stopped=False: calls.append(h) or [])
    w.write_state("legacy", "x", 2270)
    r = _rows_for(w.gather_rows("docker"), "legacy", "agent-container-x")
    assert calls == []  # attach-only never queried
    assert r and r[0]["status"] == "on remote host"  # not mislabeled 'unreachable'


def test_gather_rows_reconcile_uses_include_stopped(make_registry, monkeypatch):
    seen: dict = {}

    def _ps(h, include_stopped=False):
        seen["inc"] = include_stopped
        return [("agent-container-acme", "img", "Exited (0) 1 minute ago", "1 minute ago")]

    w = make_registry({"hosts": {"vps": dict(REMOTE)}})
    monkeypatch.setattr(w, "ps_agent_container", lambda rt, include_stopped=False, strict=False: [])
    monkeypatch.setattr(w, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(w, "host_ps_rows", _ps)
    r = _rows_for(w.gather_rows("docker"), "vps", "agent-container-acme")
    assert seen["inc"] is True  # out-of-band stop must be visible (SC-004)
    assert r and "Exited" in r[0]["status"]


def test_host_ps_rows_fail_closed_on_nonzero_and_parses_on_zero(wiz, monkeypatch):
    import subprocess as _sp

    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(
        wiz, "query", lambda a, timeout=None: _sp.CompletedProcess(a, 1, "", "cannot connect")
    )
    with pytest.raises(wiz.Fatal, match="could not list containers"):
        wiz.host_ps_rows({"driver": "docker", "context": "ssh://root@x"})
    monkeypatch.setattr(
        wiz,
        "query",
        lambda a, timeout=None: _sp.CompletedProcess(a, 0, "agent-container-z\timg\tUp\t1m\n", ""),
    )
    assert wiz.host_ps_rows({"driver": "docker", "context": "c"}) == [
        ("agent-container-z", "img", "Up", "1m")
    ]


def test_do_redeploy_warns_when_container_absent(wiz, monkeypatch):
    _fix_host(wiz, monkeypatch)
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: set())
    monkeypatch.setattr(wiz, "resolve_env_file", lambda n: Path("/tmp/x.env"))
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    seen: list = []
    monkeypatch.setattr(wiz, "warn", lambda m: seen.append(m))
    monkeypatch.setattr(
        wiz, "compose_up_exec", lambda *a, **k: seen.append(("redeploy", k.get("redeploy")))
    )
    wiz.do_redeploy("alpha")
    assert any("will create it fresh" in m for m in seen if isinstance(m, str))
    assert ("redeploy", True) in seen  # force-recreate path


def test_gather_rows_local_daemon_unreachable_is_fail_closed(make_registry, monkeypatch):
    """A failed LOCAL `ps` must not read as 'no containers' (001-US3 lesson): the
    local host renders 'unreachable' and its orphan state is kept, never dropped."""
    import subprocess as _sp

    w = make_registry({"hosts": {}})

    def _boom(rt, include_stopped=False, strict=False):
        if strict:
            raise _sp.SubprocessError("local daemon down")
        return []

    monkeypatch.setattr(w, "ps_agent_container", _boom)
    monkeypatch.setattr(w, "ensure_tunnel", lambda *a, **k: None)
    w.write_state("local", "acme", 2250)
    r = _rows_for(w.gather_rows("docker"), "local", "agent-container-acme")
    assert len(r) == 1 and r[0]["status"] == "unreachable" and r[0]["stale"] is False


def test_down_container_clears_state_when_host_unreachable(wiz, monkeypatch):
    """Teardown must not be stranded by a dead host: a failed existence check
    degrades to 'unknown' and down still clears the per-host state (#6)."""

    def _boom(*a, **k):
        raise wiz.Fatal("host is gone")

    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "host_container_names", _boom)
    warned: list = []
    monkeypatch.setattr(wiz, "warn", lambda m: warned.append(m))
    wiz.write_state("vps", "acme", 2250)
    assert wiz.read_state_port("vps", "acme") == "2250"
    wiz.down_container("vps", dict(H), "acme", purge=False)
    assert wiz.read_state_port("vps", "acme") is None  # state cleared despite the dead host
    assert any("clearing local state anyway" in m for m in warned)


# --- Feature 010 US3: the seven -> nine volume-set change is upgrade-safe -----

# The volume set that existed BEFORE Feature 010. An environment created on this
# set must still tear down cleanly under the new code (FR-009, SC-005).
_PRE_010_SUFFIXES = ("workspace", "claude", "codex", "pi", "shellenv", "tmux", "ssh")


def test_teardown_of_a_pre_upgrade_environment_tolerates_the_missing_volumes(wiz, monkeypatch):
    """FR-009 — the feature's headline risk. An environment created on the OLD
    seven-volume set is torn down by code that knows about nine. The two it has
    never heard of must be tolerated, with no error and no manual migration.

    Written even though `compose down --volumes` reconciles by project label and
    `query()` ignores exit status, because 'expected to already work' is exactly
    the reasoning that lets a regression through.
    """
    existing = {f"agent-container-legacy-{s}" for s in _PRE_010_SUFFIXES}
    attempted: list[str] = []

    def fake_query(argv, timeout=None):
        # Model a daemon that fails on `volume rm` for a volume it does not have.
        if "volume" in argv and "rm" in argv:
            vol = argv[-1]
            attempted.append(vol)
            if vol not in existing:
                return subprocess.CompletedProcess(argv, 1, "", f"no such volume: {vol}\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: {"agent-container-legacy"})
    monkeypatch.setattr(wiz, "wait_port_released", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "query", fake_query)
    wiz.write_state("local", "legacy", 2250)

    wiz.down_container("local", dict(H), "legacy", purge=True)  # must not raise

    # All nine were attempted — the two absent ones did not abort the teardown.
    assert set(attempted) == set(wiz.per_container_volumes("legacy"))
    assert "agent-container-legacy-opencode" in attempted
    assert "agent-container-legacy-opencode-data" in attempted
    assert wiz.read_state_port("local", "legacy") is None  # state cleared


def test_fresh_teardown_targets_every_volume_the_tool_creates(wiz):
    """FR-008: no orphaned storage — the purge list is exactly the created set,
    and it now includes both of opencode's."""
    created = set(wiz.per_container_volumes("acme"))
    assert len(created) == 9
    assert {"agent-container-acme-opencode", "agent-container-acme-opencode-data"} <= created
    # The pre-010 set is a strict subset: nothing was renamed or dropped (FR-014).
    assert {f"agent-container-acme-{s}" for s in _PRE_010_SUFFIXES} < created


def _ok(argv):
    import subprocess

    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


# --- Feature 012: the proxy must not survive teardown -----------------------


def test_fallback_teardown_removes_the_proxy_too(wiz, monkeypatch, tmp_path):
    """The no-compose-file branch removes by EXACT NAME, and the proxy is
    deliberately outside CONTAINER_PREFIX — so nothing else in that path would ever
    match it. Without this it keeps running under `restart: unless-stopped`."""
    calls: list[list[str]] = []
    monkeypatch.setattr(wiz, "query", lambda argv: calls.append(list(argv)) or _ok(argv))
    monkeypatch.setattr(wiz, "host_ps_rows", lambda *a, **k: [("agent-container-acme", "Up")])
    monkeypatch.setattr(wiz, "compose_file_path", lambda h, n: tmp_path / "absent.yaml")
    monkeypatch.setattr(wiz, "host_is_local", lambda h: False)
    wiz.down_container("local", H, "acme", purge=False)
    removed = [a[-1] for a in calls if "rm" in a and "-f" in a]
    assert "agent-container-acme" in removed
    assert wiz.egress_container_name("acme") in removed, "the proxy would be stranded"


def test_teardown_removes_the_proxy_when_the_agent_is_already_gone(wiz, monkeypatch, tmp_path):
    """`exists` comes from host_ps_rows, which filters on CONTAINER_PREFIX — so a
    surviving proxy can NEVER make it true. The tool would otherwise report
    'no container named …' while agent-egress-acme keeps running, unmentioned by
    anything, forever."""
    calls: list[list[str]] = []
    monkeypatch.setattr(wiz, "query", lambda argv: calls.append(list(argv)) or _ok(argv))
    monkeypatch.setattr(wiz, "host_ps_rows", lambda *a, **k: [])  # agent already gone
    monkeypatch.setattr(wiz, "compose_file_path", lambda h, n: tmp_path / "absent.yaml")
    wiz.down_container("local", H, "acme", purge=False)
    removed = [a[-1] for a in calls if "rm" in a and "-f" in a]
    assert wiz.egress_container_name("acme") in removed


# --- T118: the Phase A -> Phase B port-owner migration ----------------------


def _inspect(wiz, monkeypatch, payload: str):
    import subprocess

    monkeypatch.setattr(
        wiz, "query", lambda argv: subprocess.CompletedProcess(argv, 0, payload, "")
    )


def test_running_phase_a_container_is_detected_as_stale(wiz, monkeypatch):
    """A container that still publishes 2222 predates the shared namespace.

    THE IDENTITY LOCK CANNOT CATCH THIS: name, port number and all nine volume
    names are unchanged — only the service that publishes the port moved. So the
    baseline diff passes while the deployed shape is stale, and the environment
    keeps Phase A's cooperative enforcement while its declaration reads as a
    boundary.
    """
    _inspect(wiz, monkeypatch, '{"2222/tcp": [{"HostIp": "", "HostPort": "2206"}]}')
    assert wiz.phase_a_port_owner_stale(H, "acme", enforced=True) is True


def test_phase_b_container_publishes_nothing_and_is_not_stale(wiz, monkeypatch):
    _inspect(wiz, monkeypatch, "{}")
    assert wiz.phase_a_port_owner_stale(H, "acme", enforced=True) is False


def test_unenforced_environment_is_never_stale(wiz, monkeypatch):
    """With nothing enforced there is no egress service to own the port, so a
    published binding on the agent is CORRECT rather than left over."""
    _inspect(wiz, monkeypatch, '{"2222/tcp": [{"HostPort": "2206"}]}')
    assert wiz.phase_a_port_owner_stale(H, "acme", enforced=False) is False


def test_failed_inspect_does_not_report_stale(wiz, monkeypatch):
    """Never a false 'stale' from a failed probe — that would recreate a healthy
    environment on every apply, which is worse than the migration it is chasing."""
    import subprocess

    monkeypatch.setattr(wiz, "query", lambda argv: subprocess.CompletedProcess(argv, 1, "", "boom"))
    assert wiz.phase_a_port_owner_stale(H, "acme", enforced=True) is False
    monkeypatch.setattr(
        wiz, "query", lambda argv: subprocess.CompletedProcess(argv, 0, "not json", "")
    )
    assert wiz.phase_a_port_owner_stale(H, "acme", enforced=True) is False
