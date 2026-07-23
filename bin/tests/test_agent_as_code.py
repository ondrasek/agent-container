"""Feature 006 (agent-as-code) unit tests — hermetic, no live runtime.

Cover discovery (upward walk), YAML parse + validation against the pinned schema
(`yaml.safe_load` — a `!!python/object` tag must NOT construct an object), the
reconcile plan (absent/matching/drifted) + ownership-by-identity, the read-only
`.agent-container` spec delivery (compose configs, FR-020) + the refuse-if-writable
verify, and the apply/status orchestration (idempotent; spec-wins precedence;
inert when no project). Requirement anchors named in the bodies.
"""

from __future__ import annotations

import pytest

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}


def _project(tmp_path, yaml_text: str):
    """Create tmp project with .agent-container/project.yaml; return its root."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "project.yaml").write_text(yaml_text)
    return root


MINIMAL = """
environments:
  - name: acme
    host: local
    container:
      mode: interactive
      agent: claude
      workspace: persistent
"""


# --- discovery (FR-001/004) --------------------------------------------------


def test_find_project_root_walks_upward(wiz, tmp_path):
    root = _project(tmp_path, MINIMAL)
    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert wiz.find_project_root(nested) == root.resolve()
    assert wiz.find_project_root(root) == root.resolve()


def test_find_project_root_none_when_absent(wiz, tmp_path):
    (tmp_path / "plain").mkdir()
    assert wiz.find_project_root(tmp_path / "plain") is None


# --- parse + validate (FR-003) -----------------------------------------------


def test_load_spec_valid(wiz, tmp_path):
    root = _project(tmp_path, MINIMAL)
    envs = wiz.load_project_spec(root)
    assert len(envs) == 1
    assert envs[0]["name"] == "acme" and envs[0]["host"] == "local"


def test_load_spec_safe_load_refuses_object_construction(wiz, tmp_path, monkeypatch):
    # yaml.safe_load must NOT construct arbitrary objects (no code execution).
    import os

    called = []
    monkeypatch.setattr(os, "system", lambda cmd: called.append(cmd))
    root = _project(
        tmp_path, "environments:\n  - !!python/object/apply:os.system ['touch pwned']\n"
    )
    with pytest.raises(wiz.Fatal, match="invalid YAML"):
        wiz.load_project_spec(root)
    assert called == []  # the tag was refused, nothing executed


def test_load_spec_missing_environments_dies(wiz, tmp_path):
    root = _project(tmp_path, "{}\n")  # a mapping with no keys → missing 'environments'
    with pytest.raises(wiz.Fatal, match="missing required key 'environments'"):
        wiz.load_project_spec(root)


def test_load_spec_missing_name_dies(wiz, tmp_path):
    root = _project(tmp_path, "environments:\n  - host: local\n")
    with pytest.raises(wiz.Fatal, match="missing required string 'name'"):
        wiz.load_project_spec(root)


def test_load_spec_missing_host_dies(wiz, tmp_path):
    root = _project(tmp_path, "environments:\n  - name: acme\n")
    with pytest.raises(wiz.Fatal, match="missing required 'host'"):
        wiz.load_project_spec(root)


def test_load_spec_bad_enum_dies_naming_field(wiz, tmp_path):
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n    container:\n      mode: batch\n",
    )
    with pytest.raises(wiz.Fatal, match="mode='batch'"):
        wiz.load_project_spec(root)


def test_load_spec_unknown_container_key_dies(wiz, tmp_path):
    root = _project(
        tmp_path, "environments:\n  - name: acme\n    host: local\n    container:\n      bogus: 1\n"
    )
    with pytest.raises(wiz.Fatal, match="unknown container key 'bogus'"):
        wiz.load_project_spec(root)


def test_load_spec_duplicate_name_dies(wiz, tmp_path):
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n  - name: acme\n    host: local\n",
    )
    with pytest.raises(wiz.Fatal, match="duplicate environment name"):
        wiz.load_project_spec(root)


def test_credential_validation(wiz):
    wiz.validate_credential({"name": "K", "source": "env", "var": "K"}, "w")  # ok
    with pytest.raises(wiz.Fatal, match="source='bad'"):
        wiz.validate_credential({"name": "K", "source": "bad"}, "w")
    with pytest.raises(wiz.Fatal, match="requires 'decrypt'"):
        wiz.validate_credential({"name": "K", "source": "encrypted", "path": "x"}, "w")


def test_provisioned_host_not_yet_supported(wiz, tmp_path):
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: { provision: hetzner }\n")
    envs = wiz.load_project_spec(root)  # a provision table is a valid schema shape
    with pytest.raises(wiz.Fatal, match="not yet supported"):
        wiz.env_host_name(envs[0])


# --- reconcile + ownership (FR-006/008, Constitution IV) ---------------------


def test_env_exec_spec_maps_container(wiz):
    spec = wiz.env_exec_spec(
        {
            "name": "acme",
            "container": {"mode": "headless", "agent": "codex", "workspace": "ephemeral"},
        }
    )
    assert (spec.mode, spec.agent, spec.workspace) == ("headless", "codex", "ephemeral")


def _spec(mode="interactive", agent="claude", repo=None, workspace="persistent"):
    # tiny helper: the ExecSpec constructor lives in wiz; imported per-test via fixture
    return dict(mode=mode, agent=agent, repo=repo, workspace=workspace)


def test_env_reconcile_absent_matching_stopped(wiz, monkeypatch):
    cname = wiz.container_name("acme")
    spec = wiz.ExecSpec(**_spec())
    # absent — no container for the identity
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    assert wiz.env_reconcile(LOCAL_HOST, "acme", spec) == ("absent", "")
    # running + live config matches the spec → matching
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(
        wiz,
        "env_live_config",
        lambda hr, n: {"mode": "interactive", "agent": "claude", "repo": None},
    )
    assert wiz.env_reconcile(LOCAL_HOST, "acme", spec) == ("matching", "")
    # present but stopped → drifted (existence-level), never touches live config
    monkeypatch.setattr(
        wiz,
        "host_container_names",
        lambda host, include_stopped=False: {cname} if include_stopped else set(),
    )
    state, detail = wiz.env_reconcile(LOCAL_HOST, "acme", spec)
    assert state == "drifted" and "stopped" in detail


def test_env_reconcile_field_level_drift(wiz, monkeypatch):
    # US3: a running container whose agent-config differs from the spec is drifted,
    # and the detail names each changed field (live→desired).
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(
        wiz,
        "env_live_config",
        lambda hr, n: {"mode": "interactive", "agent": "claude", "repo": None},
    )
    spec = wiz.ExecSpec(**_spec(agent="codex"))  # declared agent changed
    state, detail = wiz.env_reconcile(LOCAL_HOST, "acme", spec)
    assert state == "drifted" and "agent" in detail and "codex" in detail and "claude" in detail


def test_env_reconcile_repo_drift_redacts_embedded_credential(wiz, monkeypatch):
    # Least exposure (III): a credential embedded in the declared repo URL must NOT
    # appear in the drift detail (status/apply log it). Adversarial-verify MEDIUM.
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(
        wiz,
        "env_live_config",
        lambda hr, n: {"mode": "interactive", "agent": "claude", "repo": None},
    )
    spec = wiz.ExecSpec(mode="interactive", agent="claude", workspace="persistent")
    spec.repo = "ssh://git:s3cr3t@github.com/o/r.git"
    state, detail = wiz.env_reconcile(LOCAL_HOST, "acme", spec)
    assert state == "drifted" and "repo" in detail
    assert "s3cr3t" not in detail and "git@github.com" in detail  # password stripped, user kept
    # https token form is redacted whole-userinfo
    spec.repo = "https://x-access-token:ghp_SECRET@github.com/o/r.git"
    _s, detail = wiz.env_reconcile(LOCAL_HOST, "acme", spec)
    assert "ghp_SECRET" not in detail and "x-access-token" not in detail


def test_env_reconcile_uninspectable_is_existence_match(wiz, monkeypatch):
    # A running-but-not-inspectable container must NOT read as a false drift/matching
    # from a failed probe — it degrades to existence-level 'matching' (no false churn).
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(wiz, "env_live_config", lambda hr, n: None)
    assert wiz.env_reconcile(LOCAL_HOST, "acme", wiz.ExecSpec(**_spec())) == ("matching", "")


def test_config_drift_pure(wiz):
    same = {"mode": "interactive", "agent": "claude", "repo": None}
    assert wiz.config_drift(same, same) == []
    d = wiz.config_drift(
        {"mode": "headless", "agent": "claude", "repo": "r"},
        {"mode": "interactive", "agent": "claude", "repo": None},
    )
    assert ("mode", "headless", "interactive") in d and ("repo", "r", None) in d
    assert not any(f == "agent" for f, _, _ in d)  # unchanged field omitted


def test_env_live_config_parses_inspect_env(wiz, monkeypatch):
    import subprocess

    out = '["PATH=/usr/bin", "AGENT_CONTAINER_MODE=headless", "AGENT_CONTAINER_AGENT=codex"]'
    monkeypatch.setattr(
        wiz, "query", lambda argv, timeout=None: subprocess.CompletedProcess(argv, 0, out, "")
    )
    cfg = wiz.env_live_config(LOCAL_HOST, "acme")
    assert cfg == {"mode": "headless", "agent": "codex", "repo": None}
    # a failed inspect → None (never a fabricated config)
    monkeypatch.setattr(
        wiz, "query", lambda argv, timeout=None: subprocess.CompletedProcess(argv, 1, "", "no such")
    )
    assert wiz.env_live_config(LOCAL_HOST, "acme") is None


# --- FR-020 read-only spec delivery ------------------------------------------


def test_stage_agent_container_spec_ro_targets(wiz, tmp_path):
    root = _project(tmp_path, MINIMAL)
    (root / ".agent-container" / "sub").mkdir()
    (root / ".agent-container" / "sub" / "extra.yaml").write_text("environments: []\n")
    entries = wiz.stage_agent_container_spec("local", "acme", root)
    targets = sorted(t for _n, _f, t in entries)
    assert "/workspace/.agent-container/project.yaml" in targets
    assert "/workspace/.agent-container/sub/extra.yaml" in targets
    # every target is under the read-only spec dir
    assert all(t.startswith("/workspace/.agent-container/") for _n, _f, t in entries)


def test_verify_refuses_bind_workspace(wiz, tmp_path):
    root = _project(tmp_path, MINIMAL)
    aac = wiz.stage_agent_container_spec("local", "acme", root)
    # FR-020 (M3): a bind workspace would expose the spec writable -> refuse.
    with pytest.raises(wiz.Fatal, match="spec-integrity"):
        wiz._verify_ro_spec_delivery(aac, wiz.ExecSpec(workspace="bind"))
    wiz._verify_ro_spec_delivery(aac, wiz.ExecSpec(workspace="persistent"))  # ok


# --- apply / status orchestration (US1) --------------------------------------


@pytest.fixture
def aac_env(wiz, monkeypatch):
    """Stub host resolution + live state + effects so apply/status are hermetic."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: (h or "local", LOCAL_HOST))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda host: None)
    # Default: running containers are inspected as existence-level matches (no real
    # `docker inspect` subprocess in the hermetic tier). Drift tests override this.
    monkeypatch.setattr(wiz, "env_live_config", lambda hr, n: None)
    calls: dict = {"up": [], "down": []}
    monkeypatch.setattr(wiz, "do_up", lambda name, **kw: calls["up"].append((name, kw)))
    monkeypatch.setattr(
        wiz, "down_container", lambda hn, hr, name, purge=False, **kw: calls["down"].append(name)
    )
    return calls


