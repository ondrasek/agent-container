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
    # Top-level named volumes: exactly the ten per-container volumes. The count
    # MOVED with Feature 016's runs volume, and it is pinned as a number on
    # purpose: a set comparison alone would follow per_container_volumes wherever
    # it went, so nothing would notice a volume silently appearing or vanishing.
    assert set(m["volumes"].keys()) == set(wiz.per_container_volumes("acme"))
    assert len(m["volumes"]) == 10
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


def test_the_model_can_no_longer_carry_a_private_host_key(wiz):
    """Feature 018 (FR-001/FR-002): the `ssh_host_key` config is GONE, and the model
    cannot be asked to deliver one.

    The assertion inverts rather than disappearing. A removal that leaves no test
    behind is a removal nobody notices being undone — and this particular channel put
    a plaintext private key on the operator's disk at mode 0644.
    """
    m = wiz.build_compose_model("acme", "/repo")
    assert "secrets" not in m  # never used compose secrets, and still does not
    assert "ssh_host_key" not in m.get("configs", {})
    assert not any(
        c.get("source") == "ssh_host_key" for c in m["services"]["agent"].get("configs", [])
    )
    with pytest.raises(TypeError):  # the parameter itself is gone
        wiz.build_compose_model("acme", "/repo", host_key_file="/anything")


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
    # No credential VALUE may appear in the serialized model — only `file:` refs.
    secret = "TOP-SECRET-CREDENTIAL-BYTES"
    ak = tmp_path / "acme.authorized_keys"
    ak.write_text(secret)  # stand-in for any staged material
    m = wiz.build_compose_model("acme", "/repo", authorized_keys_file=ak)
    blob = json.dumps(m)
    assert secret not in blob  # only the path is referenced, not the contents
    assert str(ak) in blob


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
    assert len(m["volumes"]) == 10  # Feature 016 appended the runs volume
    # Deterministic identity (Constitution IV): both names pin `name`.
    for v in ("agent-container-acme-opencode", "agent-container-acme-opencode-data"):
        assert m["volumes"][v] == {"name": v}


def test_non_persistent_workspace_still_declares_both_opencode_volumes(wiz):
    """The workspace volume stays conditional (Feature 004); opencode's two are
    unconditional, so bind/ephemeral declares nine (016 added runs, also
    unconditional — a disposable run is the one whose record matters most)."""
    for kwargs in (
        {"workspace_mount": "/host/w:/workspace", "declare_workspace_volume": False},
        {"workspace_mount": None, "declare_workspace_volume": False},
    ):
        m = wiz.build_compose_model("acme", "/repo", **kwargs)
        assert len(m["volumes"]) == 9
        assert wiz.volume_name("acme") not in m["volumes"]
        assert "agent-container-acme-opencode" in m["volumes"]
        assert "agent-container-acme-opencode-data" in m["volumes"]
        assert wiz.runs_volume_name("acme") in m["volumes"]


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
    # The LITERAL T001 baseline, not `port_for_name("acme")`. Deriving the expected
    # value from the function under discussion made both sides of every assertion
    # move together, so a drifted port read as "unchanged owner, unchanged number"
    # — and the tautology that used to sit at the end of this test
    # (`port_for_name("acme") == port_for_name("acme")`) held for any return value
    # at all. The number is also pinned in test_pure_logic.py::
    # test_identity_is_unchanged_by_feature_011; it is repeated here because THIS
    # test is the one that claims the number survives the owner moving.
    port = "2206:2222"

    assert plain["services"]["agent"]["ports"] == [port], "unchanged without a declaration"
    assert "ports" not in withp["services"]["agent"], "the agent cannot publish in a shared netns"
    assert withp["services"]["egress"]["ports"] == [port], "same NUMBER, different owner"


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


def test_the_builtin_default_disclosure_also_offers_config_that_validates(wiz, capsys):
    """The same defect one function over — and the sibling test above is exactly
    what made it easy to miss.

    `check_builtin_default_declared` was fixed to stop naming `egress.providers`;
    `disclose_builtin_default` — the message an UNDECLARED environment gets, so the
    more common of the two — went on naming it. It is the one key `validate_egress`
    refuses OUTRIGHT (FR-018b), so an operator following the advice answered a
    disclosure with a hard failure, with the tool having authored both.
    """
    wiz.disclose_builtin_default(None, "opencode")
    msg = capsys.readouterr().err
    assert "big-pickle" in msg, "the disclosure must fire for an agent with a default"
    assert "egress.providers" not in msg, "the remediation names the one refused key"
    entries = _remediation_entries(msg)
    for entry in entries:
        wiz.validate_destination(entry, "remediation")
    wiz.validate_egress({"allow": entries}, "remediation")


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


# --- T149: adopting a declaration changes how sidecars are ADDRESSED ---------


