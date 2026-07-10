"""Hetzner provisioner (Feature 001, US2) unit tests — token-free and
network-free. They pin the SECURITY and SAFETY invariants that must hold without
a real token: the HCLOUD_TOKEN never reaches argv/records (only the Bearer
header), a post-allocation failure destroys the half-provisioned server, a
missing token fails before any HTTP call, and --reuse never allocates.

The real create/cloud-init/ssh-context behavior is NOT covered here — that needs
a real token and is the opt-in tokened acceptance test.
"""

from __future__ import annotations

import json
import subprocess

import pytest


class FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def hcloud(wiz, monkeypatch):
    """Wire a fake Hetzner transport + stubbed local docker/ssh. Records every
    urllib Request and every subprocess argv so tests can assert on them."""
    reqs: list = []
    argvs: list[list[str]] = []
    # POST /servers -> a running server with an IPv4; DELETE -> ok.
    server = {"id": 42, "public_net": {"ipv4": {"ip": "203.0.113.9"}}}

    def fake_urlopen(req, timeout=None):
        reqs.append(req)
        method = req.get_method()
        if method == "POST":
            return FakeResp(201, {"server": server})
        if method == "GET":
            return FakeResp(200, {"server": server})
        if method == "DELETE":
            return FakeResp(200, {"action": {"id": 1}})
        return FakeResp(200, {})

    monkeypatch.setattr(wiz.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        wiz,
        "query",
        lambda a: (argvs.append(list(a)), subprocess.CompletedProcess(a, 0, stdout="", stderr=""))[
            1
        ],
    )
    monkeypatch.setattr(wiz, "wait_until_reachable", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "resolve_operator_pubkey", lambda o=None: "ssh-ed25519 AAAA op@host")
    return wiz, reqs, argvs


def _auth_headers(reqs) -> list[str]:
    return [r.get_header("Authorization") for r in reqs if r.get_header("Authorization")]


def test_token_only_in_header_never_on_argv_or_record(hcloud, monkeypatch):
    wiz, reqs, argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "SECRET-TOKEN-XYZ")
    rec = wiz.provision_host(
        "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
    )
    # Present in the Bearer header...
    assert "Bearer SECRET-TOKEN-XYZ" in _auth_headers(reqs)
    # ...never on any subprocess argv (docker/ssh/context)...
    assert all("SECRET-TOKEN-XYZ" not in " ".join(a) for a in argvs)
    # ...and never in the returned Host record or a registry round-trip.
    assert "SECRET-TOKEN-XYZ" not in json.dumps(rec)


def test_create_returns_docker_driver_host(hcloud, monkeypatch):
    wiz, _reqs, _argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    rec = wiz.provision_host(
        "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
    )
    assert rec["driver"] == "docker"
    assert rec["context"] == "agent-container-hz1"  # named local docker context
    assert rec["address"] == "203.0.113.9"
    assert rec["created_by_tool"] is True
    assert rec["provisioning"]["server_id"] == 42
    assert rec["provisioning"]["provider"] == "hetzner"
    # The record drives the existing driver seam unchanged.
    assert wiz.driver_runtime_argv(rec) == ["docker", "--context", "agent-container-hz1"]


def test_cleanup_destroys_server_on_post_allocation_failure(hcloud, monkeypatch):
    wiz, reqs, _argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    # Allocation (POST) succeeds, but reachability fails after the server exists.
    monkeypatch.setattr(
        wiz, "wait_until_reachable", lambda *a, **k: wiz.die("docker never came up")
    )
    with pytest.raises(wiz.Fatal):
        wiz.provision_host(
            "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
        )
    # A DELETE for the allocated server id was issued (no orphaned billable server).
    deletes = [r for r in reqs if r.get_method() == "DELETE" and r.full_url.endswith("/servers/42")]
    assert len(deletes) == 1


def test_missing_token_dies_before_any_http(wiz, monkeypatch):
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    called = {"urlopen": False}
    monkeypatch.setattr(
        wiz.urllib.request,
        "urlopen",
        lambda *a, **k: called.__setitem__("urlopen", True) or FakeResp(200, {}),
    )
    with pytest.raises(wiz.Fatal, match="HCLOUD_TOKEN"):
        wiz.provision_host(
            "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
        )
    assert called["urlopen"] is False  # never reached the network


def test_reuse_never_provisions(wiz, monkeypatch):
    # --reuse must register an existing server without touching the provider API.
    monkeypatch.setattr(
        wiz.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("urlopen must not be called for --reuse"),
    )
    wiz.cli_host_add(
        "hzold",
        "docker",
        "ssh://root@198.51.100.7",
        None,
        False,
        provider="hetzner",
        reuse=True,
    )
    rec = wiz.get_host(wiz.load_registry(), "hzold")
    assert rec["created_by_tool"] is False
    assert rec["provisioning"]["created"] is False


def test_create_and_reuse_are_mutually_exclusive(wiz):
    with pytest.raises(wiz.Fatal, match="exactly one of --create"):
        wiz.cli_host_add(
            "x", "docker", None, None, False, provider="hetzner", create=True, reuse=True
        )
    with pytest.raises(wiz.Fatal, match="exactly one of --create"):
        wiz.cli_host_add(
            "x", "docker", None, None, False, provider="hetzner", create=False, reuse=False
        )


def test_unknown_provider_dies(wiz, monkeypatch):
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    with pytest.raises(wiz.Fatal, match="unknown --provider"):
        wiz.provision_host(
            "aws", "x", server_type=None, location=None, ssh_key=None, ssh_pubkey=None
        )


def test_user_data_is_cloud_config_with_key_and_docker(wiz):
    ud = wiz.hetzner_build_user_data("ssh-ed25519 AAAA op@host")
    assert ud.startswith("#cloud-config\n")
    assert "ssh-ed25519 AAAA op@host" in ud
    assert "docker-ce" in ud and "docker-compose-plugin" in ud
