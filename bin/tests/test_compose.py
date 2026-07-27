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
    # Top-level named volumes: exactly the nine per-container volumes.
    assert set(m["volumes"].keys()) == set(wiz.per_container_volumes("acme"))
    assert len(m["volumes"]) == 9
    # Each volume pins its `name` so compose does NOT project-prefix it — the
    # deterministic identity contract (Constitution IV) must be the real volume name.
    for vn in wiz.per_container_volumes("acme"):
        assert m["volumes"][vn] == {"name": vn}
    # And the service mounts all seven (short "name:path" syntax).
    assert m["services"]["agent"]["volumes"] == wiz.all_volume_mounts("acme")


def test_no_injection_means_no_secrets_or_configs(wiz):
    m = wiz.build_compose_model("acme", "/repo")
    assert "secrets" not in m
    assert "configs" not in m
    assert "secrets" not in m["services"]["agent"]
    assert "configs" not in m["services"]["agent"]


def test_host_key_maps_to_config(wiz, tmp_path):
    # Delivered as a compose `config` (not `secret`): a secret with an absolute
    # target crash-loops the container on some docker engines; configs are portable.
    hk = tmp_path / "acme.host_key"
    hk.write_text("PRIVATE-KEY-MATERIAL")
    m = wiz.build_compose_model("acme", "/repo", host_key_file=hk)
    assert "secrets" not in m  # never uses compose secrets
    assert m["configs"]["ssh_host_key"]["file"] == str(hk)
    assert {"source": "ssh_host_key", "target": wiz.INJECT_HOST_KEY_PATH} in m["services"]["agent"][
        "configs"
    ]


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


# --- Feature 010 FR-007: the compose model declares the NINE-volume set ------


def test_compose_declares_both_opencode_volumes_at_their_native_paths(wiz):
    """FR-006/FR-007. opencode is the one agent with two volumes: it follows XDG
    and splits config from credentials. Both mount at opencode's OWN paths, so
    guidance written for opencode applies verbatim inside the container."""
    m = wiz.build_compose_model("acme", "/repo")
    vols = m["services"]["agent"]["volumes"]
    assert "agent-container-acme-opencode:/home/dev/.config/opencode" in vols
    assert "agent-container-acme-opencode-data:/home/dev/.local/share/opencode" in vols
    assert len(m["volumes"]) == 9
    # Deterministic identity (Constitution IV): both names pin `name`.
    for v in ("agent-container-acme-opencode", "agent-container-acme-opencode-data"):
        assert m["volumes"][v] == {"name": v}


def test_non_persistent_workspace_still_declares_both_opencode_volumes(wiz):
    """The workspace volume stays conditional (Feature 004); opencode's two are
    unconditional, so bind/ephemeral declares eight."""
    for kwargs in (
        {"workspace_mount": "/host/w:/workspace", "declare_workspace_volume": False},
        {"workspace_mount": None, "declare_workspace_volume": False},
    ):
        m = wiz.build_compose_model("acme", "/repo", **kwargs)
        assert len(m["volumes"]) == 8
        assert wiz.volume_name("acme") not in m["volumes"]
        assert "agent-container-acme-opencode" in m["volumes"]
        assert "agent-container-acme-opencode-data" in m["volumes"]
