"""Feature 006 (agent-as-code) unit tests — hermetic, no live runtime.

Cover discovery (upward walk), YAML parse + validation against the pinned schema
(`yaml.safe_load` — a `!!python/object` tag must NOT construct an object), the
reconcile plan (absent/matching/drifted) + ownership-by-identity, the read-only
`.agent-container` spec delivery (compose configs, FR-020) + the refuse-if-writable
verify, and the apply/status orchestration (idempotent; spec-wins precedence;
inert when no project). Requirement anchors named in the bodies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}


def _project(tmp_path, yaml_text: str):
    """Create tmp project with .agent-container/environments.yaml; return its root.

    The filename is load-bearing: a spec file is identified by KIND, and the suffix
    names the top-level key it contains. `project.yaml` (what this helper used
    before, and what the docs showed) is no longer a recognised kind.
    """
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "environments.yaml").write_text(yaml_text)
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
    with pytest.raises(wiz.Fatal, match="requires 'account'"):
        wiz.validate_credential({"name": "K", "source": "keychain", "service": "s"}, "w")


def test_env_host_binding_referenced_vs_provisioned(wiz, tmp_path):
    # US4: a string host is referenced; a provision table is provisioned. The
    # provisioned host's registry name defaults to the env name (RFC-1123).
    referenced = _project(tmp_path / "a", "environments:\n  - name: acme\n    host: hz1\n")
    (env,) = wiz.load_project_spec(referenced)
    assert wiz.env_host_binding(env) == ("hz1", None)
    provisioned = _project(
        tmp_path / "b", "environments:\n  - name: acme\n    host: { provision: hetzner }\n"
    )
    (env,) = wiz.load_project_spec(provisioned)
    hn, table = wiz.env_host_binding(env)
    assert hn == "acme" and table["provision"] == "hetzner"


def test_provision_table_validation(wiz, tmp_path):
    # bad provider enum
    bad = _project(tmp_path / "x", "environments:\n  - name: acme\n    host: { provision: aws }\n")
    with pytest.raises(wiz.Fatal, match="provision='aws'"):
        wiz.load_project_spec(bad)
    # underscore env name → invalid Hetzner host name unless host.name given
    us = _project(
        tmp_path / "y", "environments:\n  - name: my_box\n    host: { provision: hetzner }\n"
    )
    with pytest.raises(wiz.Fatal, match="RFC-1123"):
        wiz.load_project_spec(us)
    # unknown key inside the provision table rejected
    uk = _project(
        tmp_path / "z",
        "environments:\n  - name: acme\n    host: { provision: hetzner, bogus: 1 }\n",
    )
    with pytest.raises(wiz.Fatal, match="unknown host provision key 'bogus'"):
        wiz.load_project_spec(uk)
    # a non-string host.name dies cleanly naming the field (not a TypeError traceback)
    nn = _project(
        tmp_path / "n",
        "environments:\n  - name: acme\n    host: { provision: hetzner, name: 123 }\n",
    )
    with pytest.raises(wiz.Fatal, match="provision name must be a string"):
        wiz.load_project_spec(nn)


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
    (root / ".agent-container" / "sub" / "extra.environments.yaml").write_text("environments: []\n")
    # Delivery is deliberately WIDER than loading: every file in the directory rides
    # read-only (.env and .services.yaml included), while only spec-kind files are
    # parsed as spec. A non-spec file appearing here is correct, not a leak.
    (root / ".agent-container" / "acme.services.yaml").write_text("services:\n  x:\n    image: a\n")
    entries = wiz.stage_agent_container_spec("local", "acme", root)
    targets = sorted(t for _n, _f, t in entries)
    assert "/workspace/.agent-container/environments.yaml" in targets
    assert "/workspace/.agent-container/sub/extra.environments.yaml" in targets
    assert "/workspace/.agent-container/acme.services.yaml" in targets
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


_TWO_ENVS = (
    "environments:\n  - name: a\n    host: local\n  - name: b\n    host: { provision: hetzner }\n"
)


def test_provision_table_with_host_override_deploys_no_provisioning(
    wiz, aac_env, tmp_path, monkeypatch
):
    # US4: a --host override bypasses provisioning entirely — a provision-table env
    # deploys onto the override host, allocates nothing, needs no HCLOUD_TOKEN.
    root = _project(tmp_path, _TWO_ENVS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    called: list = []
    monkeypatch.setattr(wiz, "ensure_provisioned_host", lambda hn, t: called.append(hn) or {})
    wiz.do_aac_apply(host_override="x", yes=True)
    assert called == []  # never provisioned
    assert sorted(n for n, _kw in aac_env["up"]) == ["a", "b"]
    assert all(kw["host"] == "x" for _n, kw in aac_env["up"])


def test_provision_table_without_token_rejected_upfront(wiz, aac_env, tmp_path, monkeypatch):
    # US4: without --host and without HCLOUD_TOKEN, a provision-table env is refused
    # BEFORE any deploy (FR-003) — billable allocation needs the token.
    root = _project(tmp_path, _TWO_ENVS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    with pytest.raises(wiz.Fatal, match="requires HCLOUD_TOKEN"):
        wiz.do_aac_apply(yes=True)
    assert aac_env["up"] == []  # nothing deployed before the rejection


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
    # Must be a RECOGNISED spec kind, or the file-kind refusal fires first and this
    # never exercises the decode path it exists to cover.
    (root / ".agent-container" / "environments.yaml").write_bytes(
        b"environments:\n  - name: \x80\n"
    )
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


def test_resolve_credential_command_in_memory(wiz, tmp_path, monkeypatch):
    # The generic resolver: the declared argv is run verbatim and its stdout is the
    # secret. The VALUE never rides on argv — only the locator does (FR-013).
    import subprocess

    seen = {}

    def fake_run(argv, **k):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="resolved-secret\n")

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    cred = {"name": "K", "source": "command", "argv": ["pass", "show", "acme/key"]}
    assert wiz.resolve_credential_value(cred, tmp_path) == "resolved-secret\n"
    assert seen["argv"] == ["pass", "show", "acme/key"]
    assert "resolved-secret" not in " ".join(seen["argv"])  # secret never on argv


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
    configs, env_file, _ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
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
    configs, env_file, _ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, base)
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
    (merged_path,) = kw["env_file_override"]  # Feature 011: a list of one here
    merged = merged_path.read_text()
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
    configs, _env, _ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
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


# --- US4: declarative host provisioning (FR-017, SC-007) ---------------------


def _tool_host(provider="hetzner"):
    return {
        "driver": "docker",
        "context": "agent-container-prov",
        "address": "1.2.3.4",
        "created_by_tool": True,
        "provisioning": {"provider": provider, "server_id": 42, "created": True},
    }


def test_ensure_provisioned_host_idempotent_and_collision(wiz, monkeypatch):
    # Idempotency (no double-bill): an existing tool-created host of the same provider
    # is reused, provision_host is NEVER called again.
    existing = _tool_host()
    monkeypatch.setattr(
        wiz, "load_registry", lambda: {"hosts": {"acme": existing}, "default": "acme"}
    )
    called: list = []
    monkeypatch.setattr(wiz, "provision_host", lambda *a, **k: called.append(1) or {})
    assert wiz.ensure_provisioned_host("acme", {"provision": "hetzner"}) is existing
    assert called == []  # reused, not re-provisioned
    # a name collision with a host this spec did not create → refuse (no silent reuse)
    ref = {"driver": "docker", "context": "c", "created_by_tool": False, "provisioning": None}
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {"acme": ref}, "default": "acme"})
    with pytest.raises(wiz.Fatal, match="not provisioned by this spec"):
        wiz.ensure_provisioned_host("acme", {"provision": "hetzner"})


def test_apply_provisions_unregistered_host_before_deploy(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: { provision: hetzner }\n")
    monkeypatch.chdir(root)
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {}, "default": None})
    prov: list = []
    monkeypatch.setattr(
        wiz,
        "ensure_provisioned_host",
        lambda hn, t: prov.append((hn, t["provision"])) or dict(LOCAL_HOST),
    )
    wiz.do_aac_apply(yes=True)
    assert prov == [("acme", "hetzner")]  # provisioned first
    assert [n for n, _ in aac_env["up"]] == ["acme"]  # then deployed


def test_status_provision_table_plans_without_allocating(
    wiz, aac_env, tmp_path, monkeypatch, capsys
):
    # status/plan MUST NOT allocate a billable server — it reports the intent only.
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: { provision: hetzner }\n")
    monkeypatch.chdir(root)
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {}, "default": None})
    boom = lambda *a, **k: pytest.fail("status must not provision")  # noqa: E731
    monkeypatch.setattr(wiz, "provision_host", boom)
    monkeypatch.setattr(wiz, "ensure_provisioned_host", boom)
    wiz.do_aac_status()
    err = capsys.readouterr().err
    assert "will provision" in err and "acme" in err
    assert aac_env["up"] == []


def _destroy_env(wiz, monkeypatch, hosts):
    import contextlib

    monkeypatch.setattr(wiz, "deployment_lock", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(
        wiz, "load_registry", lambda: {"hosts": hosts, "default": next(iter(hosts), None)}
    )
    rm: list = []
    monkeypatch.setattr(wiz, "cli_host_rm", lambda name, destroy, yes: rm.append((name, destroy)))
    return rm


def test_destroy_deprovision_scoped_to_provisioned_host(wiz, aac_env, tmp_path, monkeypatch):
    # FR-017/SC-007: --deprovision removes the spec-PROVISIONED host only; a REFERENCED
    # host is never deprovisioned.
    root = _project(
        tmp_path,
        "environments:\n  - name: refenv\n    host: hz1\n"
        "  - name: prov\n    host: { provision: hetzner }\n",
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("HCLOUD_TOKEN", "tok")
    rm = _destroy_env(wiz, monkeypatch, {"hz1": {"created_by_tool": False}, "prov": _tool_host()})
    wiz.do_aac_destroy(yes=True, deprovision=True)
    assert aac_env["down"] == ["refenv", "prov"]  # both containers removed
    assert rm == [("prov", True)]  # ONLY the provisioned host deprovisioned; hz1 untouched


def test_destroy_without_deprovision_leaves_provisioned_host(wiz, aac_env, tmp_path, monkeypatch):
    # FR-017: deprovision is opt-in — a bare destroy removes containers, never the host.
    root = _project(tmp_path, "environments:\n  - name: prov\n    host: { provision: hetzner }\n")
    monkeypatch.chdir(root)
    rm = _destroy_env(wiz, monkeypatch, {"prov": _tool_host()})
    wiz.do_aac_destroy(yes=True, deprovision=False)
    assert aac_env["down"] == ["prov"] and rm == []  # container gone, host left intact


def test_destroy_deprovision_without_token_fails_upfront(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(tmp_path, "environments:\n  - name: prov\n    host: { provision: hetzner }\n")
    monkeypatch.chdir(root)
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    with pytest.raises(wiz.Fatal, match="deprovision needs HCLOUD_TOKEN"):
        wiz.do_aac_destroy(yes=True, deprovision=True)
    assert aac_env["down"] == []  # nothing torn down before the early refusal


# --- T012a: SSH-key credential routing (least exposure) ----------------------


def test_ssh_target_credential_routes_to_ssh_channel(wiz, tmp_path, monkeypatch):
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
    monkeypatch.setenv("PUSHKEY", key)  # multi-line — the env-file channel rejects this
    creds = [{"name": "git-push", "source": "env", "var": "PUSHKEY", "target": "push_key"}]
    configs, env_file, ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert configs == [] and env_file is None  # NOT the apikey/env channels
    assert ssh.push_key is not None and ssh.host_key is None and ssh.authorized_keys == []
    body = ssh.push_key.read_text()
    assert "BEGIN OPENSSH" in body and body.endswith("\n")  # multi-line kept, newline ensured
    import stat

    assert stat.S_IMODE(ssh.push_key.stat().st_mode) == 0o600  # 0600 staged file


def test_ssh_target_credential_invalid_target_rejected(wiz):
    with pytest.raises(wiz.Fatal, match="target='bogus'"):
        wiz.validate_credential({"name": "K", "source": "env", "var": "V", "target": "bogus"}, "w")


def test_apply_threads_ssh_push_key_to_do_up(wiz, aac_env, tmp_path, monkeypatch):
    spec_yaml = (
        "environments:\n  - name: acme\n    host: local\n"
        "    credentials:\n      - { name: gitpush, source: env, var: PUSHKEY, target: push_key }\n"
    )
    root = _project(tmp_path, spec_yaml)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PUSHKEY", "-----BEGIN KEY-----\nx\n-----END KEY-----")
    (root / ".env").write_text("GH_TOKEN=x\n")  # base env so do_up has one
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    wiz.do_aac_apply(yes=True)
    _name, kw = aac_env["up"][0]
    assert kw["push_key"] is not None and kw["push_key"].read_text().startswith("-----BEGIN KEY")


# --- Feature 008: credential managers ----------------------------------------
# The one audited resolver runner + the manager sources. Least exposure
# (Constitution III) is pinned explicitly: no shell, stdin closed, bounded, and a
# resolver's stderr must never reach the operator-visible message.


def _fake_run(monkeypatch, wiz, *, rc=0, out="secret", err="", raises=None):
    """Stub subprocess.run for the resolver, capturing how it was invoked."""
    import subprocess

    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)

    monkeypatch.setattr(wiz.subprocess, "run", fake)
    return seen


def test_run_resolver_no_shell_stdin_closed_bounded(wiz, monkeypatch):
    # T002: run the argv DIRECTLY (no shell), stdin closed, timeout applied.
    seen = _fake_run(monkeypatch, wiz, out="v")
    wiz._run_resolver(["op", "read", "op://a/b/c"], "K")
    assert seen["argv"] == ["op", "read", "op://a/b/c"]
    assert seen["kw"].get("shell") is None  # never shell=True (Constitution II/III)
    assert seen["kw"]["stdin"] is wiz.subprocess.DEVNULL  # non-interactive (FR-005)
    assert seen["kw"]["timeout"] == wiz.RESOLVER_TIMEOUT  # bounded (FR-005)


def test_run_resolver_metacharacters_passed_literally(wiz, monkeypatch):
    # A shell metacharacter in a locator is just a character — nothing interprets it.
    seen = _fake_run(monkeypatch, wiz, out="v")
    wiz._run_resolver(["pass", "show", "acme/key; rm -rf /"], "K")
    assert seen["argv"][2] == "acme/key; rm -rf /"


def test_run_resolver_timeout_dies(wiz, monkeypatch):
    import subprocess

    _fake_run(monkeypatch, wiz, raises=subprocess.TimeoutExpired("op", 30))
    with pytest.raises(wiz.Fatal, match="did not finish within"):
        wiz._run_resolver(["op", "read", "x"], "K")


def test_run_resolver_missing_binary_dies(wiz, monkeypatch):
    _fake_run(monkeypatch, wiz, raises=FileNotFoundError("no op"))
    with pytest.raises(wiz.Fatal, match="could not be run"):
        wiz._run_resolver(["op", "read", "x"], "K")


def test_run_resolver_nonzero_dies(wiz, monkeypatch):
    _fake_run(monkeypatch, wiz, rc=1, out="")
    with pytest.raises(wiz.Fatal, match="exited 1"):
        wiz._run_resolver(["op", "read", "x"], "K")


def test_run_resolver_empty_and_whitespace_only_die(wiz, monkeypatch):
    # FR-004: whitespace-only counts as empty — delivery strips the trailing newline,
    # so it would otherwise become a silently-injected EMPTY secret (analyze C2).
    for out in ("", "\n", "   \n\t "):
        _fake_run(monkeypatch, wiz, out=out)
        with pytest.raises(wiz.Fatal, match="produced no value"):
            wiz._run_resolver(["op", "read", "x"], "K")


def test_run_resolver_never_echoes_stderr(wiz, monkeypatch):
    # FR-006 / Constitution III: a secret planted on the resolver's stderr must not
    # reach the operator-visible message.
    _fake_run(monkeypatch, wiz, rc=1, out="", err="FATAL: token sk-LEAKED-ON-STDERR")
    with pytest.raises(wiz.Fatal) as e:
        wiz._run_resolver(["op", "read", "x"], "K")
    assert "sk-LEAKED-ON-STDERR" not in str(e.value)


def test_run_resolver_failure_carries_remediation_hint(wiz, monkeypatch):
    # FR-006: suppressing the resolver's own diagnostic must not leave the operator
    # without a clue — every failure carries a non-specific hint.
    import subprocess

    cases = [
        dict(rc=1, out=""),
        dict(out=""),
        dict(raises=FileNotFoundError("x")),
        dict(raises=subprocess.TimeoutExpired("op", 30)),
    ]
    for kw in cases:
        _fake_run(monkeypatch, wiz, **kw)
        with pytest.raises(wiz.Fatal) as e:
            wiz._run_resolver(["op", "read", "x"], "K")
        assert "unlocked" in str(e.value)  # the shared RESOLVER_HINT


# --- schema validation (T005/T008/T010) --------------------------------------


def test_command_argv_must_be_nonempty_string_list(wiz):
    ok = {"name": "K", "source": "command", "argv": ["op", "read", "x"]}
    wiz.validate_credential(ok, "w")
    for bad in ("op read x", [], ["op", 3], {"a": 1}):
        with pytest.raises(wiz.Fatal, match="argv"):
            wiz.validate_credential({"name": "K", "source": "command", "argv": bad}, "w")
    # argv missing entirely
    with pytest.raises(wiz.Fatal, match="requires 'argv'"):
        wiz.validate_credential({"name": "K", "source": "command"}, "w")


def test_named_manager_required_fields(wiz):
    wiz.validate_credential(
        {"name": "K", "source": "onepassword", "vault": "v", "item": "i", "field": "f"}, "w"
    )
    wiz.validate_credential({"name": "K", "source": "bitwarden", "item": "i", "field": "f"}, "w")
    with pytest.raises(wiz.Fatal, match="requires 'field'"):
        wiz.validate_credential(
            {"name": "K", "source": "onepassword", "vault": "v", "item": "i"}, "w"
        )
    with pytest.raises(wiz.Fatal, match="requires 'item'"):
        wiz.validate_credential({"name": "K", "source": "bitwarden", "field": "password"}, "w")


def test_named_manager_unknown_key_rejected(wiz):
    with pytest.raises(wiz.Fatal, match="unknown credential key 'argv'"):
        wiz.validate_credential(
            {"name": "K", "source": "bitwarden", "item": "i", "field": "f", "argv": ["x"]}, "w"
        )


def test_encrypted_source_refused_with_migration(wiz, tmp_path):
    # FR-009/SC-003: the removed source must give an ACTIONABLE migration, not the
    # generic "not one of {…}" enum error.
    cred = {"name": "K", "source": "encrypted", "path": "s.age", "decrypt": "age -d"}
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_credential(cred, "w")
    msg = str(e.value)
    assert "REMOVED" in msg
    assert "onepassword" in msg and "keychain" in msg  # names the migration targets
    assert "is not one of" not in msg  # NOT the generic enum error
    # and it is refused at spec-load time, before any action (FR-015)
    root = _project(
        tmp_path,
        "environments:\n  - name: acme\n    host: local\n    credentials:\n"
        "      - { name: K, source: encrypted, path: s.age, decrypt: 'age -d' }\n",
    )
    with pytest.raises(wiz.Fatal, match="REMOVED"):
        wiz.load_project_spec(root)


def test_retained_sources_still_validate(wiz):
    # Regression guard: 008 must not disturb the Feature 006 sources.
    wiz.validate_credential({"name": "K", "source": "env", "var": "V"}, "w")
    wiz.validate_credential({"name": "K", "source": "file", "path": "/x/k"}, "w")
    wiz.validate_credential(
        {"name": "K", "source": "keychain", "service": "s", "account": "a"}, "w"
    )


# --- resolver argv assembly (T005/T008) --------------------------------------


def test_resolver_argv_assembly(wiz):
    assert wiz.resolver_argv({"source": "command", "argv": ["a", "b"]}) == ["a", "b"]
    assert wiz.resolver_argv(
        {"source": "onepassword", "vault": "Personal", "item": "anthropic", "field": "key"}
    ) == ["op", "read", "op://Personal/anthropic/key"]
    assert wiz.resolver_argv({"source": "bitwarden", "item": "gh", "field": "password"}) == [
        "bw",
        "get",
        "password",
        "gh",
    ]


def test_named_sources_resolve_identically_to_command(wiz, tmp_path, monkeypatch):
    # SC-005: a named reference resolves exactly as the equivalent generic resolver.
    calls = []
    monkeypatch.setattr(wiz, "_run_resolver", lambda argv, name, **k: calls.append(argv) or "S")
    named = {"name": "K", "source": "onepassword", "vault": "V", "item": "I", "field": "F"}
    generic = {"name": "K", "source": "command", "argv": ["op", "read", "op://V/I/F"]}
    assert wiz.resolve_credential_value(named, tmp_path) == "S"
    assert wiz.resolve_credential_value(generic, tmp_path) == "S"
    assert calls[0] == calls[1]  # identical invocation


# --- FR-002: plan/status must never invoke a resolver ------------------------


_CMD_SPEC = (
    "environments:\n  - name: acme\n    host: local\n"
    "    credentials:\n      - { name: MYSECRET, source: command, argv: ['printf', 'v'] }\n"
)


def test_plan_status_never_invokes_a_resolver(wiz, aac_env, tmp_path, monkeypatch):
    # FR-002: a read-only preview must not contact the manager — otherwise `status`
    # would trigger a manager prompt or a hardware-key touch.
    root = _project(tmp_path, _CMD_SPEC)
    monkeypatch.chdir(root)
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(
        wiz, "_run_resolver", lambda *a, **k: pytest.fail("status must not resolve credentials")
    )
    wiz.do_aac_status()
    assert aac_env["up"] == [] and aac_env["down"] == []


def test_apply_resolves_and_delivers_command_credential(wiz, aac_env, tmp_path, monkeypatch):
    root = _project(tmp_path, _CMD_SPEC)
    monkeypatch.chdir(root)
    (root / ".env").write_text("GH_TOKEN=x\n")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(wiz, "_run_resolver", lambda argv, name, **k: "sk-resolved\n")
    wiz.do_aac_apply(yes=True)
    _name, kw = aac_env["up"][0]
    (env_file,) = kw["env_file_override"]  # Feature 011: a list of one here
    assert env_file is not None and "MYSECRET=sk-resolved" in env_file.read_text()


# --- T007a: delivery regression guard (FR-012) -------------------------------


def test_delivery_routing_unchanged_for_new_sources(wiz, tmp_path, monkeypatch):
    # FR-012: a value resolved from a NEW source still routes through the unchanged
    # Feature 003 channels — provider name -> apikey FILE channel (never the env).
    monkeypatch.setattr(wiz, "_run_resolver", lambda argv, name, **k: "sk-ant\n")
    creds = [{"name": "anthropic", "source": "command", "argv": ["op", "read", "x"]}]
    configs, env_file, ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert configs and configs[0][2] == f"{wiz.INJECT_APIKEY_DIR}/anthropic"
    assert env_file is None and ssh.push_key is None  # not the env/ssh channels


def test_delivery_strips_trailing_newline_for_apikey_and_env(wiz, tmp_path, monkeypatch):
    # FR-012: a manager's trailing newline must not corrupt the delivered value.
    monkeypatch.setattr(wiz, "_run_resolver", lambda argv, name, **k: "sk-value\n")
    creds = [{"name": "anthropic", "source": "command", "argv": ["x"]}]
    configs, _e, _s = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert configs[0][1].read_text() == "sk-value"  # stripped
    creds = [{"name": "MYVAR", "source": "onepassword", "vault": "v", "item": "i", "field": "f"}]
    _c, env_file, _s = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert env_file.read_text().rstrip("\n").endswith("MYVAR=sk-value")  # no stray newline


def test_delivery_ensures_trailing_newline_for_ssh_target(wiz, tmp_path, monkeypatch):
    # FR-012: SSH-key delivery needs the terminating newline ensured, not stripped.
    monkeypatch.setattr(
        wiz, "_run_resolver", lambda argv, name, **k: "-----BEGIN KEY-----\nabc\n-----END KEY-----"
    )
    creds = [
        {"name": "gitpush", "source": "command", "argv": ["op", "read", "x"], "target": "push_key"}
    ]
    _c, _e, ssh = wiz.stage_declared_credentials("local", "acme", creds, tmp_path, None)
    assert ssh.push_key is not None
    assert ssh.push_key.read_text().endswith("-----END KEY-----\n")


def test_delivered_spec_path_and_read_only_survive_feature_011(wiz):
    """FR-012 (analysis C3). The delivered spec deliberately does NOT move.

    `/workspace/.agent-container` SHOULD echo the project config name, because it
    is literally that directory delivered read-only — unlike `~/.agent-container`,
    which shared the name while being unrelated and was renamed. Pinned here so
    that distinction is a decision on record rather than an accident someone
    "tidies up" later, and so FR-012 has a test of its own rather than being
    covered only incidentally by the full-suite run.
    """
    assert wiz.INJECT_AAC_DIR == "/workspace/.agent-container"
    src = (Path(__file__).resolve().parents[1] / "agent-container").read_text()
    marker = 'target.startswith(INJECT_AAC_DIR + "/")'
    assert marker in src, "the delivered-spec containment check disappeared"


# --- file kinds: a spec and a sidecar must share one directory (011 amendment) ---
# The rule, one line: THE SUFFIX NAMES THE TOP-LEVEL YAML KEY THE FILE CONTAINS.


def test_spec_and_sidecar_override_coexist(wiz, tmp_path):
    """The regression this amendment exists for.

    Feature 011 put both the declarative spec and `<name>.services.yaml` in
    `.agent-container/`. The spec loader claimed EVERY *.yaml by glob and died on
    the sidecar's `services:` key — so two documented features could not be used
    together at all. Neither suite caught it: the spec tests never wrote a
    sidecar, and the sidecar tests never wrote a spec.
    """
    root = _project(tmp_path, MINIMAL)
    (root / ".agent-container" / "acme.services.yaml").write_text(
        "services:\n  redis:\n    image: redis:7\n"
    )
    envs = wiz.load_project_spec(root)
    assert [e["name"] for e in envs] == ["acme"]


def test_spec_files_selected_by_kind_not_by_glob(wiz, tmp_path):
    """Bare `environments.yaml` and prefixed `*.environments.yaml` are both specs;
    a sidecar is not, and its environments are never merged in."""
    root = _project(tmp_path, MINIMAL)
    (root / ".agent-container" / "prod.environments.yaml").write_text(
        MINIMAL.replace("acme", "prod")
    )
    (root / ".agent-container" / "acme.services.yaml").write_text("services:\n  x:\n    image: a\n")
    assert sorted(e["name"] for e in wiz.load_project_spec(root)) == ["acme", "prod"]


def test_unrecognised_yaml_is_refused_naming_it(wiz, tmp_path):
    """A typo must fail LOUDLY. Silently skipping `enviroments.yaml` would report
    'no environments' with no hint that a file was ignored — trading a loud bug
    for a quiet one."""
    root = _project(tmp_path, MINIMAL)
    (root / ".agent-container" / "enviroments.yaml").write_text(MINIMAL)
    with pytest.raises(wiz.Fatal) as e:
        wiz.load_project_spec(root)
    msg = str(e.value)
    assert "enviroments.yaml" in msg
    assert "--skip-unknown-files" in msg, "the refusal must name its own escape hatch"


def test_skip_unknown_downgrades_refusal_to_warning(wiz, tmp_path):
    """The operator-requested escape hatch: keep unrelated YAML, get a warning."""
    root = _project(tmp_path, MINIMAL)
    (root / ".agent-container" / "notes.yaml").write_text("anything: at all\n")
    assert [e["name"] for e in wiz.load_project_spec(root, skip_unknown=True)] == ["acme"]


def test_pre_amendment_spec_filename_is_refused(wiz, tmp_path):
    """`project.yaml` — what the docs showed and the test helper used — is no
    longer a recognised kind. Refused, not silently ignored, so an operator on the
    old name is told rather than left with an empty plan."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "project.yaml").write_text(MINIMAL)
    with pytest.raises(wiz.Fatal) as e:
        wiz.load_project_spec(root)
    assert "project.yaml" in str(e.value)