def test_apply_absent_drives_do_up_with_ro_configs(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(tmp_path, MINIMAL)
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_apply(yes=True)
    assert len(aac_env["up"]) == 1
    name, kw = aac_env["up"][0]
    assert name == "acme"
    # the .agent-container spec rides as read-only configs (FR-020)
    aac = kw["extra_injected_configs"]
    assert aac and all(t.startswith("/workspace/.agent-container/") for _n, _f, t in aac)


def test_apply_matching_is_idempotent_no_op(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(tmp_path, MINIMAL)
    monkeypatch.chdir(root)
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    wiz.do_aac_apply(yes=True)
    assert aac_env["up"] == []  # SC-002: no change


def test_apply_inert_when_no_project(wiz, tmp_path, monkeypatch):
    (tmp_path / "plain").mkdir()
    monkeypatch.chdir(tmp_path / "plain")
    with pytest.raises(wiz.Fatal, match="no .agent-container/ project"):
        wiz.do_aac_apply(yes=True)


def test_status_reports_plan_without_mutation(wiz, aac_env, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, MINIMAL)
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_status()
    assert aac_env["up"] == [] and aac_env["down"] == []  # no mutation
    err = capsys.readouterr().err
    assert "acme" in err and "absent" in err and "project root" in err  # reports root + state


def test_apply_host_override_deploys_to_override(wiz, aac_env, tmp_path, monkeypatch):
    # Regression (verification HIGH): --host must deploy to the override, not the
    # spec's declared host, matching the previewed plan.
    root = _project(tmp_path, MINIMAL)  # spec host: local
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_apply(host_override="staging", yes=True)
    _name, kw = aac_env["up"][0]
    assert kw["host"] == "staging"  # NOT "local"


def test_precheck_rejects_bind_upfront_no_partial_apply(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(
        tmp_path,
        "environments:\n  - name: a\n    host: local\n  - name: b\n    host: local\n"
        "    container:\n      workspace: bind\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    with pytest.raises(wiz.Fatal, match="workspace=bind"):
        wiz.do_aac_apply(yes=True)
    assert aac_env["up"] == []  # FR-003: no env deployed before the later bind env is rejected


def test_precheck_rejects_provision_table_upfront_even_with_host_override(
    wiz, aac_env, tmp_path, monkeypatch
):
    root = _project(
        tmp_path,
        "environments:\n  - name: a\n    host: local\n  - name: b\n    host: { provision: hetzner }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    with pytest.raises(wiz.Fatal, match="not yet supported"):
        wiz.do_aac_apply(host_override="x", yes=True)  # override must not bypass the guard
    assert aac_env["up"] == []


def test_unknown_top_level_key_dies(wiz, tmp_path):
    root = _project(tmp_path, "version: 1\nenvironments:\n  - name: acme\n    host: local\n")
    with pytest.raises(wiz.Fatal, match="unknown top-level key 'version'"):
        wiz.load_project_spec(root)


def test_credential_unknown_key_dies(wiz):
    with pytest.raises(wiz.Fatal, match="unknown credential key 'extra'"):
        wiz.validate_credential({"name": "K", "source": "env", "var": "V", "extra": 1}, "w")


def test_non_utf8_spec_dies_cleanly(wiz, tmp_path):
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "bad.yaml").write_bytes(b"environments:\n  - name: \x80\n")
    with pytest.raises(wiz.Fatal, match="cannot read spec file"):
        wiz.load_project_spec(root)


# --- US2: credential resolution (FR-011..016) --------------------------------


def test_resolve_credential_env(wiz, tmp_path, monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-secret")
    assert (
        wiz.resolve_credential_value({"name": "K", "source": "env", "var": "MY_KEY"}, tmp_path)
        == "sk-secret"
    )


def test_resolve_credential_env_missing_dies(wiz, tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    with pytest.raises(wiz.Fatal, match="is not set"):
        wiz.resolve_credential_value({"name": "K", "source": "env", "var": "ABSENT_KEY"}, tmp_path)


def test_resolve_credential_external_file(wiz, tmp_path):
    ext = tmp_path / "outside.key"  # OUTSIDE any project root
    ext.write_text("file-secret")
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    assert (
        wiz.resolve_credential_value({"name": "K", "source": "file", "path": str(ext)}, root)
        == "file-secret"
    )


def test_resolve_credential_keychain(wiz, tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(
        wiz.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="kc-secret\n"),
    )
    cred = {"name": "K", "source": "keychain", "service": "s", "account": "a"}
    assert wiz.resolve_credential_value(cred, tmp_path) == "kc-secret"


def test_resolve_credential_encrypted_in_memory(wiz, tmp_path, monkeypatch):
    import subprocess

    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "s.age").write_text("ENCRYPTED-BYTES")
    seen = {}

    def fake_run(argv, **k):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="decrypted-secret")

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    cred = {
        "name": "K",
        "source": "encrypted",
        "path": ".agent-container/s.age",
        "decrypt": "age -d -i key",
    }
    assert wiz.resolve_credential_value(cred, root) == "decrypted-secret"
    assert "decrypted-secret" not in " ".join(seen["argv"])  # secret never on argv


def test_refuse_git_tracked_plaintext(wiz, tmp_path, monkeypatch):
    import subprocess

    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    secret = root / ".agent-container" / "plain.key"
    secret.write_text("leak")
    monkeypatch.setattr(
        wiz.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0)
    )  # tracked
    with pytest.raises(wiz.Fatal, match="tracked by git"):
        wiz.resolve_credential_value({"name": "K", "source": "file", "path": str(secret)}, root)


def test_stage_credentials_provider_apikey_file_channel(wiz, tmp_path, monkeypatch):
    monkeypatch.setenv("AK", "sk-anthropic")
    creds = [{"name": "ANTHROPIC_API_KEY", "source": "env", "var": "AK"}]
    configs, env_file = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert env_file is None  # provider key does NOT go via env
    (cfgname, staged, target) = configs[0]
    assert target == f"{wiz.INJECT_APIKEY_DIR}/anthropic"
    assert (
        "sk-anthropic" not in cfgname and "sk-anthropic" not in target
    )  # secret not in names/targets
    assert staged.read_text() == "sk-anthropic" and (staged.stat().st_mode & 0o777) == 0o600


def test_stage_credentials_env_delivery_merges_base(wiz, tmp_path, monkeypatch):
    monkeypatch.setenv("GT", "ghp_secret")
    base = tmp_path / "base.env"
    base.write_text("GIT_USER_NAME=x\n")
    creds = [{"name": "GH_TOKEN", "source": "env", "var": "GT"}]
    configs, env_file = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, base)
    assert configs == []
    text = env_file.read_text()
    assert "GIT_USER_NAME=x" in text and "GH_TOKEN=ghp_secret" in text  # merged
    assert (env_file.stat().st_mode & 0o777) == 0o600


def test_stage_credentials_multiline_env_value_refused(wiz, tmp_path):
    ext = tmp_path / "key.pem"
    ext.write_text("-----BEGIN-----\nline2\n-----END-----\n")
    creds = [{"name": "SOME_KEY", "source": "file", "path": str(ext)}]
    with pytest.raises(wiz.Fatal, match="multi-line"):
        wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)


def test_apply_injects_declared_credentials(wiz, aac_env, tmp_path, monkeypatch):
    monkeypatch.setenv("AK", "sk-live")
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n    credentials:\n"
        "      - { name: ANTHROPIC_API_KEY, source: env, var: AK }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_apply(yes=True)
    _name, kw = aac_env["up"][0]
    targets = [t for _n, _f, t in kw["extra_injected_configs"]]
    assert (
        f"{wiz.INJECT_APIKEY_DIR}/anthropic" in targets
    )  # credential injected via the 003 channel
    # the secret value is never in the config names/targets passed to do_up
    assert not any("sk-live" in n or "sk-live" in t for n, _f, t in kw["extra_injected_configs"])


def test_apply_pre_resolves_credentials_before_any_deploy(wiz, aac_env, tmp_path, monkeypatch):
    # Regression (verification HIGH / FR-016): a missing source in a LATER env must
    # die BEFORE any earlier env is deployed.
    monkeypatch.setattr(wiz, "resolve_env_file", lambda name: None)
    monkeypatch.delenv("MISSING_K", raising=False)
    root = _project(
        tmp_path,
        "environments:\n  - name: a\n    host: local\n  - name: b\n    host: local\n"
        "    credentials:\n      - { name: X, source: env, var: MISSING_K }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    with pytest.raises(wiz.Fatal, match="MISSING_K"):
        wiz.do_aac_apply(yes=True)
    assert aac_env["up"] == []  # env 'a' was NOT deployed


def test_apply_preserves_convention_env_as_merge_base(wiz, aac_env, tmp_path, monkeypatch):
    # Regression (verification HIGH): credentials must MERGE onto the convention .env
    # (GH_TOKEN/GIT_*), not replace it.
    conv = tmp_path / "conv.env"
    conv.write_text("GH_TOKEN=from-dotenv\n")
    monkeypatch.setattr(wiz, "resolve_env_file", lambda name: conv)
    monkeypatch.setenv("AK", "sk-live")
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n    credentials:\n"
        "      - { name: OTHER, source: env, var: AK }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_apply(yes=True)
    _name, kw = aac_env["up"][0]
    merged = kw["env_file_override"].read_text()
    assert "GH_TOKEN=from-dotenv" in merged and "OTHER=sk-live" in merged


def test_env_credential_dotenv_unsafe_value_refused(wiz, tmp_path, monkeypatch):
    monkeypatch.setenv("V", "tok #comment")  # an inline ' #' would be mangled by dotenv
    creds = [{"name": "TOK", "source": "env", "var": "V"}]
    with pytest.raises(wiz.Fatal, match="mangle"):
        wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)


def test_env_credential_invalid_name_refused(wiz, tmp_path, monkeypatch):
    monkeypatch.setenv("V", "x")
    creds = [{"name": "BAD NAME", "source": "env", "var": "V"}]  # not a valid env identifier
    with pytest.raises(wiz.Fatal, match="valid environment-variable identifier"):
        wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)


