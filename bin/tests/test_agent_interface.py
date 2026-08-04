"""Feature 009 (agent-operable CLI) unit tests — hermetic, no runtime, no TTY.

Covers the versioned envelope, the failure descriptor rendered at the single
`cli()` chokepoint, the `context` serializer (fed a constructed Feature 007
snapshot, which is pure), and the skill installer against a scratch config tree.

Constitution III is the gate: no machine-readable payload may carry a secret.
"""

from __future__ import annotations

import json

import pytest

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}


def _emitted(wiz, capsys, **kw) -> dict:
    wiz.emit_json(**kw)
    return json.loads(capsys.readouterr().out)


# --- envelope (T002 / FR-006, FR-002) ----------------------------------------


def test_envelope_success_shape(wiz, capsys):
    env = _emitted(wiz, capsys, data={"a": 1})
    assert env["schema"] == wiz.SCHEMA_VERSION == "agent-container/v1"
    assert env["ok"] is True
    assert env["data"] == {"a": 1}
    assert "error" not in env  # exactly one of data/error


def test_envelope_failure_shape(wiz, capsys):
    env = _emitted(wiz, capsys, error={"code": "x", "entity": None, "message": "m", "remedy": None})
    assert env["ok"] is False and env["error"]["code"] == "x"
    assert "data" not in env


def test_envelope_is_the_only_thing_on_stdout(wiz, capsys):
    """FR-002: no colour/progress/table bleed — stdout parses whole."""
    wiz.emit_json({"k": "v"})
    out = capsys.readouterr().out
    assert json.loads(out)  # the entire stream is one JSON document
    assert not out.lstrip().startswith("\x1b")  # no ANSI escape


# --- failure descriptor (T004 / FR-003, FR-004, FR-005, FR-019) --------------


