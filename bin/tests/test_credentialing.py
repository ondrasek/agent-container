"""Agent credentialing (Feature 003) unit tests — hermetic, no live runtime.

Covers the foundational injected-material staging + the US1 outbound push
credential: staging is ephemeral (targets under /run, never a persistent volume,
FR-012), fail-fast on a missing source (FR-016), the compose model carries the
material as `configs` with no secret value inlined (FR-011), and the outbound
push key is a DISTINCT credential from the inbound host key (SC-008). Real-
container push behavior is the acceptance tier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _key(tmp_path: Path, name: str = "push") -> Path:
    f = tmp_path / name
    f.write_bytes(
        b"-----BEGIN OPENSSH PRIVATE KEY-----\nFAKEKEYBYTES\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    return f


# --- foundational staging (T004) ---------------------------------------------


def test_stage_push_injection_stages_ephemeral_entries(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    pk = _key(tmp_path)
    kh = tmp_path / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAA\n")
    entries = wiz.stage_push_injection("local", "acme", pk, kh)
    by_name = {e[0]: e for e in entries}
    # both present, targeting the EPHEMERAL /run paths (never a volume)
    assert (
        by_name["push_key"][2]
        == wiz.INJECT_PUSH_KEY_PATH
        == "/run/agent-container/push_ed25519_key"
    )
    assert by_name["known_hosts"][2] == wiz.INJECT_KNOWN_HOSTS_PATH
    # staged locally under the per-host state dir, byte-identical, 0644 (state dir 0700)
    staged = by_name["push_key"][1]
    assert staged == wiz.host_state_dir("local") / "acme.push_key"
    assert staged.read_bytes() == pk.read_bytes()
    assert (staged.stat().st_mode & 0o777) == 0o644
    assert (wiz.host_state_dir("local").stat().st_mode & 0o777) == 0o700


def test_stage_push_injection_none_returns_empty(wiz):
    assert wiz.stage_push_injection("local", "acme", None, None) == []


def test_stage_push_injection_missing_key_dies(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="--push-key"):
        wiz.stage_push_injection("local", "acme", tmp_path / "nope", None)


def test_stage_push_injection_missing_known_hosts_dies(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    with pytest.raises(wiz.Fatal, match="--known-hosts"):
        wiz.stage_push_injection("local", "acme", _key(tmp_path), tmp_path / "nope")


def test_stage_push_injection_validates_key(wiz, monkeypatch, tmp_path):
    def _reject(p):
        raise wiz.Fatal("encrypted key")

    monkeypatch.setattr(wiz, "validate_private_key", _reject)
    with pytest.raises(wiz.Fatal, match="encrypted key"):
        wiz.stage_push_injection("local", "acme", _key(tmp_path), None)


# --- compose model wiring (T005 / T006) --------------------------------------


def test_build_compose_model_emits_injected_configs(wiz, tmp_path):
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"KEY")
    injected = [("push_key", push, wiz.INJECT_PUSH_KEY_PATH)]
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=injected)
    svc = model["services"]["agent"]
    assert {"source": "push_key", "target": wiz.INJECT_PUSH_KEY_PATH} in svc["configs"]
    assert model["configs"]["push_key"] == {"file": str(push)}


def test_push_key_distinct_from_host_key(wiz, tmp_path):
    """SC-008: the inbound host key and the outbound push key are two distinct
    credentials at two distinct targets — never conflated."""
    hk = tmp_path / "hk"
    hk.write_bytes(b"HOSTKEY")
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"PUSHKEY")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        host_key_file=hk,
        injected_configs=[("push_key", push, wiz.INJECT_PUSH_KEY_PATH)],
    )  # fmt: skip
    targets = {c["source"]: c["target"] for c in model["services"]["agent"]["configs"]}
    assert targets["ssh_host_key"] == wiz.INJECT_HOST_KEY_PATH
    assert targets["push_key"] == wiz.INJECT_PUSH_KEY_PATH
    assert targets["ssh_host_key"] != targets["push_key"]  # distinct
    assert model["configs"]["ssh_host_key"]["file"] != model["configs"]["push_key"]["file"]


def test_no_secret_value_inlined_in_compose_model(wiz, tmp_path):
    """FR-011: the compose model references the key by FILE path, never inlines the
    secret bytes."""
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"SUPERSECRETKEYBYTES")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        injected_configs=[("push_key", push, wiz.INJECT_PUSH_KEY_PATH)],
    )  # fmt: skip
    assert "SUPERSECRETKEYBYTES" not in json.dumps(model)


# --- CLI threading (T007) ----------------------------------------------------


def test_do_up_threads_push_material(wiz, monkeypatch, tmp_path):
    seen: dict = {}

    def _fake_exec(*a, **k):
        seen["push_key"] = k.get("push_key")
        seen["known_hosts"] = k.get("known_hosts")

    monkeypatch.setattr(
        wiz, "resolve_deploy_host", lambda h=None: ("local", {"driver": "docker", "context": ""})
    )
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: set())
    monkeypatch.setattr(wiz, "resolve_env_file", lambda n: tmp_path / "acme.env")
    (tmp_path / "acme.env").write_text("GH_TOKEN=x\n")
    monkeypatch.setattr(wiz, "compose_up_exec", _fake_exec)
    pk, kh = tmp_path / "pk", tmp_path / "kh"
    pk.write_bytes(b"K")
    kh.write_text("h\n")
    wiz.do_up("acme", push_key=pk, known_hosts=kh)
    assert seen == {"push_key": pk, "known_hosts": kh}
