"""Compose generation (Feature 001) tests: the per-container deployment is a
generated compose project emitted as JSON (a valid YAML subset). These pin its
structure, the seven declared volumes, the secrets/configs mapping for injected
SSH identity, and — a security invariant (Constitution III) — that NO secret
material is ever written inline; only `file:` references appear.
"""

from __future__ import annotations

import json

import pytest


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


# --- Feature 011 US3: the shell-env mount point moves, the NAME does not -----


def test_shellenv_mounts_at_agent_env_with_an_unchanged_name(wiz):
    """FR-009 / contract C5. `~/.agent-container` was confusable with the project
    config directory it has nothing to do with; `~/.agent-env` says what it is.

    The volume NAME is untouched (Constitution IV), so an existing volume
    reappears at the new path on recreate — contents are relocated, never
    stranded. Asserting both halves in one place is the point: a change that
    moved the name too would look identical from the mount string alone.
    """
    m = wiz.build_compose_model("acme", "/repo")
    mounts = dict(x.split(":", 1) for x in m["services"]["agent"]["volumes"] if ":" in x)
    assert mounts["agent-container-acme-shellenv"] == "/home/dev/.agent-env"
    assert "agent-container-acme-shellenv" in m["volumes"]  # name unchanged
    assert not any(v.endswith(":/home/dev/.agent-container") for v in mounts.values())


# --- Feature 012: the egress proxy in the generated model --------------------


def _model(wiz, tmp_path, **kw):
    return wiz.build_compose_model("acme", tmp_path / "image", **kw)


def test_no_declaration_leaves_the_model_byte_identical(wiz, tmp_path):
    """FR-004/FR-012 — the guarantee every existing environment depends on.

    Byte-identical, not merely equivalent: this is compared as serialized JSON
    because that is what actually reaches the daemon.
    """
    import json

    before = json.dumps(_model(wiz, tmp_path), indent=2, sort_keys=True)
    after = json.dumps(_model(wiz, tmp_path, egress_filter_body=None), indent=2, sort_keys=True)
    assert before == after
    assert "egress" not in before
    assert wiz.EGRESS_SERVICE_KEY not in _model(wiz, tmp_path)["services"]


def test_declaration_adds_exactly_one_service_and_no_volume(wiz, tmp_path):
    """The proxy must not touch the nine-volume identity contract (Constitution IV)."""
    plain = _model(wiz, tmp_path)
    withp = _model(wiz, tmp_path, egress_filter_body="api.anthropic.com\n")
    assert set(withp["services"]) - set(plain["services"]) == {"egress"}
    assert withp["volumes"] == plain["volumes"], "the volume set must be untouched"
    egress = withp["services"]["egress"]
    assert "volumes" not in egress
    assert "env_file" not in egress, "an operator env-file must not reach the security control"
    assert egress["cap_add"] == ["NET_ADMIN"], "the only privilege, and not on the agent"
    assert withp["configs"]["egress_acl"]["content"] == "api.anthropic.com\n"


def test_the_published_port_moves_to_the_egress_service(wiz, tmp_path):
    """T116/T117 — the identity migration the lock cannot see.

    A shared network namespace has exactly ONE port owner, and the daemon refuses
    `ports:` on a service using `network_mode: service:`. So the binding moves.

    The port NUMBER is unchanged, which is why `port_for_name` and every consumer
    still agree — and precisely why this needs its own test: the identity lock
    compares names and numbers and would pass while the owning service changed
    underneath it.
    """
    plain = _model(wiz, tmp_path)
    withp = _model(wiz, tmp_path, egress_filter_body="")
    port = f"{wiz.port_for_name('acme')}:2222"

    assert plain["services"]["agent"]["ports"] == [port], "unchanged without a declaration"
    assert "ports" not in withp["services"]["agent"], "the agent cannot publish in a shared netns"
    assert withp["services"]["egress"]["ports"] == [port], "same NUMBER, different owner"
    assert wiz.port_for_name("acme") == wiz.port_for_name("acme")


def test_agent_joins_the_namespace_and_gains_no_capability(wiz, tmp_path):
    """SC-011. The container running untrusted code must hold NOTHING."""
    withp = _model(wiz, tmp_path, egress_filter_body="")
    agent = withp["services"]["agent"]
    assert agent["network_mode"] == "service:egress"
    assert agent["depends_on"] == ["egress"]
    assert "cap_add" not in agent, "the agent must gain no capability — this is the whole design"


