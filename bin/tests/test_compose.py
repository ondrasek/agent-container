"""Compose generation (Feature 001) tests: the per-container deployment is a
generated compose project emitted as JSON (a valid YAML subset). These pin its
structure, the seven declared volumes, the secrets/configs mapping for injected
SSH identity, and — a security invariant (Constitution III) — that NO secret
material is ever written inline; only `file:` references appear.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml


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
    # `service_healthy`, not the bare list: the list form waits only for the
    # container to be STARTED, and netfilter is installed before squid serves —
    # so the agent would run against a boundary that refuses everything, which
    # is indistinguishable from "nothing is declared" (measured: curl exit 7
    # immediately after `up`, exit 0 three seconds later).
    assert agent["depends_on"] == {"egress": {"condition": "service_healthy"}}
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
        assert env[k] == f"http://127.0.0.1:{wiz.EGRESS_PORT}", (
            "the proxy must be addressed on loopback: the agent shares the "
            "sidecar's netns, and a service name would need the very DNS the "
            "allowlist refuses"
        )
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


def test_push_check_is_silent_for_ssh_remotes_under_PROXY_enforcement(wiz):
    """ssh does not honour https_proxy, so an SSH push is unaffected BY THE PROXY.
    This asymmetry is why the defect is invisible to anyone testing with a push key.

    Narrowed deliberately — the old name claimed SSH is always safe, which Phase B
    made false. Under a packet-level boundary port 22 is closed unless declared.
    """
    for url in ("git@github.com:you/acme.git", "ssh://git@github.com/you/acme"):
        wiz.check_egress_permits_push({"allow": [{"provider": "anthropic"}]}, url, "strict")


# --- T132: the SSH arm, which exists only under transparent enforcement -------


@pytest.mark.parametrize(
    "url,host,port",
    [
        ("git@github.com:you/acme.git", "github.com", 22),
        ("ssh://git@github.com/you/acme", "github.com", 22),
        ("ssh://git@git.example.com:2222/you/acme", "git.example.com", 2222),
    ],
)
def test_push_check_fires_for_an_undeclared_ssh_remote_under_transparent(wiz, url, host, port):
    """Default-deny is at the PACKET level, so port 22 is closed unless declared —
    Hard Constraint #1 breaking with SSH as the casualty rather than the survivor."""
    with pytest.raises(wiz.Fatal, match=f"does not permit '{host}' on port {port}"):
        wiz.check_egress_permits_push(
            {"allow": [{"provider": "anthropic"}]}, url, "strict", transparent=True
        )


def test_push_check_is_silent_when_the_ssh_endpoint_is_declared(wiz):
    wiz.check_egress_permits_push(
        {"allow": [{"provider": "anthropic"}, {"host": "github.com", "port": 22}]},
        "git@github.com:you/acme.git",
        "strict",
        transparent=True,
    )


def test_declaring_the_host_over_https_does_not_open_port_22(wiz):
    """FR-018a: the port SELECTS the mechanism. A portless entry is the proxy's
    surface and says nothing about reaching the same host on 22 — so accepting it
    here would report a push as safe that default-deny will refuse."""
    with pytest.raises(wiz.Fatal, match="on port 22"):
        wiz.check_egress_permits_push(
            {"allow": [{"host": "github.com"}]},
            "git@github.com:you/acme.git",
            "strict",
            transparent=True,
        )


def test_declaring_a_different_port_does_not_open_22(wiz):
    with pytest.raises(wiz.Fatal, match="on port 22"):
        wiz.check_egress_permits_push(
            {"allow": [{"host": "github.com", "port": 2222}]},
            "git@github.com:you/acme.git",
            "strict",
            transparent=True,
        )


# --- the remediation a refusal prints must survive the tool's own validator ----


def _remediation_entries(message: str) -> list:
    """Pull the `egress.allow: [...]` snippet a refusal offers, as parsed YAML."""
    m = re.search(r"egress\.allow:\s*(\[.*?\])", message, re.S)
    assert m, f"the refusal offers no `egress.allow:` remediation:\n{message}"
    return yaml.safe_load(m.group(1))


