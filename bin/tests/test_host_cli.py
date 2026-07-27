"""host-management CLI (Feature 001, US1) tests: `host add` writes the registry
and `host ls` reflects it. Exercised through the underlying functions (no live
runtime needed — the capability probe is best-effort and never blocks
registration).
"""

from __future__ import annotations

import json
import subprocess

import pytest


def _ps(returncode, stdout="", stderr=""):
    """A fake `query()` result standing in for a `docker ps` invocation."""
    return lambda argv: subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_host_add_writes_registry_and_sets_default(wiz):
    wiz.cli_host_add("local", "docker", "lima-docker", None, False)
    reg = wiz.load_registry()
    h = wiz.get_host(reg, "local")
    assert h is not None
    assert h["driver"] == "docker"
    assert h["context"] == "lima-docker"
    assert h["address"] == "localhost"  # derived from a local context
    # First host becomes the default even without --default.
    assert wiz.default_host_name(reg) == "local"


def test_host_add_ssh_context_derives_remote_address(wiz):
    wiz.cli_host_add("hz1", "docker", "ssh://root@203.0.113.7", None, False)
    h = wiz.get_host(wiz.load_registry(), "hz1")
    assert h["address"] == "203.0.113.7"


def test_host_add_address_override(wiz):
    wiz.cli_host_add("hz1", "docker", "ssh://root@internal", "1.2.3.4", False)
    assert wiz.get_host(wiz.load_registry(), "hz1")["address"] == "1.2.3.4"


def test_second_host_default_only_when_requested(wiz):
    wiz.cli_host_add("local", "docker", "lima-docker", None, False)
    wiz.cli_host_add("hz1", "docker", "ssh://root@h", None, False)
    assert wiz.default_host_name(wiz.load_registry()) == "local"  # unchanged
    wiz.cli_host_add("hz2", "docker", "ssh://root@h2", None, True)
    assert wiz.default_host_name(wiz.load_registry()) == "hz2"  # --default moves it


def test_host_add_rejects_unknown_driver(wiz):
    with pytest.raises(wiz.Fatal, match="docker.*podman"):
        wiz.cli_host_add("x", "kubernetes", "ctx", None, False)


def test_host_add_requires_context(wiz):
    with pytest.raises(wiz.Fatal, match="needs --docker-context"):
        wiz.cli_host_add("x", "docker", None, None, False)


def test_host_add_podman_needs_connection(wiz):
    with pytest.raises(wiz.Fatal, match="needs --connection"):
        wiz.cli_host_add("x", "podman", None, None, False)


def test_host_ls_json_shows_default(wiz, capsys):
    # Feature 009: machine-readable payloads are wrapped in a VERSIONED envelope
    # (FR-006), so the record now lives under `data` and carries `schema`/`ok`.
    wiz.cli_host_add("local", "docker", "lima-docker", None, True)
    wiz.do_host_ls(as_json=True)
    env = json.loads(capsys.readouterr().out)
    assert env["schema"] == wiz.SCHEMA_VERSION and env["ok"] is True
    out = env["data"]
    assert out["default"] == "local"
    assert out["hosts"]["local"]["context"] == "lima-docker"


def test_host_ls_empty_is_not_an_error(wiz, capsys):
    wiz.do_host_ls(as_json=True)
    out = json.loads(capsys.readouterr().out)["data"]
    assert out == {"default": None, "hosts": {}}


# --- host show / rm / rm --destroy (Feature 001, US3 — safe teardown) ---------
# The safety invariants (FR-008/009/010, SC-005): a container teardown never
# touches the server; --destroy is refused for hosts the tool did not create,
# for non-hetzner providers, and while ANY container is still present; the token
# is fetched only on the destroy path after all refusals; the registry entry is
# removed only after a successful deprovision. All exercised via the underlying
# functions with host_container_names / provisioner_destroy monkeypatched.


def _tool_hz_host(name="hz1", **prov):
    p = {"provider": "hetzner", "server_id": 42, "created": True, **prov}
    return {
        "driver": "docker",
        "context": f"agent-container-{name}",
        "address": "203.0.113.9",
        "provisioning": p,
        "created_by_tool": True,
    }


def test_host_show_json_emits_record(make_registry, capsys):
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    wiz.do_host_show("hz1", as_json=True)
    out = json.loads(capsys.readouterr().out)["data"]
    assert out["name"] == "hz1"
    assert out["default"] is True
    assert out["driver"] == "docker"
    assert out["provisioning"]["server_id"] == 42
    assert out["created_by_tool"] is True


def test_host_show_unknown_dies(wiz):
    with pytest.raises(wiz.Fatal, match="no host named"):
        wiz.do_host_show("nope", as_json=True)