def test_all_three_surfaces_ride_the_configs_channel(wiz, tmp_path):
    """One declaration, three injected artefacts, all by `content:` — never
    `file:`, which is a bind of a local path and cannot reach a remote daemon."""
    m = _model(
        wiz,
        tmp_path,
        egress_filter_body="api.anthropic.com\n",
        egress_unbound_body="server:\n",
        egress_ports_body="iptables -A OUTPUT -p tcp -d 'github.com' --dport 22 -j ACCEPT\n",
    )
    cfgs = m["configs"]
    for key in ("egress_acl", "egress_unbound", "egress_ports"):
        assert "content" in cfgs[key] and "file" not in cfgs[key], f"{key} must be API-delivered"
    targets = {c["source"]: c["target"] for c in m["services"]["egress"]["configs"]}
    assert targets["egress_ports"].endswith("ports.rules")


def test_proxy_container_name_is_outside_the_environment_namespace(wiz, tmp_path):
    """Compose would name it `agent-container-acme-egress-1`, which begins with
    CONTAINER_PREFIX — and six sites treat any `agent-container-*` container as a
    deployable environment to list, pick or tear down."""
    cn = _model(wiz, tmp_path, egress_filter_body="")["services"]["egress"]["container_name"]
    assert not cn.startswith(wiz.CONTAINER_PREFIX), f"{cn} would be scanned as an environment"


def test_agent_is_pointed_at_the_proxy_in_both_cases(wiz, tmp_path):
    """Lowercase variants matter: curl, git and most HTTP clients read
    `https_proxy`, not `HTTPS_PROXY`."""
    env = _model(wiz, tmp_path, egress_filter_body="")["services"]["agent"]["environment"]
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        assert env[k] == f"http://egress:{wiz.EGRESS_PORT}"
    assert env["NO_PROXY"] == env["no_proxy"] == wiz.EGRESS_NO_PROXY


# --- FR-003c: the check that protects "commit AND push every change" ---------


def test_push_check_fires_for_an_https_remote_not_in_the_allowlist(wiz):
    """Probe-verified failure: under `allow: [{provider: anthropic}]`, git over HTTPS to
    github.com returns `CONNECT tunnel failed, response 403` — at push time."""
    with pytest.raises(wiz.Fatal, match="does not permit 'github.com'"):
        wiz.check_egress_permits_push(
            {"allow": [{"provider": "anthropic"}]}, "https://github.com/you/acme", "strict"
        )


def test_push_check_is_silent_when_the_host_is_declared(wiz):
    wiz.check_egress_permits_push(
        {"allow": [{"provider": "anthropic"}, {"host": "github.com"}]},
        "https://github.com/you/acme",
        "strict",
    )


def test_push_check_is_silent_for_ssh_remotes(wiz):
    """ssh does not honour https_proxy, so an SSH push is unaffected. This
    asymmetry is why the defect is invisible to anyone testing with a push key."""
    for url in ("git@github.com:you/acme.git", "ssh://git@github.com/you/acme"):
        wiz.check_egress_permits_push({"allow": [{"provider": "anthropic"}]}, url, "strict")


def test_push_check_is_silent_when_nothing_is_declared(wiz):
    wiz.check_egress_permits_push(None, "https://github.com/you/acme", "strict")


def test_push_check_warns_rather_than_dies_under_advisory(wiz):
    wiz.check_egress_permits_push(
        {"allow": [{"provider": "anthropic"}]}, "https://github.com/you/acme", "advisory"
    )


def test_push_check_uses_the_same_patterns_as_the_proxy(wiz):
    """The check and the enforcement must not be able to disagree — a wildcard the
    proxy would admit must not be reported as refused."""
    e = [("allow", "*.githubusercontent.com", None, "declaration")]
    assert wiz.egress_permits_host(e, "raw.githubusercontent.com")
    assert not wiz.egress_permits_host(e, "githubusercontent.com.attacker.net")


# --- C6: NO_PROXY cannot silently disable enforcement -----------------------

DECL = {"allow": [{"provider": "anthropic"}]}