# --- Feature 012: the egress declaration (contracts C1) ----------------------


def _egress(tmp_path, block: str, sub: str = ""):
    return _project(
        tmp_path / (sub or "e"),
        "environments:\n  - name: acme\n    host: local\n    egress:\n" + block,
    )


def test_egress_absent_empty_and_populated_are_three_distinct_states(wiz, tmp_path):
    """data-model §2. Absent must NEVER coerce to empty: absent is unrestricted,
    empty is air-gapped. Conflating them would turn every existing environment
    air-gapped on upgrade — a silent, total change of behaviour."""
    absent = _project(tmp_path / "a", MINIMAL)
    (env,) = wiz.load_project_spec(absent)
    assert "egress" not in env
    assert wiz.resolve_provider_hosts(env.get("egress")) == []

    empty = _egress(tmp_path, "      providers: []\n", "b")
    (env,) = wiz.load_project_spec(empty)
    assert env["egress"]["providers"] == []  # declared, and declared EMPTY
    assert wiz.resolve_provider_hosts(env["egress"]) == []

    populated = _egress(tmp_path, "      providers: [anthropic]\n", "c")
    (env,) = wiz.load_project_spec(populated)
    assert wiz.resolve_provider_hosts(env["egress"]) == [
        ("anthropic", ("api.anthropic.com",), "tool")
    ]