@pytest.mark.parametrize(
    "egress,url,transparent",
    [
        ({"allow": [{"provider": "anthropic"}]}, "https://github.com/you/acme", False),
        ({"allow": [{"provider": "anthropic"}]}, "git@github.com:you/acme.git", True),
        ({"allow": [{"provider": "anthropic"}]}, "ssh://git@git.example.com:2222/x", True),
    ],
)
def test_the_push_refusal_offers_config_the_validator_accepts(wiz, egress, url, transparent):
    """The HTTPS arm printed `egress.allow: [github.com]` — a bare string, which
    `validate_destination` refuses ("must be a mapping"). The operator was sent
    from one refusal into a second one the TOOL had authored, with the first
    message still reading as correct help. Parse what the refusal offers and put
    it back through the validator, so the two cannot drift apart again.
    """
    with pytest.raises(wiz.Fatal) as exc:
        wiz.check_egress_permits_push(egress, url, "strict", transparent=transparent)
    entries = _remediation_entries(str(exc.value))
    assert entries, "the remediation parsed to an empty list"
    for entry in entries:
        wiz.validate_destination(entry, "remediation")


def test_the_builtin_default_refusal_offers_config_the_validator_accepts(wiz):
    """The same defect, one message over: it named `egress.providers:`, which
    `validate_egress` refuses OUTRIGHT (FR-018b) — answering a warning with a
    hard failure."""
    with pytest.raises(wiz.Fatal) as exc:
        wiz.check_builtin_default_declared(
            {"allow": [{"provider": "anthropic"}]}, "opencode", "strict"
        )
    msg = str(exc.value)
    assert "egress.providers" not in msg, "the remediation names the one refused key"
    for entry in _remediation_entries(msg):
        wiz.validate_destination(entry, "remediation")
    # And the whole block it implies must validate, not just the entry.
    wiz.validate_egress({"allow": _remediation_entries(msg)}, "remediation")