def test_declaring_a_sidecar_service_name_is_refused_with_the_real_fix(wiz, tmp_path):
    """T149. `{host: redis}` was meaningful under the cooperative proxy — the agent
    was on the project network and reached the service by name. Inside the boundary
    every service shares ONE namespace, so the sidecar is on loopback and the name
    resolves nowhere: with a port the rule renders `-d redis` and the boundary dies
    installing it, without one squid gets a domain it can never resolve.

    Refused rather than warned because the entry cannot be made to work at all, and
    the message must carry the fix — an operator who reaches for the allowlist has
    already guessed wrong, so repeating "declare it" would send them in a circle.
    """
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n")
    for entry in ({"host": "redis"}, {"host": "redis", "port": 6379}):
        with pytest.raises(wiz.Fatal) as e:
            wiz.refuse_sidecar_name_in_allow({"allow": [entry]}, o, enforced=True)
        msg = str(e.value)
        assert "redis" in msg, "must name the entry it is refusing"
        assert "127.0.0.1" in msg, "and where the service actually is now"
        assert "one network namespace" in msg.lower(), "and why it changed"


def test_a_real_destination_that_merely_resembles_nothing_is_left_alone(wiz, tmp_path):
    """The refusal matches sidecar service names EXACTLY. A declaration is mostly
    real hosts, and a check that fired on any of them would make the boundary
    undeployable for the environments most likely to want it."""
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n")
    wiz.refuse_sidecar_name_in_allow(
        {"allow": [{"provider": "anthropic"}, {"host": "redis.corp.internal"}]}, o, enforced=True
    )
    # Undeclared, and no override: nothing to say in either case.
    wiz.refuse_sidecar_name_in_allow(None, o, enforced=True)
    wiz.refuse_sidecar_name_in_allow({"allow": [{"host": "redis"}]}, None, enforced=True)


def test_the_refusal_is_silent_when_no_boundary_is_actually_DEPLOYED(wiz, tmp_path):
    """The refusal's premise is a shared namespace, which exists only when the
    declaration is ENFORCED — and a declaration can exist without one.

    `advisory` on a host with no reachable egress image sources, or under an
    override redefining the `egress` service, deploys UNENFORCED: no boundary, the
    sidecars stay on the project network, and service-name DNS between them keeps
    working. Refusing there rejects a configuration that works, and does it with a
    message stating as fact a namespace share that is not happening.

    Neither `sidecars_inside_boundary` nor the overlay can catch this — both answer
    the conditional question — so the gate lives on this parameter, and it has no
    default so a future caller cannot omit it back into the defect.
    """
    o = _override(tmp_path, "services:\n  redis:\n    image: redis:7\n")
    egress = {"allow": [{"provider": "anthropic"}, {"host": "redis", "port": 6379}]}
    wiz.refuse_sidecar_name_in_allow(egress, o, enforced=False)
    # And the same input DOES refuse once a boundary is deployed, so the test above
    # is not passing because the entry stopped being detected.
    with pytest.raises(wiz.Fatal, match="redis"):
        wiz.refuse_sidecar_name_in_allow(egress, o, enforced=True)


def test_a_sidecar_declared_outside_the_boundary_is_not_matched(wiz, tmp_path):
    """One placed outside is on the project network and is disclosed as
    unconstrained. Whether its name resolves is the cost of that choice, not a
    mistake in the allowlist — so the refusal stays scoped to services INSIDE."""
    o = _override(tmp_path, "services:\n  feed:\n    image: f\n")
    wiz.refuse_sidecar_name_in_allow(
        {"allow": [{"host": "feed", "port": 8080}], "sidecars_outside": ["feed"]}, o, enforced=True
    )


def test_the_loopback_diagnostic_says_what_changed_and_what_to_do(wiz, capsys):
    """The old failure was a correct placement with a wrong story: the operator was
    told the sidecars were "inside the boundary" and then met an unresolvable
    hostname, with nothing connecting the two. Both halves are asserted — what
    broke, and the fix — plus that it does NOT point at the allowlist, which is the
    fix that cannot work.
    """
    wiz.warn_sidecar_hostnames_moved_to_loopback(["db", "redis"])
    err = capsys.readouterr().err
    assert "db" in err and "redis" in err
    assert "NO LONGER RESOLVES" in err, "say what changed, not just what to do"
    assert "127.0.0.1:5432" in err, "a concrete replacement, not 'use loopback'"
    assert "does NOT restore it" in err, "the obvious guess must be closed off"
    # Silent when there is nothing inside — an environment with no sidecars must
    # not be told about a change that did not happen to it.
    wiz.warn_sidecar_hostnames_moved_to_loopback([])
    assert capsys.readouterr().err == ""


