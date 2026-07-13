"""host-management CLI (Feature 001, US1) tests: `host add` writes the registry
and `host ls` reflects it. Exercised through the underlying functions (no live
runtime needed — the capability probe is best-effort and never blocks
registration).
"""

from __future__ import annotations

import json

import pytest


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
    wiz.cli_host_add("local", "docker", "lima-docker", None, True)
    wiz.do_host_ls(as_json=True)
    out = json.loads(capsys.readouterr().out)
    assert out["default"] == "local"
    assert out["hosts"]["local"]["context"] == "lima-docker"


def test_host_ls_empty_is_not_an_error(wiz, capsys):
    wiz.do_host_ls(as_json=True)
    out = json.loads(capsys.readouterr().out)
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
    out = json.loads(capsys.readouterr().out)
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
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: {"agent-container-x"})
    monkeypatch.setattr(
        wiz,
        "provisioner_destroy",
        lambda *a, **k: pytest.fail("must NOT deprovision a loaded host"),
    )
    with pytest.raises(wiz.Fatal, match="still present"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # not removed


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
        wiz, "host_container_names", lambda *a, **k: pytest.fail("must NOT probe before refusing")
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
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: set())
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    with pytest.raises(wiz.Fatal, match="HCLOUD_TOKEN"):
        wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert wiz.get_host(wiz.load_registry(), "hz1") is not None  # token gate before unregister


def test_host_rm_destroy_happy_path_deprovisions_then_unregisters(make_registry, monkeypatch):
    wiz = make_registry({"default": "hz1", "hosts": {"hz1": _tool_hz_host()}})
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: set())
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    calls: list = []
    monkeypatch.setattr(wiz, "provisioner_destroy", lambda h, t: calls.append((h["context"], t)))
    wiz.cli_host_rm("hz1", destroy=True, yes=True)
    assert calls == [("agent-container-hz1", "tok")]  # deprovision ran, with the token
    assert wiz.get_host(wiz.load_registry(), "hz1") is None  # then unregistered


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