def test_apikey_trailing_newline_stripped(wiz, tmp_path, monkeypatch):
    ext = tmp_path / "anthropic.key"
    ext.write_text("sk-ant-key\n")  # file ends in a newline
    creds = [{"name": "anthropic", "source": "file", "path": str(ext)}]
    configs, _env = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert configs[0][1].read_text() == "sk-ant-key"  # no trailing newline in the apikey file


def test_config_tokens_and_staged_files_injective(wiz, tmp_path):
    root = _project(tmp_path, MINIMAL)
    # two paths that a lossy flattener could collide
    (root / ".agent-container" / "a-b.yaml").write_text("environments: []\n")
    (root / ".agent-container" / "a_b.yaml").write_text("environments: []\n")
    entries = wiz.stage_agent_container_spec("local", "acme", root)
    tokens = [t for t, _f, _tg in entries]
    staged = [str(f) for _t, f, _tg in entries]
    targets = [tg for _t, _f, tg in entries]
    assert len(tokens) == len(set(tokens))  # unique config resource names
    assert len(staged) == len(set(staged))  # unique staged files
    assert len(targets) == len(set(targets))  # unique in-container targets


# --- US3: drift, converge, scoped teardown (FR-008/009/010, SC-003/006/007) ---


def test_apply_converges_config_drift_recreates(wiz, aac_env, tmp_path, monkeypatch):
    # A RUNNING container whose live agent-config differs from the spec is drifted;
    # apply announces then recreates it (down + up) to converge (FR-008).
    root = _project(tmp_path, MINIMAL)  # spec: interactive/claude
    monkeypatch.chdir(root)
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    # live differs (agent=codex) → config drift
    monkeypatch.setattr(
        wiz,
        "env_live_config",
        lambda hr, n: {"mode": "interactive", "agent": "codex", "repo": None},
    )
    wiz.do_aac_apply(yes=True)
    assert aac_env["down"] == ["acme"]  # recreated to converge
    assert len(aac_env["up"]) == 1