def test_env_file_keys_reads_names_never_values(wiz, tmp_path):
    """The one place the tool opens an env file. Names only — a value must never be
    returned or logged, so the C6 check cannot become a secret-exposure path."""
    f = tmp_path / "e.env"
    f.write_text("# comment\nexport NO_PROXY=*\nGH_TOKEN=ghp_supersecret\nmalformed\n\n")
    keys = wiz.env_file_keys(f)
    assert keys == {"NO_PROXY", "GH_TOKEN"}
    assert not any("ghp_supersecret" in k for k in keys)


def test_operator_no_proxy_in_an_env_file_is_refused(wiz, tmp_path):
    f = tmp_path / "dev.env"
    f.write_text("NO_PROXY=*\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.refuse_operator_proxy_vars(DECL, "claude", [f])
    msg = str(e.value)
    assert "NO_PROXY" in msg and str(f) in msg, "must name the variable AND the file"


def test_a_harmless_looking_no_proxy_is_refused_too(wiz, tmp_path):
    """No subset comparison is attempted, deliberately. A check that judged some
    values 'safe' would fail OPEN on the ones it did not anticipate — reproducing
    the bypass it exists to prevent, while passing its own tests."""
    f = tmp_path / "dev.env"
    f.write_text("NO_PROXY=localhost\n")
    with pytest.raises(wiz.Fatal, match="NO_PROXY"):
        wiz.refuse_operator_proxy_vars(DECL, "claude", [f])


def test_operator_https_proxy_is_refused(wiz, tmp_path):
    """Redirecting the agent at a DIFFERENT proxy defeats the allowlist just as
    completely as skipping one."""
    f = tmp_path / "dev.env"
    f.write_text("https_proxy=http://elsewhere:3128\n")
    with pytest.raises(wiz.Fatal, match="https_proxy"):
        wiz.refuse_operator_proxy_vars(DECL, "claude", [f])


def test_a_credential_named_no_proxy_is_refused(wiz):
    """`stage_declared_credentials` validates names against [A-Za-z_][A-Za-z0-9_]*,
    which NO_PROXY matches — and then writes the name into the merged env file."""
    with pytest.raises(wiz.Fatal, match="NO_PROXY"):
        wiz.refuse_operator_proxy_vars(DECL, "claude", None, ["GH_TOKEN", "NO_PROXY"])


def test_a_sidecar_override_setting_no_proxy_is_refused(wiz, tmp_path):
    """The override rides as the SECOND -f and wins the compose merge. Detected via
    yaml.safe_load — the old column-0 scanner returned [] for this exact shape."""
    o = tmp_path / "dev.services.yaml"
    o.write_text("services:\n  agent:\n    environment:\n      NO_PROXY: '*'\n")
    with pytest.raises(wiz.Fatal, match="NO_PROXY"):
        wiz.refuse_operator_proxy_vars(DECL, "claude", None, None, o)


def test_flow_style_override_is_also_caught(wiz, tmp_path):
    """The form the regex scanner silently missed."""
    o = tmp_path / "dev.services.yaml"
    o.write_text("services: {agent: {environment: {NO_PROXY: '*'}}}\n")
    with pytest.raises(wiz.Fatal, match="NO_PROXY"):
        wiz.refuse_operator_proxy_vars(DECL, "claude", None, None, o)


def test_no_declaration_means_no_refusal(wiz, tmp_path):
    """Today's behaviour is untouched for anyone not using the feature."""
    f = tmp_path / "dev.env"
    f.write_text("NO_PROXY=*\n")
    wiz.refuse_operator_proxy_vars(None, "claude", [f])


def test_unenforced_declaration_means_no_refusal(wiz, tmp_path):
    """An unenforced declaration makes no guarantee for NO_PROXY to contradict, so
    refusing would be noise — the operator has already been told it is not enforced."""
    f = tmp_path / "dev.env"
    f.write_text("NO_PROXY=*\n")
    wiz.refuse_operator_proxy_vars(DECL, "some-future-agent", [f])


def test_unrelated_env_vars_are_untouched(wiz, tmp_path):
    f = tmp_path / "dev.env"
    f.write_text("GH_TOKEN=x\nFOO=bar\n")
    wiz.refuse_operator_proxy_vars(DECL, "claude", [f])
