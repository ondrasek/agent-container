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

    def fake_open(req, timeout=None):
        reqs.append(req)
        method, path = req.get_method(), req.full_url
        if "/ssh_keys" in path:
            if method == "POST":
                return FakeResp(201, {"ssh_key": {"id": 7}})  # we uploaded it
            if method == "GET":
                return FakeResp(200, {"ssh_keys": []})  # none exist -> upload
            return FakeResp(200, {"action": {"id": 1}})  # DELETE
        if method == "POST":  # /servers
            return FakeResp(201, {"server": server})
        if method == "GET":  # /servers/<id>
            return FakeResp(200, {"server": server})
        return FakeResp(200, {"action": {"id": 1}})  # DELETE /servers/<id>

    monkeypatch.setattr(wiz._HCLOUD_OPENER, "open", fake_open)
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
    assert rec["provisioning"]["ssh_key_id"] == 7  # we uploaded it -> destroy removes it
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
    called = {"open": False}
    monkeypatch.setattr(
        wiz._HCLOUD_OPENER,
        "open",
        lambda *a, **k: called.__setitem__("open", True) or FakeResp(200, {}),
    )
    with pytest.raises(wiz.Fatal, match="HCLOUD_TOKEN"):
        wiz.provision_host(
            "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
        )
    assert called["open"] is False  # never reached the network


def test_reuse_never_provisions(wiz, monkeypatch):
    # --reuse must register an existing server without touching the provider API.
    monkeypatch.setattr(
        wiz._HCLOUD_OPENER,
        "open",
        lambda *a, **k: pytest.fail("the Hetzner API must not be called for --reuse"),
    )
    # --reuse wraps an ssh:// URL in a named context (local docker call) — stub it.
    argvs: list[list[str]] = []
    monkeypatch.setattr(
        wiz,
        "query",
        lambda a: (argvs.append(list(a)), subprocess.CompletedProcess(a, 0, stdout="", stderr=""))[
            1
        ],
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
    # A named context was created (so `docker --context <name>` works), not the raw URL.
    assert rec["context"] == "agent-container-hzold"
    assert any(a[:3] == ["docker", "context", "create"] for a in argvs)


def test_keyboard_interrupt_during_wait_still_destroys_server(hcloud, monkeypatch):
    wiz, reqs, _argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "t")

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(wiz, "wait_until_reachable", boom)
    with pytest.raises(KeyboardInterrupt):
        wiz.provision_host(
            "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
        )
    # Ctrl-C mid-provision must NOT orphan the billable server.
    assert any(r.get_method() == "DELETE" and r.full_url.endswith("/servers/42") for r in reqs)


def test_missing_binary_during_provision_still_destroys_server(hcloud, monkeypatch):
    wiz, reqs, _argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    monkeypatch.setattr(
        wiz,
        "docker_context_create",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
    )
    with pytest.raises(FileNotFoundError):
        wiz.provision_host(
            "hetzner", "hz1", server_type="cax11", location="nbg1", ssh_key=None, ssh_pubkey=None
        )
    assert any(r.get_method() == "DELETE" and r.full_url.endswith("/servers/42") for r in reqs)


def test_defaults_reach_the_create_body(hcloud, monkeypatch):
    wiz, reqs, _argvs = hcloud
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    wiz.provision_host(
        "hetzner", "hz1", server_type=None, location=None, ssh_key=None, ssh_pubkey=None
    )
    post = next(r for r in reqs if r.get_method() == "POST" and r.full_url.endswith("/servers"))
    body = json.loads(post.data)
    assert body["server_type"] == "cax11"  # HETZNER_DEFAULT_SERVER_TYPE
    assert body["location"] == "nbg1"  # HETZNER_DEFAULT_LOCATION
    assert body["image"] == "debian-12"
    assert body["ssh_keys"] == [7]  # the uploaded operator key id (root injection)
    assert body["user_data"].startswith("#cloud-config")


def test_provider_rejects_non_rfc1123_name(wiz, monkeypatch):
    monkeypatch.setenv("HCLOUD_TOKEN", "t")
    called = {"open": False}
    monkeypatch.setattr(
        wiz._HCLOUD_OPENER, "open", lambda *a, **k: called.__setitem__("open", True)
    )
    with pytest.raises(wiz.Fatal, match="RFC-1123"):
        wiz.provision_host(
            "hetzner", "my_box", server_type=None, location=None, ssh_key=None, ssh_pubkey=None
        )
    assert called["open"] is False  # rejected before allocation


def test_reject_private_key_as_operator_pubkey(wiz, tmp_path):
    priv = tmp_path / "id_ed25519"
    priv.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nxxxx\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    with pytest.raises(wiz.Fatal, match="PUBLIC key"):
        wiz.resolve_operator_pubkey(priv)


def test_hcloud_request_retries_transient_5xx_on_get(wiz, monkeypatch):
    import io

    calls = {"n": 0}

    def flaky_open(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise wiz.urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b""))
        return FakeResp(200, {"servers": []})

    monkeypatch.setattr(wiz._HCLOUD_OPENER, "open", flaky_open)
    monkeypatch.setattr(wiz.time, "sleep", lambda *_: None)  # no real backoff wait
    status, resp = wiz._hcloud_request("GET", "/servers", "t")
    assert status == 200 and calls["n"] == 2  # retried once, then succeeded


def test_provisioner_destroy_refuses_foreign_host(wiz):
    with pytest.raises(wiz.Fatal, match="did not create"):
        wiz.provisioner_destroy({"created_by_tool": False, "provisioning": {"server_id": 5}}, "t")


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


def test_user_data_installs_docker_and_carries_no_key(wiz):
    # Docker-install only: key auth is via the Hetzner ssh_keys API (root
    # injection), NOT cloud-init, which does not authorize root on this image.
    ud = wiz.hetzner_build_user_data()
    assert ud.startswith("#cloud-config\n")
    assert "docker-ce" in ud and "docker-compose-plugin" in ud
    assert "ssh_authorized_keys" not in ud
    assert "bookworm" in ud  # apt suite pinned (no fragile nested $(...) quoting)


def test_ensure_ssh_key_reuses_existing_by_public_key(wiz, monkeypatch):
    # When the operator's key is already in the project, reuse it (created_by_us
    # False) so destroy never removes a key they use elsewhere.
    calls: list = []

    def fake_open(req, timeout=None):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            return FakeResp(
                200, {"ssh_keys": [{"id": 99, "name": "x", "public_key": "ssh-ed25519 AAAA me"}]}
            )
        pytest.fail("must not POST/DELETE when the key already exists")

    monkeypatch.setattr(wiz._HCLOUD_OPENER, "open", fake_open)
    key_id, created = wiz.hetzner_ensure_ssh_key(
        "agent-container-hz1", "ssh-ed25519 AAAA me@host", "t"
    )
    assert key_id == 99 and created is False
