"""Compose generation (Feature 001) tests: the per-container deployment is a
generated compose project emitted as JSON (a valid YAML subset). These pin its
structure, the seven declared volumes, the secrets/configs mapping for injected
SSH identity, and — a security invariant (Constitution III) — that NO secret
material is ever written inline; only `file:` references appear.
"""

from __future__ import annotations

import json


def test_project_name(wiz):
    assert wiz.compose_project("acme") == "agent-container-acme"


def test_model_has_service_build_restart_port(wiz):
    m = wiz.build_compose_model("acme", "/repo")
    svc = m["services"]["agent"]
    assert svc["container_name"] == "agent-container-acme"
    assert svc["build"]["context"] == "/repo"
    assert svc["restart"] == "unless-stopped"
    assert svc["ports"] == [f"{wiz.port_for_name('acme')}:2222"]
    assert m["name"] == "agent-container-acme"


def test_model_declares_seven_named_volumes(wiz):
    m = wiz.build_compose_model("acme", "/repo")
    # Top-level named volumes: exactly the seven per-container volumes.
    assert set(m["volumes"].keys()) == set(wiz.per_container_volumes("acme"))
    assert len(m["volumes"]) == 7
    # And the service mounts all seven (short "name:path" syntax).
    assert m["services"]["agent"]["volumes"] == wiz.all_volume_mounts("acme")


def test_no_injection_means_no_secrets_or_configs(wiz):
    m = wiz.build_compose_model("acme", "/repo")
    assert "secrets" not in m
    assert "configs" not in m
    assert "secrets" not in m["services"]["agent"]
    assert "configs" not in m["services"]["agent"]


def test_host_key_maps_to_secret(wiz, tmp_path):
    hk = tmp_path / "acme.host_key"
    hk.write_text("PRIVATE-KEY-MATERIAL")
    m = wiz.build_compose_model("acme", "/repo", host_key_file=hk)
    assert m["secrets"]["ssh_host_key"]["file"] == str(hk)
    svc_secrets = m["services"]["agent"]["secrets"]
    assert svc_secrets == [{"source": "ssh_host_key", "target": wiz.INJECT_HOST_KEY_PATH}]


def test_authorized_keys_maps_to_config(wiz, tmp_path):
    ak = tmp_path / "acme.authorized_keys"
    ak.write_text("ssh-ed25519 AAAA... user@host")
    m = wiz.build_compose_model("acme", "/repo", authorized_keys_file=ak)
    assert m["configs"]["ssh_authorized_keys"]["file"] == str(ak)
    svc_configs = m["services"]["agent"]["configs"]
    assert svc_configs == [
        {"source": "ssh_authorized_keys", "target": wiz.INJECT_AUTHORIZED_KEYS_PATH}
    ]


def test_no_secret_material_inline(wiz, tmp_path):
    # The private key material must never appear anywhere in the serialized model.
    hk = tmp_path / "acme.host_key"
    secret = "TOP-SECRET-PRIVATE-KEY-BYTES"
    hk.write_text(secret)
    ak = tmp_path / "acme.authorized_keys"
    ak.write_text("ssh-ed25519 AAAA... user@host")
    m = wiz.build_compose_model("acme", "/repo", host_key_file=hk, authorized_keys_file=ak)
    blob = json.dumps(m)
    assert secret not in blob  # only the path is referenced, not the contents


def test_output_is_valid_json_and_deterministic(wiz, tmp_path):
    m1 = wiz.build_compose_model("acme", "/repo")
    m2 = wiz.build_compose_model("acme", "/repo")
    assert json.dumps(m1) == json.dumps(m2)  # deterministic
    # Round-trips through JSON (i.e. it is JSON-serializable = valid YAML subset).
    assert json.loads(json.dumps(m1)) == m1


def test_write_compose_file_lands_under_host_state_dir(wiz, tmp_path):
    m = wiz.build_compose_model("acme", "/repo")
    p = wiz.write_compose_file("local", "acme", m)
    assert p == wiz.host_state_dir("local") / "acme.compose.yaml"
    assert p.is_file()
    assert json.loads(p.read_text()) == m
    assert p.read_text().endswith("\n")
