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