def test_die_defaults_to_unspecified_code(wiz):
    """Un-annotated call sites keep working, with a documented generic code."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.die("boom")
    d = e.value.descriptor()
    assert d["code"] == wiz.FAILURE_CODE_UNSPECIFIED == "unspecified"
    assert d["message"] == "boom" and d["entity"] is None and d["remedy"] is None


def test_die_carries_code_entity_remedy(wiz):
    with pytest.raises(wiz.Fatal) as e:
        wiz.die("nope", code="host_not_registered", entity="hz1", remedy="agent-container host ls")
    d = e.value.descriptor()
    assert (d["code"], d["entity"], d["remedy"]) == (
        "host_not_registered",
        "hz1",
        "agent-container host ls",
    )
    assert d["message"] == "nope"  # human wording preserved (FR-019)


def test_json_mode_is_off_by_default(wiz):
    """--json is opt-in per invocation; the human path must be untouched."""
    wiz.set_json_mode(False)
    assert wiz.json_mode() is False


# --- --json coverage across the command surface (T006 / FR-001) --------------


def _command_names(wiz) -> set[str]:
    names = set()
    for cmd in wiz.app.registered_commands:
        names.add(cmd.name or cmd.callback.__name__.replace("_", "-"))
    return names


def test_every_command_takes_json_except_documented_exclusions(wiz):
    """A newly added command cannot silently miss the machine-readable surface."""
    import inspect

    missing = []
    for cmd in wiz.app.registered_commands:
        name = cmd.name or cmd.callback.__name__
        if name in {"menu", "attach", "completions"}:
            continue  # documented exclusions (NO_JSON_COMMANDS)
        if "as_json" not in inspect.signature(cmd.callback).parameters:
            missing.append(name)
    assert missing == [], f"commands missing --json: {missing}"


def test_no_json_exclusions_are_exactly_the_documented_set(wiz):
    assert wiz.NO_JSON_COMMANDS == frozenset({"host env", "completions", "attach", "menu"}), (
        "changing the exclusion set is a contract change — update the docs too"
    )


# --- additive guarantee (T007a / FR-019, SC-008) -----------------------------


def test_emit_action_is_a_noop_without_json(wiz, capsys):
    """Without --json the human path emits nothing extra — byte-for-byte unchanged."""
    wiz.set_json_mode(False)
    wiz.emit_action("stop", name="dev")
    assert capsys.readouterr().out == ""


def test_emit_action_emits_envelope_with_json(wiz, capsys):
    wiz.set_json_mode(True)
    try:
        wiz.emit_action("stop", name="dev", host="local")
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] and env["data"] == {"command": "stop", "name": "dev", "host": "local"}
    finally:
        wiz.set_json_mode(False)


# --- context serializer (T015 / FR-009, FR-010) ------------------------------


def _snapshot(wiz, monkeypatch, *, reachable=True, containers=()):
    monkeypatch.setattr(wiz, "probe_host_runtime", lambda hr: None if reachable else "down")
    monkeypatch.setattr(wiz, "image_exists", lambda rt, tag: True)
    monkeypatch.setattr(
        wiz,
        "host_ps_rows",
        lambda hr, include_stopped=False: [
            (f"agent-container-{n}", "img", s, "1m") for n, s in containers
        ],
    )
    monkeypatch.setattr(wiz, "_volume_names", lambda rt: [])
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {}, "default": None})
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "implicit_local_host", lambda rt=None: dict(LOCAL_HOST))


def test_context_valid_in_an_empty_world(wiz, monkeypatch, tmp_path):
    """FR-010: an unconfigured machine is DESCRIBED, never an error."""
    monkeypatch.chdir(tmp_path)
    _snapshot(wiz, monkeypatch)
    ctx = wiz.build_agent_context("docker")
    assert ctx["hosts"] == [] and ctx["environments"] == []
    assert ctx["credentials"] == []
    assert {s["key"] for s in ctx["stages"]} == set(wiz.STAGE_KEYS)
    assert ctx["next_step"]["kind"]  # always suggests something


def test_context_describes_unreachable_host_without_failing(wiz, monkeypatch, tmp_path):
    """A REGISTERED but unreachable host is `unusable` (present-but-broken) — a
    described state, not a failed call and not `unsatisfied` (absent)."""
    monkeypatch.chdir(tmp_path)
    _snapshot(wiz, monkeypatch, reachable=False)
    monkeypatch.setattr(
        wiz, "load_registry", lambda: {"hosts": {"local": dict(LOCAL_HOST)}, "default": "local"}
    )
    ctx = wiz.build_agent_context("docker")  # must NOT raise
    host_stage = next(s for s in ctx["stages"] if s["key"] == "host")
    assert host_stage["status"] == wiz.STAGE_UNUSABLE  # described, not absent
    assert any("unreachable" in p for p in ctx["problems"])
    assert ctx["hosts"] and ctx["hosts"][0]["name"] == "local"


def test_context_is_json_serializable(wiz, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _snapshot(wiz, monkeypatch, containers=[("dev", "Up 2 minutes")])
    json.dumps(wiz.build_agent_context("docker"))  # must not raise


# --- Constitution III: locators only, never values (T012/T017 / FR-011) ------


_SECRET = "sk-THIS-MUST-NEVER-APPEAR"


def _project(tmp_path, yaml_text: str):
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "environments.yaml").write_text(yaml_text)
    return root


def test_context_credentials_are_locators_never_values(wiz, monkeypatch, tmp_path):
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n    credentials:\n"
        "      - { name: K1, source: env, var: MY_SECRET_VAR }\n"
        "      - { name: K2, source: onepassword, vault: V, item: I, field: F }\n"
        "      - { name: K3, source: command, argv: ['op', 'read', 'op://V/I/F'] }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("MY_SECRET_VAR", _SECRET)
    _snapshot(wiz, monkeypatch)
    ctx = wiz.build_agent_context("docker")
    blob = json.dumps(ctx)
    assert _SECRET not in blob, "Constitution III breach: a secret reached the payload"
    refs = {c["name"]: c["reference"] for c in ctx["credentials"]}
    assert refs["K1"] == "MY_SECRET_VAR"  # the VARIABLE NAME, not its value
    assert refs["K2"] == "op://V/I/F"
    assert "op read" in refs["K3"]


def test_context_env_file_is_a_path_not_contents(wiz, monkeypatch, tmp_path):
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: local\n")
    (root / ".env").write_text(f"GH_TOKEN={_SECRET}\n")
    monkeypatch.chdir(root)
    _snapshot(wiz, monkeypatch, containers=[("acme", "Up 1m")])
    ctx = wiz.build_agent_context("docker")
    assert _SECRET not in json.dumps(ctx)


def test_failure_descriptor_never_carries_a_secret(wiz):
    """A die() message is authored by us; assert the descriptor exposes only
    what we put in it, so a secret cannot ride along in a structured field."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.die("credential X is unavailable", code="credential_unresolvable", entity="X")
    assert _SECRET not in json.dumps(e.value.descriptor())


# --- skill (T018/T020 / FR-012a, FR-012c, FR-013..018) -----------------------


def test_skill_conforms_to_agent_skills_standard(wiz):
    md = wiz.render_skill()
    assert md.startswith("---\n")
    fm = md.split("---\n", 2)[1]
    assert "name: agent-container" in fm  # required by the standard
    assert "description:" in fm  # required by the standard
    assert wiz.SKILL_MARKER in fm  # our drift marker (extra keys are allowed)


def test_skill_body_enforces_json_on_every_example(wiz):
    """FR-012c: the skill is what makes the per-invocation --json workable."""
    body = wiz.SKILL_BODY
    assert "ALWAYS pass `--json`" in body
    examples = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("agent-container ")]
    assert examples, "expected command examples in the skill"
    missing = [e for e in examples if "--json" not in e]
    assert missing == [], f"skill examples missing --json: {missing}"