def test_status_reports_field_level_drift_no_mutation(wiz, aac_env, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, MINIMAL)
    monkeypatch.chdir(root)
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(
        wiz, "env_live_config", lambda hr, n: {"mode": "headless", "agent": "claude", "repo": None}
    )
    wiz.do_aac_status()
    assert aac_env["up"] == [] and aac_env["down"] == []  # FR-008: mutates nothing
    err = capsys.readouterr().err
    assert "drifted" in err and "mode" in err and "headless" in err  # the delta is shown


def test_status_plan_portable_across_checkout_paths(wiz, aac_env, tmp_path, monkeypatch, capsys):
    # FR-005/SC-003: the same spec from a fresh checkout at a DIFFERENT path yields an
    # identical plan (ownership is identity-derived; location does not affect it).
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())

    def plan_lines(base):
        root = _project(base, MINIMAL)
        monkeypatch.chdir(root)
        capsys.readouterr()  # drain
        wiz.do_aac_status()
        # drop the path-dependent "project root:" line; keep the reconcile plan lines
        return [ln for ln in capsys.readouterr().err.splitlines() if "project root" not in ln]

    a = plan_lines(tmp_path / "one")
    b = plan_lines(tmp_path / "two" / "nested")
    assert a == b and any("acme" in ln and "absent" in ln for ln in a)