def test_host_rm_registration_only_removes_entry_and_warns(make_registry, monkeypatch, capsys):
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(
        wiz, "provisioner_destroy", lambda *a, **k: pytest.fail("must NOT deprovision")
    )
    wiz.cli_host_rm("hz1", destroy=False, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is None
    assert "left" in capsys.readouterr().err.lower()  # billable-server warning


def test_host_rm_destroy_refused_when_containers_present(make_registry, monkeypatch):
    # Drives the REAL assert_host_empty: a successful `ps` reporting a container.
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "query", _ps(0, "agent-container-x\n"))
    monkeypatch.setattr(
        wiz,
        "provisioner_destroy",
        lambda *a, **k: pytest.fail("must NOT deprovision a loaded host"),
    )
    with pytest.raises(wiz.Fatal, match="still present"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # not removed


def test_host_rm_destroy_fails_closed_on_enumeration_error(make_registry, monkeypatch):
    # THE fail-open regression (review finding #1/#2/#4): a FAILED `docker ps`
    # (unreachable daemon / down tunnel / wrong context) must REFUSE — never be
    # read as "empty" — even with a token present. Otherwise a loaded (or merely
    # unreachable) server could be destroyed. SC-005: refuse 100% of the time.
    wiz = make_registry({"hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    monkeypatch.setattr(wiz, "query", _ps(1, "", "Cannot connect to the Docker daemon"))
    monkeypatch.setattr(
        wiz,
        "provisioner_destroy",
        lambda *a, **k: pytest.fail("must NOT destroy an unverifiable host"),
    )
    with pytest.raises(wiz.Fatal, match="could not confirm"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # retained


def test_host_rm_destroy_refused_for_non_tool_host(make_registry, monkeypatch):
    host = {
        "driver": "existing-ssh",
        "context": "",
        "address": "198.51.100.7",
        "created_by_tool": False,
    }
    wiz = make_registry({"default": "r1", "hosts": {"r1": host}})
    monkeypatch.setattr(
        wiz, "provisioner_destroy", lambda *a, **k: pytest.fail("must NOT deprovision")
    )
    monkeypatch.setattr(
        wiz, "assert_host_empty", lambda *a, **k: pytest.fail("must NOT probe before refusing")
    )
    with pytest.raises(wiz.Fatal, match="did not create"):
        wiz.cli_host_rm("r1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "r1") is not None


def test_host_rm_destroy_refused_non_hetzner_provider(make_registry):
    wiz = make_registry({"hosts": {"a1": _tool_hz_host("a1", provider="aws")}})
    with pytest.raises(wiz.Fatal, match="no deprovisioner"):
        wiz.cli_host_rm("a1", destroy=True, yes=True)


def test_host_rm_destroy_requires_token(make_registry, monkeypatch):
    wiz = make_registry({"hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "query", _ps(0, ""))  # provably empty
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    with pytest.raises(wiz.Fatal, match="HCLOUD_TOKEN"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # token gate before unregister


def test_host_rm_destroy_happy_path_deprovisions_then_unregisters(make_registry, monkeypatch):
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "query", _ps(0, ""))  # provably empty
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    calls: list = []

    def _destroy(h, t):
        # Ordering: the host is still registered at the moment we deprovision — it
        # is unregistered ONLY AFTER a successful destroy (retryable on failure).
        assert wiz.get_host(wiz.load_registry(), "hz1") is not None
        calls.append((h["context"], t))

    monkeypatch.setattr(wiz, "provisioner_destroy", _destroy)
    wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert calls == [("agent-container-hz1", "tok")]  # deprovision ran, with the token
    assert wiz.get_host(wiz.load_registry(), "hz1") is None  # then unregistered


def test_host_rm_destroy_retains_registry_when_deprovision_fails(make_registry, monkeypatch):
    # Unregister only AFTER a successful destroy: a failed provisioner_destroy must
    # leave the host registered so the operator can retry (no orphaned billable
    # server with no record). Ties to hetzner_delete_server(strict=True).
    wiz = make_registry({"hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "query", _ps(0, ""))
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")

    def _boom(h, t):
        raise wiz.Fatal("server delete failed")

    monkeypatch.setattr(wiz, "provisioner_destroy", _boom)
    with pytest.raises(wiz.Fatal, match="server delete failed"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # retained for retry


def test_assert_host_empty_refuses_on_failed_enumeration(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "query", _ps(1, "", "boom"))
    with pytest.raises(wiz.Fatal, match="could not confirm"):
        wiz.assert_host_empty(_tool_hz_host())


def test_assert_host_empty_passes_when_proven_empty(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "query", _ps(0, ""))
    wiz.assert_host_empty(_tool_hz_host())  # returns without raising


def test_assert_host_empty_requires_the_tunnel_for_ssh_forward_hosts(wiz, monkeypatch):
    # The emptiness check must bring the socket-forward up (required=True) before
    # `ps`, so a not-yet-forwarded socket can't falsely report empty (finding #7).
    seen: dict = {}
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: seen.update(k))
    monkeypatch.setattr(wiz, "query", _ps(0, ""))
    h = _tool_hz_host()
    h["provisioning"]["connection"] = "ssh-forward"
    wiz.assert_host_empty(h)
    assert seen.get("required") is True


def test_host_rm_default_repointed_then_nulled(make_registry):
    a = {"driver": "docker", "context": "ca", "address": "localhost", "created_by_tool": False}
    b = {"driver": "docker", "context": "cb", "address": "localhost", "created_by_tool": False}
    wiz = make_registry({"default": "a", "hosts": {"a": a, "b": b}})
    wiz.cli_host_rm("a", destroy=False, yes=True)
    assert wiz.default_host_name(wiz.load_registry()) == "b"  # repointed to the survivor
    wiz.cli_host_rm("b", destroy=False, yes=True)
    reg = wiz.load_registry()
    assert wiz.default_host_name(reg) is None and reg["hosts"] == {}  # last host -> default null


def test_host_rm_unknown_dies(wiz):
    with pytest.raises(wiz.Fatal, match="no host named"):
        wiz.cli_host_rm("ghost", destroy=False, yes=True)