def test_ssh_endpoint_parsing_rejects_a_non_numeric_port(wiz):
    """Coercing it to 22 would check an endpoint the push never uses, and a check
    that passes for the WRONG endpoint is worse than no check."""
    assert wiz.ssh_remote_endpoint("ssh://git@h:notaport/x") is None
    assert wiz.ssh_remote_endpoint("ssh://git@h:99999/x") is None


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
    refusing would be noise — the operator has already been told it is not enforced.

    The obstacle is an override of the egress service. An unprobed AGENT no longer
    qualifies: transparent enforcement asks the agent for nothing, so that
    environment IS enforced and its NO_PROXY is refused like any other.
    """
    f = tmp_path / "dev.env"
    f.write_text("NO_PROXY=*\n")
    o = tmp_path / "dev.services.yaml"
    o.write_text("services:\n  egress:\n    image: someone/else\n")
    wiz.refuse_operator_proxy_vars(DECL, "claude", [f], None, o)


def test_unrelated_env_vars_are_untouched(wiz, tmp_path):
    f = tmp_path / "dev.env"
    f.write_text("GH_TOKEN=x\nFOO=bar\n")
    wiz.refuse_operator_proxy_vars(DECL, "claude", [f])


# --- T120-T123: the sidecar boundary ----------------------------------------

DECL_A = {"allow": [{"provider": "anthropic"}]}


def _override(tmp_path, body: str):
    o = tmp_path / "dev.services.yaml"
    o.write_text(body)
    return o


def test_sidecars_join_the_boundary_by_default(wiz, tmp_path):
    """FR-023. ANY sidecar the agent can reach with free egress IS a bypass — the
    agent need not escape anything, only ask something that already has the
    access (`redis REPLICAOF`, `postgres COPY … FROM PROGRAM`). Inside is the
    default because "a redis is a bypass" is not obvious to whoever adds one.
    """
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n  db:\n    image: pg\n")
    overlay = wiz.build_sidecar_boundary_overlay(o, DECL_A)
    assert set(overlay["services"]) == {"redis", "db"}
    assert overlay["services"]["redis"]["network_mode"] == "service:egress"


def test_declared_opt_out_leaves_a_sidecar_outside(wiz, tmp_path):
    """FR-023a. Some sidecars legitimately need their own egress — a feed sync on
    its own schedule. That must be a CALL, not a default."""
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n  feed:\n    image: f\n")
    overlay = wiz.build_sidecar_boundary_overlay(o, {**DECL_A, "sidecars_outside": ["feed"]})
    assert set(overlay["services"]) == {"redis"}, "feed must be left alone"


def test_opt_out_naming_a_missing_service_is_refused(wiz, tmp_path):
    """The failure this prevents is a RENAME. A spec naming the old service while
    the override declares a new one leaves reality and the declaration disagreeing
    — and which way round is unknowable from here, so it is refused, not guessed.
    """
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.verify_sidecars_outside_resolve({**DECL_A, "sidecars_outside": ["typo"]}, o)
    msg = str(e.value)
    assert "typo" in msg and "redis" in msg, "must name both the miss and what IS declared"


def test_opt_out_with_no_sidecars_at_all_is_refused(wiz):
    with pytest.raises(wiz.Fatal, match="no sidecars"):
        wiz.verify_sidecars_outside_resolve({**DECL_A, "sidecars_outside": ["ghost"]}, None)


def test_opt_out_may_not_name_the_agent_or_the_proxy(wiz, tmp_path):
    """Neither is an operator sidecar. The agent outside the boundary is the
    feature switched off while still reporting a declaration; the egress service
    outside its own namespace is incoherent."""
    for svc in ("agent", "egress"):
        root = tmp_path / svc
        (root / ".agent-container").mkdir(parents=True)
        (root / ".agent-container" / "environments.yaml").write_text(
            "environments:\n  - name: acme\n    host: local\n    egress:\n"
            "      allow: []\n"
            f"      sidecars_outside: [{svc}]\n"
        )
        with pytest.raises(wiz.Fatal, match="may only name operator sidecars"):
            wiz.load_project_spec(root)


def test_boundary_overlay_rides_as_the_LAST_compose_layer(wiz, tmp_path):
    """Order is the point. After the operator's override, or their `network_mode`
    would win and their sidecar would sit outside the boundary while the
    declaration said otherwise."""
    argv = wiz.driver_compose_argv(
        {"driver": "docker", "context": ""},
        "p",
        tmp_path / "gen.yaml",
        "up",
        override=tmp_path / "side.yaml",
        boundary=tmp_path / "b.yaml",
    )
    fs = [argv[i + 1] for i, a in enumerate(argv) if a == "-f"]
    assert fs[-1].endswith("b.yaml"), "the boundary must be layered last"
    assert fs.index(str(tmp_path / "side.yaml")) < fs.index(str(tmp_path / "b.yaml"))


def test_no_overlay_when_there_are_no_sidecars(wiz, tmp_path):
    """No third `-f` for an environment without sidecars — the argv is unchanged."""
    assert wiz.build_sidecar_boundary_overlay(None, DECL_A) is None
    o = _override(tmp_path, "services:\n  only:\n    image: x\n")
    assert wiz.build_sidecar_boundary_overlay(o, {**DECL_A, "sidecars_outside": ["only"]}) is None


def test_sidecar_holding_net_admin_is_refused(wiz, tmp_path):
    """FR-023d — the check that matters most in this block.

    A sidecar inside the shared namespace holding NET_ADMIN can FLUSH THE EGRESS
    RULES. The agent needs no capability of its own: it only needs to ask. That is
    the same shape as the laundering bypass, one layer down — and it would defeat
    the boundary completely while the declaration still read as enforced.
    """
    o = _override(tmp_path, "services:\n  helper:\n    image: x\n    cap_add: [NET_ADMIN]\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.check_sidecar_egress_posture(o, DECL_A)
    msg = str(e.value)
    assert "NET_ADMIN" in msg and "sidecars_outside" in msg, "must name the intended escape hatch"


def test_privileged_sidecar_is_refused(wiz, tmp_path):
    o = _override(tmp_path, "services:\n  helper:\n    image: x\n    privileged: true\n")
    with pytest.raises(wiz.Fatal, match="privileged"):
        wiz.check_sidecar_egress_posture(o, DECL_A)


def test_host_network_sidecar_is_refused(wiz, tmp_path):
    """`network_mode: host` leaves the namespace entirely — the boundary would
    simply not apply while the declaration read as enforced."""
    o = _override(tmp_path, "services:\n  helper:\n    image: x\n    network_mode: host\n")
    with pytest.raises(wiz.Fatal, match="network_mode: host"):
        wiz.check_sidecar_egress_posture(o, DECL_A)


def test_cap_prefix_and_case_do_not_evade_the_check(wiz, tmp_path):
    """`CAP_NET_ADMIN`, `cap_net_admin` and `NET_ADMIN` are the same capability."""
    for spelling in ("CAP_NET_ADMIN", "cap_net_admin", "Net_Admin"):
        o = _override(tmp_path, f"services:\n  h:\n    image: x\n    cap_add: ['{spelling}']\n")
        with pytest.raises(wiz.Fatal, match="NET_ADMIN"):
            wiz.check_sidecar_egress_posture(o, DECL_A)


def test_posture_check_ignores_a_sidecar_declared_outside(wiz, tmp_path):
    """One deliberately outside is already declared unconstrained AND named as
    such, and it is not in the namespace to dismantle. Refusing its capabilities
    too would be theatre."""
    o = _override(tmp_path, "services:\n  feed:\n    image: x\n    privileged: true\n")
    wiz.check_sidecar_egress_posture(o, {**DECL_A, "sidecars_outside": ["feed"]})


def test_posture_check_is_inert_without_a_declaration(wiz, tmp_path):
    """No declaration, no boundary, no business refusing an operator's sidecar."""
    o = _override(tmp_path, "services:\n  h:\n    image: x\n    privileged: true\n")
    wiz.check_sidecar_egress_posture(o, None)