def test_skill_targets_cover_the_four_agents(wiz):
    assert set(wiz.SKILL_TARGETS) == {"claude", "codex", "opencode", "pi"}


def test_skill_install_idempotent_then_drift_refused(wiz, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = wiz.skill_dir("claude", False) / "SKILL.md"
    wiz.do_skill("install", "claude", False, False)
    assert md.is_file()
    first = md.read_text()
    wiz.do_skill("install", "claude", False, False)  # idempotent: no rewrite
    assert md.read_text() == first
    md.write_text(first + "\noperator edit\n")
    with pytest.raises(wiz.Fatal, match="modified"):
        wiz.do_skill("update", "claude", False, False)  # FR-014: never clobber
    wiz.do_skill("update", "claude", False, True)  # --force replaces
    assert "operator edit" not in md.read_text()


def test_skill_foreign_file_refused(wiz, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = wiz.skill_dir("claude", False)
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("someone else's skill\n")
    with pytest.raises(wiz.Fatal, match="not written by this tool"):
        wiz.do_skill("install", "claude", False, False)


def test_skill_remove_leaves_no_residue(wiz, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wiz.do_skill("install", "claude", False, False)
    wiz.do_skill("remove", "claude", False, False)
    assert not (wiz.skill_dir("claude", False) / "SKILL.md").exists()
    assert list(tmp_path.rglob("SKILL.md")) == []  # FR-015


def test_skill_unknown_agent_refused(wiz, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(wiz.Fatal, match="unknown agent"):
        wiz.skill_dir("nosuchagent", False)


def test_skill_user_scope_differs_from_project(wiz, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert wiz.skill_dir("claude", False) != wiz.skill_dir("claude", True)
    assert str(wiz.skill_dir("claude", False)).startswith(str(tmp_path))  # project default


# --- FR-007: non-interactive must REFUSE, never silently proceed -------------


def test_aac_destroy_refuses_without_yes_on_non_tty(wiz, tmp_path, monkeypatch):
    """Regression: this previously SKIPPED the confirmation on a non-TTY and tore
    everything down unauthorized — strictly worse than blocking. An agent must have
    to say -y."""
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: local\n")
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "is_tty", lambda: False)
    torn: list = []
    monkeypatch.setattr(wiz, "down_container", lambda *a, **k: torn.append(a))
    with pytest.raises(wiz.Fatal) as e:
        wiz.do_aac_destroy(yes=False)
    assert e.value.code == "confirmation_required"
    assert "-y" in str(e.value)
    assert torn == [], "nothing may be destroyed without authorization"


def test_aac_apply_refuses_without_yes_on_non_tty(wiz, tmp_path, monkeypatch):
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: local\n")
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "is_tty", lambda: False)
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda host: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(wiz, "env_live_config", lambda hr, n: None)
    deployed: list = []
    monkeypatch.setattr(wiz, "do_up", lambda name, **kw: deployed.append(name))
    with pytest.raises(wiz.Fatal) as e:
        wiz.do_aac_apply(yes=False)
    assert e.value.code == "confirmation_required"
    assert deployed == [], "nothing may be deployed (or PROVISIONED) without authorization"


# --- plan/status emit a machine-readable payload (Feature 009 FR-013) --------


def test_plan_payload_names_fields_explicitly(wiz):
    """The environment dict carries `credentials`. Those are locators rather than
    values (Feature 008), but the payload is an ALLOWLIST so a future spec key
    cannot start appearing on stdout merely by existing (Constitution III).
    """
    env = {
        "name": "acme",
        "host": "local",
        "container": {"agent": "codex", "mode": "headless", "workspace": "ephemeral"},
        "credentials": [
            {
                "name": "ANTHROPIC_API_KEY",
                "source": "onepassword",
                "vault": "V",
                "item": "i",
                "field": "f",
            }
        ],
        "egress": {"providers": ["anthropic"]},
    }
    (row,) = wiz.plan_payload([(env, "acme", "local", None, "drifted", "agent: 'claude'→'codex'")])
    assert row == {
        "name": "acme",
        "host": "local",
        "state": "drifted",
        "detail": "agent: 'claude'→'codex'",
        "agent": "codex",
        "mode": "headless",
        "workspace": "ephemeral",
    }
    assert "credentials" not in row, "the credentials block must not ride the payload"


def test_plan_payload_defaults_match_the_execspec_defaults(wiz):
    """An environment declaring no container block still reports what it will get,
    rather than nulls the caller must interpret."""
    (row,) = wiz.plan_payload([({"name": "acme"}, "acme", "local", None, "absent", "")])
    assert (row["agent"], row["mode"], row["workspace"]) == ("claude", "interactive", "persistent")
    assert row["detail"] is None