def test_destroy_scoped_to_owned_identity(wiz, aac_env, tmp_path, monkeypatch):
    import contextlib

    root = _project(tmp_path, MINIMAL)
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "deployment_lock", lambda *a, **k: contextlib.nullcontext())
    wiz.do_aac_destroy(yes=True)
    # SC-007: destroy targets ONLY the declared identity's container/volumes via
    # down_container(purge=True) — an unrelated container is never named/touched.
    assert aac_env["down"] == ["acme"]


def test_destroy_partial_failure_reports_both(wiz, aac_env, tmp_path, monkeypatch):
    import contextlib

    root = _project(
        tmp_path,
        "environments:\n  - name: aa\n    host: local\n  - name: bb\n    host: local\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "deployment_lock", lambda *a, **k: contextlib.nullcontext())

    def flaky_down(hn, hr, name, purge=False, **kw):
        if name == "bb":
            wiz.die("host unreachable")
        aac_env["down"].append(name)

    monkeypatch.setattr(wiz, "down_container", flaky_down)
    # FR-010: one env fails, the other is removed, and the report names both.
    with pytest.raises(wiz.Fatal, match=r"removed \[aa\].*failed \[bb"):
        wiz.do_aac_destroy(yes=True)
    assert aac_env["down"] == ["aa"]
