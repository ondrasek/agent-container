"""Container lifecycle engine (Feature 002) unit tests — hermetic, no live runtime.

Covers the net-new foundational pieces and the US2 verbs' guard behavior:
the per-(host,name) deployment lock (FR-017), the new compose-subcommand argv
builders (R1/R2/R3), and the verbs' fail-fast/confirmation guards. Real-container
behavior (stop→start→redeploy→wipe, volume preservation) is the acceptance tier.
"""

from __future__ import annotations

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
    assert wiz.driver_down_argv(H, "p", F)[-1] == "down"
    assert wiz.driver_down_argv(H, "p", F, purge=True)[-2:] == ["down", "--volumes"]
    assert wiz.driver_down_argv(H, "p", F, purge=True, rmi_local=True)[-4:] == [
        "down", "--volumes", "--rmi", "local",
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