# --- adversarial review: fail-open paths -------------------------------------


def test_a_broken_spec_refuses_rather_than_deploying_unrestricted(wiz, tmp_path, monkeypatch):
    """D4. `resolve_egress_declaration` swallowed the validator's Fatal and returned
    None, which means UNDECLARED — i.e. unrestricted — for an environment whose own
    `egress:` block is what failed to validate.

    That fails OPEN, and silence is the defect this feature exists to remove: the
    operator wrote a declaration and would have got an environment that ignores it
    while reporting nothing.
    """
    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n"
        "  - name: acme\n"
        "    host: local\n"
        "    container:\n"
        "      agent: claude\n"
        "    egress:\n"
        "      allow: [{provider: anthropic}]\n"
        "      enforcement: nonsense-not-a-mode\n"
    )
    with pytest.raises(wiz.Fatal, match="cannot tell what it permits"):
        wiz.resolve_egress_declaration("acme", cwd=proj)


def test_a_broken_spec_elsewhere_still_deploys_an_undeclared_environment(wiz, tmp_path):
    """The complement, and the reason the swallow existed. An unrelated environment
    being invalid must NOT block an imperative `up` of one that declares nothing —
    otherwise the refusal above becomes a denial of service on the whole project."""
    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n"
        "  - name: other\n"
        "    host: local\n"
        "    container:\n"
        "      agent: claude\n"
        "    egress:\n"
        "      enforcement: nonsense-not-a-mode\n"
        "  - name: acme\n"
        "    host: local\n"
        "    container:\n"
        "      agent: claude\n"
    )
    assert wiz.resolve_egress_declaration("acme", cwd=proj) is None


def test_lenient_egress_detection_reads_flow_style_and_quoted_keys(wiz, tmp_path):
    """The detector must not be a pattern scan. Flow style and quoted keys are
    exactly what a regex misses, and the miss would be silent and PERMISSIVE."""
    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        'environments: [{name: acme, host: local, "egress": {allow: []}}]\n'
    )
    assert wiz._environment_declares_egress_leniently(proj, "acme") is True
    assert wiz._environment_declares_egress_leniently(proj, "absent") is False


# --- adversarial review: an HTTPS remote on a non-standard port ---------------


def test_push_check_fires_for_an_https_remote_on_a_non_standard_port(wiz):
    """D6. The nat REDIRECT matches dport 443/80 only, so `https://h:8443/…` never
    reaches squid and is denied at the packet level unless declared with a port.
    `https_remote_host` discards the port, so the portless check reported it as
    permitted while the push was dropped."""
    with pytest.raises(wiz.Fatal, match="on port 8443"):
        wiz.check_egress_permits_push(
            {"allow": [{"host": "git.example.com"}]},
            "https://git.example.com:8443/you/acme",
            "strict",
            transparent=True,
        )


def test_a_declared_non_standard_https_port_is_accepted(wiz):
    wiz.check_egress_permits_push(
        {"allow": [{"host": "git.example.com", "port": 8443}]},
        "https://git.example.com:8443/you/acme",
        "strict",
        transparent=True,
    )


def test_an_ordinary_https_remote_is_still_the_proxys_surface(wiz):
    """443 must NOT start demanding a {host, port} entry — that would break every
    existing declaration, and the proxy genuinely governs that path."""
    wiz.check_egress_permits_push(
        {"allow": [{"host": "github.com"}]},
        "https://github.com:443/you/acme",
        "strict",
        transparent=True,
    )