def test_egress_providers_bare_string_dies_naming_the_field(wiz, tmp_path):
    """Must not iterate the characters — "anthropic" is one provider, not nine."""
    root = _egress(tmp_path, "      providers: anthropic\n")
    with pytest.raises(wiz.Fatal, match="'providers' must be a list"):
        wiz.load_project_spec(root)


def test_egress_unknown_name_short_form_dies_listing_known(wiz, tmp_path):
    root = _egress(tmp_path, "      providers: [nosuchvendor]\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.load_project_spec(root)
    msg = str(e.value)
    assert "nosuchvendor" in msg and "anthropic" in msg
    assert "hosts:" in msg, "must point at the escape hatch it is telling them they need"


def test_egress_unknown_name_long_form_is_accepted(wiz, tmp_path):
    """FR-001a: the whole point of the escape hatch. A corporate gateway has a
    name the tool has never heard of; the hosts are authoritative."""
    root = _egress(
        tmp_path,
        "      providers:\n        - name: corp-llm\n          hosts: [gw.corp.internal]\n",
    )
    (env,) = wiz.load_project_spec(root)
    assert wiz.resolve_provider_hosts(env["egress"]) == [
        ("corp-llm", ("gw.corp.internal",), "declaration")
    ]


def test_egress_hosts_replace_never_extend(wiz, tmp_path):
    """FR-001b — the load-bearing sub-decision, invisible in a passing deploy.

    An operator routing through a gateway is closing the direct vendor path.
    Additive semantics would leave api.anthropic.com reachable while the
    declaration reads as constrained.
    """
    root = _egress(
        tmp_path, "      providers:\n        - name: anthropic\n          hosts: [gw.corp]\n"
    )
    (env,) = wiz.load_project_spec(root)
    ((name, hosts, source),) = wiz.resolve_provider_hosts(env["egress"])
    assert name == "anthropic" and source == "declaration"
    assert hosts == ("gw.corp",)
    assert "api.anthropic.com" not in hosts, "hosts: must REPLACE the mapping, not extend it"


def test_egress_long_form_without_hosts_dies(wiz, tmp_path):
    root = _egress(tmp_path, "      providers:\n        - name: anthropic\n")
    with pytest.raises(wiz.Fatal, match="requires 'hosts'"):
        wiz.load_project_spec(root)


@pytest.mark.parametrize(
    "bad", ["https://gw.corp", "gw.corp:8443", "gw.corp/v1", "gw corp", "-gw.corp"]
)
def test_egress_non_hostname_dies_naming_the_field(wiz, tmp_path, bad):
    """A URL accepted here would never match a CONNECT target — permitting
    nothing, silently. Refuse it at parse time instead."""
    root = _egress(
        tmp_path, f"      providers:\n        - name: x\n          hosts: ['{bad}']\n", sub=bad[:4]
    )
    with pytest.raises(wiz.Fatal, match="is not a hostname"):
        wiz.load_project_spec(root)


def test_egress_unknown_keys_die(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="unknown key 'bogus'"):
        wiz.load_project_spec(_egress(tmp_path, "      bogus: 1\n", "k1"))
    with pytest.raises(wiz.Fatal, match="unknown provider key 'bogus'"):
        wiz.load_project_spec(
            _egress(
                tmp_path,
                "      providers:\n        - name: x\n          hosts: [a.b]\n          bogus: 1\n",
                "k2",
            )
        )


def test_egress_enforcement_enum(wiz, tmp_path):
    ok = _egress(tmp_path, "      providers: [anthropic]\n      enforcement: strict\n", "ok")
    (env,) = wiz.load_project_spec(ok)
    assert env["egress"]["enforcement"] == "strict"
    bad = _egress(tmp_path, "      providers: []\n      enforcement: paranoid\n", "bad")
    with pytest.raises(wiz.Fatal, match="enforcement='paranoid'"):
        wiz.load_project_spec(bad)


def test_egress_without_providers_is_refused_as_the_fourth_state(wiz, tmp_path):
    """`egress:` present with no `providers` is neither declared nor undeclared.

    Reading it as unrestricted would let `enforcement: strict` sit in a file
    enforcing nothing; reading it as empty would air-gap on a key added for an
    unrelated reason. Both are silent, so it is refused — and the message must
    offer BOTH real states, since the operator's intent is genuinely ambiguous.
    """
    root = _egress(tmp_path, "      enforcement: strict\n", "fourth")
    with pytest.raises(wiz.Fatal) as e:
        wiz.load_project_spec(root)
    msg = str(e.value)
    assert "missing 'providers'" in msg
    assert "providers: []" in msg and "remove the egress block" in msg


def test_is_egress_declared_separates_absent_from_empty(wiz):
    """The presence gate T011f exists for: both states resolve to an empty
    allowlist, so presence can never be read off the resolved hosts."""
    assert wiz.is_egress_declared(None) is False
    assert wiz.is_egress_declared({"providers": []}) is True
    assert wiz.resolve_provider_hosts(None) == wiz.resolve_provider_hosts({"providers": []}) == []


def test_egress_filter_is_anchored_against_suffix_attack(wiz):
    """THE security boundary. tinyproxy matches filter lines UNANCHORED, so a bare
    hostname is a substring allowlist."""
    import re as _re

    pat = wiz.egress_filter_line("api.anthropic.com")
    rx = _re.compile(pat)
    assert rx.fullmatch("api.anthropic.com")
    for attack in (
        "api.anthropic.com.attacker.net",
        "evil-api.anthropic.com",
        "apiXanthropicYcom",
        "notapi.anthropic.com",
    ):
        assert not rx.match(attack), f"{pat!r} permits {attack!r}"


def test_egress_wildcard_matches_subdomains_but_not_suffix_attack(wiz):
    import re as _re

    rx = _re.compile(wiz.egress_filter_line("*.githubusercontent.com"))
    assert rx.fullmatch("objects.githubusercontent.com")
    assert rx.fullmatch("raw.githubusercontent.com")
    assert rx.fullmatch("githubusercontent.com"), "the bare domain must match too"
    for attack in ("githubusercontent.com.attacker.net", "evilgithubusercontent.com"):
        assert not rx.match(attack), f"wildcard permits {attack!r}"


def test_egress_empty_filter_body_denies_everything(wiz):
    """`providers: []` must produce an EMPTY allowlist body. With
    `FilterDefaultDeny Yes` that denies everything; an empty file that somehow
    meant allow-all would invert the air-gapped state, silently and totally."""
    assert wiz.build_egress_filter([]) == ""


def test_egress_host_length_is_capped(wiz, tmp_path):
    """An over-long entry splits across tinyproxy's 512-byte line buffer into two
    UNANCHORED patterns. Reachable through the FR-001a hosts: escape hatch."""
    long_host = ".".join(["a" * 60] * 8)  # 487 chars, regex-valid, over the DNS limit
    assert wiz.HOSTNAME_RE.fullmatch(long_host), "fixture must pass the shape check"
    root = _egress(
        tmp_path,
        f"      providers:\n        - name: x\n          hosts: ['{long_host}']\n",
        "long",
    )
    with pytest.raises(wiz.Fatal, match="over the 253-character DNS limit"):
        wiz.load_project_spec(root)


def test_egress_allow_carries_non_provider_hosts(wiz, tmp_path):
    """FR-001c. The proxy governs ALL egress, so git remotes and registries must be
    declarable — there is no hidden baseline (FR-001e)."""
    root = _egress(
        tmp_path,
        "      providers: [anthropic]\n      allow: [github.com, '*.githubusercontent.com']\n",
        "allow",
    )
    (env,) = wiz.load_project_spec(root)
    entries = wiz.resolve_provider_hosts(env["egress"])
    assert ("allow", ("github.com", "*.githubusercontent.com"), "declaration") in entries
    body = wiz.build_egress_filter(entries)
    assert "^github\\.com$" in body


def test_egress_not_a_mapping_dies(wiz, tmp_path):
    root = _project(tmp_path, "environments:\n  - name: acme\n    host: local\n    egress: nope\n")
    with pytest.raises(wiz.Fatal, match="egress: must be a mapping"):
        wiz.load_project_spec(root)