def test_inside_and_outside_are_computed_in_one_place(wiz, tmp_path):
    """The overlay does the placing and three diagnostics describe it. A second
    spelling of "which sidecars are inside" would eventually disagree with the one
    that actually places them — and the disagreement would be a service the
    operator believes is constrained.

    WHAT THIS EQUALITY DOES NOT COVER, stated so it is not read as more than it is:
    both sides answer the CONDITIONAL question — which sidecars would be inside a
    boundary that is deployed. Whether one is deployed at all is `_enforced`, which
    neither function receives, so agreeing here proves nothing about whether a
    caller remembered to ask. That gate is a required keyword on
    `refuse_sidecar_name_in_allow` for exactly that reason.
    """
    o = _override(tmp_path, "services:\n  redis:\n    image: r\n  feed:\n    image: f\n")
    egress = {**DECL_A, "sidecars_outside": ["feed"]}
    assert wiz.sidecars_inside_boundary(o, egress) == ["redis"]
    overlay = wiz.build_sidecar_boundary_overlay(o, egress)
    assert list(overlay["services"]) == wiz.sidecars_inside_boundary(o, egress)
    # Undeclared: nothing is placed anywhere, so nothing is inside.
    assert wiz.sidecars_inside_boundary(o, None) == []


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


# --- T155 / research R24: the pinned-address warning --------------------------


def test_every_named_ported_destination_is_warned_about(wiz, monkeypatch, capsys):
    """The trigger is a NAME, not an address count.

    The first version warned only on more than one simultaneous address, and that is
    silent for the canonical case: `github.com` returns ONE address per query while
    R24 proved .3, .4 and .5 all exist — it rotates across queries, not within an
    answer. A count-based check passed while the very host it was written for went
    unwarned.
    """
    monkeypatch.setattr(wiz, "resolve_host_addresses", lambda h, p, timeout=3.0: ["140.82.121.3"])
    wiz.warn_pinned_port_destinations([("github.com", "github.com", 22, "spec")], transparent=True)
    err = capsys.readouterr().err
    assert "WHEN THE BOUNDARY STARTS" in err
    assert "still reads as permitting it" in err, "name the failure, not just the mechanism"
    assert "140.82.121.3" in err, "the resolved address is useful information"


def test_an_ip_literal_is_never_warned_about(wiz, monkeypatch, capsys):
    """Nothing to re-resolve, so nothing can go stale. Warning here would be noise."""
    monkeypatch.setattr(wiz, "resolve_host_addresses", lambda h, p, timeout=3.0: ["10.0.0.1"])
    wiz.warn_pinned_port_destinations([("db", "10.0.0.1", 5432, "spec")], transparent=True)
    assert capsys.readouterr().err == ""
    wiz.warn_pinned_port_destinations([("v6", "::1", 5432, "spec")], transparent=True)
    assert capsys.readouterr().err == ""


def test_the_warning_still_fires_when_the_lookup_fails(wiz, monkeypatch, capsys):
    """The PINNING is what is being reported, and it is true whether or not this
    machine can resolve the name. Staying silent on a failed probe would make the
    warning depend on the deploying machine's resolver rather than on the mechanism."""
    monkeypatch.setattr(wiz, "resolve_host_addresses", lambda h, p, timeout=3.0: None)
    wiz.warn_pinned_port_destinations([("gh", "github.com", 22, "spec")], transparent=True)
    err = capsys.readouterr().err
    assert "WHEN THE BOUNDARY STARTS" in err
    assert "now:" not in err, "must not claim addresses it never measured"


def test_portless_entries_are_never_warned_about(wiz, monkeypatch, capsys):
    """The proxy re-resolves per request, so nothing is pinned on that surface. If
    this ever warns, the port/mechanism split (FR-018a) has been misread."""
    monkeypatch.setattr(
        wiz, "resolve_host_addresses", lambda h, p, timeout=3.0: ["1.1.1.1", "1.0.0.1"]
    )
    wiz.warn_pinned_port_destinations(
        [("anthropic", "api.anthropic.com", None, "tool")], transparent=True
    )
    assert capsys.readouterr().err == ""


def test_nothing_is_warned_about_without_transparent_enforcement(wiz, monkeypatch, capsys):
    """Without netfilter there is no pinned rule to warn about."""
    monkeypatch.setattr(
        wiz, "resolve_host_addresses", lambda h, p, timeout=3.0: ["1.2.3.4", "5.6.7.8"]
    )
    wiz.warn_pinned_port_destinations([("gh", "github.com", 22, "spec")], transparent=False)
    assert capsys.readouterr().err == ""


def test_the_resolver_probe_is_bounded_and_never_raises(wiz):
    """It runs on the deploy path, and `getaddrinfo` honours no timeout argument.

    Exercised against a name that cannot resolve: the contract is None, promptly,
    rather than an exception escaping into a deploy.
    """
    import time

    started = time.monotonic()
    assert wiz.resolve_host_addresses("no-such-host.invalid", 22, timeout=2.0) is None
    assert time.monotonic() - started < 10, "the probe must not stall a deploy"
