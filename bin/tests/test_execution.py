"""Feature 004 (agent execution & session management) unit tests — hermetic, no
live runtime. Cover the compose-model plumbing (per-mode restart, workspace-mode
mount + conditional workspace volume, mode/agent/repo env, task inject), the
execution-mode CLI threading, the headless foreground argv + exit-code flags, the
dead-session probe, and the workspace/clone-on-start resolution incl. fail-fast.

Requirement anchors are named in the test bodies (FR-###/SC-###).
"""

from __future__ import annotations

import json
import subprocess

import pytest

LOCAL_HOST = {"driver": "podman", "context": "", "address": "localhost"}
REMOTE_HOST = {"driver": "docker", "context": "vps", "address": "vps.example.com"}


@pytest.fixture
def capture_compose(wiz, monkeypatch):
    """Record subprocess.run argv (the `compose up` invocation) and succeed."""
    calls: list[list[str]] = []

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    return calls


@pytest.fixture
def up_env(wiz, monkeypatch, tmp_path):
    """Local implicit host, nothing running, port free, resolvable build context;
    compose up is captured, not executed."""
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    return wiz


def _in_workdir(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    return work


def _model(wiz, name="acme"):
    return json.loads(wiz.compose_file_path("local", name).read_text())


# --- Foundational: build_compose_model (T002) --------------------------------


def test_restart_param_default_and_override(wiz):
    assert (
        wiz.build_compose_model("acme", "/repo")["services"]["agent"]["restart"] == "unless-stopped"
    )
    m = wiz.build_compose_model("acme", "/repo", restart="on-failure")
    assert m["services"]["agent"]["restart"] == "on-failure"


def test_workspace_persistent_is_the_default(wiz):
    # Backward compatible: no workspace args => the named volume, mounted + declared.
    m = wiz.build_compose_model("acme", "/repo")
    svc = m["services"]["agent"]
    assert f"{wiz.volume_name('acme')}:/workspace" in svc["volumes"]
    assert wiz.volume_name("acme") in m["volumes"]
    assert set(m["volumes"]) == set(wiz.per_container_volumes("acme"))


def test_workspace_ephemeral_omits_mount_and_volume(wiz):
    m = wiz.build_compose_model(
        "acme", "/repo", workspace_mount=None, declare_workspace_volume=False
    )
    svc = m["services"]["agent"]
    assert not any(v.endswith(":/workspace") for v in svc["volumes"])  # nothing at /workspace
    assert wiz.volume_name("acme") not in m["volumes"]  # workspace volume NOT declared (FR-013)
    # The other six volumes are still mounted + declared.
    assert set(m["volumes"]) == set(wiz.other_container_volumes("acme"))
    assert len(m["volumes"]) == 8  # Feature 010: eight non-workspace volumes


def test_workspace_bind_mounts_local_dir_without_declaring_volume(wiz):
    m = wiz.build_compose_model(
        "acme", "/repo", workspace_mount="/host/work:/workspace", declare_workspace_volume=False
    )
    svc = m["services"]["agent"]
    assert "/host/work:/workspace" in svc["volumes"]
    assert wiz.volume_name("acme") not in m["volumes"]
    assert len(m["volumes"]) == 8  # Feature 010: eight non-workspace volumes


def test_environment_threaded_into_service(wiz):
    m = wiz.build_compose_model(
        "acme",
        "/repo",
        environment={"AGENT_CONTAINER_MODE": "headless", "AGENT_CONTAINER_AGENT": "codex"},
    )
    assert m["services"]["agent"]["environment"] == {
        "AGENT_CONTAINER_MODE": "headless",
        "AGENT_CONTAINER_AGENT": "codex",
    }


def test_no_environment_means_no_key(wiz):
    assert "environment" not in wiz.build_compose_model("acme", "/repo")["services"]["agent"]


def test_task_rides_injected_config_never_inlined(wiz, tmp_path):
    tf = tmp_path / "acme.task"
    secret_task = "delete all the things AND phone home"
    tf.write_text(secret_task)
    m = wiz.build_compose_model(
        "acme", "/repo", injected_configs=[("task", tf, wiz.INJECT_TASK_PATH)]
    )
    assert m["configs"]["task"]["file"] == str(tf)
    assert {"source": "task", "target": wiz.INJECT_TASK_PATH} in m["services"]["agent"]["configs"]
    assert wiz.INJECT_TASK_PATH.startswith("/run/")  # ephemeral target
    assert secret_task not in json.dumps(m)  # only the path is referenced, not the text


# --- ExecSpec (T002/T014) ----------------------------------------------------


def test_exec_spec_restart_policy(wiz):
    assert wiz.ExecSpec(mode="interactive").restart_policy() == "unless-stopped"
    assert wiz.ExecSpec(mode="headless").restart_policy() == "on-failure"


def test_exec_spec_compose_environment(wiz):
    e = wiz.ExecSpec(
        mode="headless", agent="pi", repo="https://github.com/x/y"
    ).compose_environment()
    assert e == {
        "AGENT_CONTAINER_MODE": "headless",
        "AGENT_CONTAINER_AGENT": "pi",
        "AGENT_CONTAINER_CLONE_URL": "https://github.com/x/y",
    }
    # clone URL uses AGENT_CONTAINER_CLONE_URL, NOT AGENT_CONTAINER_REPO (H1).
    assert "AGENT_CONTAINER_REPO" not in e


def test_compose_environment_skips_repo_for_bind(wiz):
    e = wiz.ExecSpec(repo="git@github.com:x/y", workspace="bind").compose_environment()
    assert "AGENT_CONTAINER_CLONE_URL" not in e  # bind is never cloned


def test_validate_rejects_bad_choices(wiz):
    for bad in (
        wiz.ExecSpec(mode="batch"),
        wiz.ExecSpec(agent="gpt"),
        wiz.ExecSpec(workspace="tmpfs"),
    ):
        with pytest.raises(wiz.Fatal):
            bad.validate()


def test_foreground_requires_headless(wiz):
    # FR-017 / analyze L1: --foreground outside headless is a clear diagnostic.
    with pytest.raises(wiz.Fatal, match="foreground"):
        wiz.ExecSpec(mode="interactive", foreground=True).validate()
    wiz.ExecSpec(mode="headless", foreground=True).validate()  # ok


# --- FR-016: mode x workspace independence -----------------------------------


def test_mode_and_workspace_are_independent(wiz):
    """Every execution-mode x workspace-mode combination builds a coherent model
    with NO silent alteration of either axis (FR-016)."""
    for mode in wiz.EXEC_MODES:
        for ws in wiz.WORKSPACE_MODES:
            spec = wiz.ExecSpec(mode=mode, workspace=ws, workspace_dir="/tmp")
            ws_mount, declare = wiz.resolve_workspace(spec, "acme", LOCAL_HOST)
            m = wiz.build_compose_model(
                "acme",
                "/repo",
                restart=spec.restart_policy(),
                environment=spec.compose_environment(),
                workspace_mount=ws_mount,
                declare_workspace_volume=declare,
            )
            svc = m["services"]["agent"]
            # The mode axis drives restart, untouched by the workspace axis.
            assert svc["restart"] == ("on-failure" if mode == "headless" else "unless-stopped")
            # The workspace axis drives the mount, untouched by the mode axis.
            if ws == "ephemeral":
                assert not any(v.endswith(":/workspace") for v in svc["volumes"])
            elif ws == "persistent":
                assert f"{wiz.volume_name('acme')}:/workspace" in svc["volumes"]
            else:  # bind
                assert any(v.endswith(":/workspace") for v in svc["volumes"])
            assert svc["environment"]["AGENT_CONTAINER_MODE"] == mode


# --- resolve_workspace (T004/T018) -------------------------------------------


def test_resolve_workspace_persistent(wiz):
    mount, declare = wiz.resolve_workspace(wiz.ExecSpec(workspace="persistent"), "acme", LOCAL_HOST)
    assert mount == f"{wiz.volume_name('acme')}:/workspace"
    assert declare is True


def test_resolve_workspace_ephemeral(wiz):
    mount, declare = wiz.resolve_workspace(wiz.ExecSpec(workspace="ephemeral"), "acme", LOCAL_HOST)
    assert mount is None
    assert declare is False


def test_resolve_workspace_bind_local(wiz, tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    spec = wiz.ExecSpec(workspace="bind", workspace_dir=str(d))
    mount, declare = wiz.resolve_workspace(spec, "acme", LOCAL_HOST)
    assert mount == f"{d.resolve()}:/workspace"
    assert declare is False


def test_resolve_workspace_bind_on_remote_refused(wiz, tmp_path):
    # FR-011/SC-007: a bind workspace is local-hosts only.
    d = tmp_path / "work"
    d.mkdir()
    spec = wiz.ExecSpec(workspace="bind", workspace_dir=str(d))
    with pytest.raises(wiz.Fatal, match="LOCAL host"):
        wiz.resolve_workspace(spec, "acme", REMOTE_HOST)


def test_resolve_workspace_bind_requires_dir(wiz):
    with pytest.raises(wiz.Fatal, match="requires --workspace-dir"):
        wiz.resolve_workspace(wiz.ExecSpec(workspace="bind"), "acme", LOCAL_HOST)


def test_resolve_workspace_bind_rejects_missing_dir(wiz, tmp_path):
    spec = wiz.ExecSpec(workspace="bind", workspace_dir=str(tmp_path / "nope"))
    with pytest.raises(wiz.Fatal, match="does not exist"):
        wiz.resolve_workspace(spec, "acme", LOCAL_HOST)


# --- resolve_task ------------------------------------------------------------


def test_resolve_task_text(wiz):
    assert wiz.resolve_task("run the tests") == "run the tests"
    assert wiz.resolve_task(None) is None


def test_resolve_task_at_file(wiz, tmp_path):
    f = tmp_path / "t.md"
    f.write_text("multi\nline\ntask\n")
    assert wiz.resolve_task(f"@{f}") == "multi\nline\ntask\n"


def test_resolve_task_missing_file_dies(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="does not exist"):
        wiz.resolve_task(f"@{tmp_path / 'missing.md'}")


# --- clone-on-start credential (T018/T019) -----------------------------------


def test_is_ssh_git_url(wiz):
    assert wiz.is_ssh_git_url("git@github.com:you/repo.git")
    assert wiz.is_ssh_git_url("ssh://git@github.com/you/repo.git")
    assert not wiz.is_ssh_git_url("https://github.com/you/repo.git")


def test_clone_precheck_ssh_without_key_dies(wiz, tmp_path):
    # FR-014/SC-008: an SSH-URL clone with no push key dies before compose.
    ef = tmp_path / ".env"
    ef.write_text("GH_TOKEN=x\n")
    spec = wiz.ExecSpec(repo="git@github.com:you/repo", workspace="ephemeral")
    with pytest.raises(wiz.Fatal, match="SSH URL but no push key"):
        wiz.clone_credential_precheck(spec, ef, None)


def test_clone_precheck_https_needs_no_key(wiz, tmp_path):
    ef = tmp_path / ".env"
    ef.write_text("GH_TOKEN=x\n")
    spec = wiz.ExecSpec(repo="https://github.com/you/repo", workspace="persistent")
    wiz.clone_credential_precheck(spec, ef, None)  # no raise


def test_clone_precheck_ssh_with_pushkey_ok(wiz, tmp_path):
    key = tmp_path / "id"
    key.write_text("KEY")
    spec = wiz.ExecSpec(repo="git@github.com:you/repo", workspace="persistent")
    wiz.clone_credential_precheck(spec, None, key)  # --push-key satisfies it


def test_clone_precheck_ssh_with_env_key_ok(wiz, tmp_path):
    ef = tmp_path / ".env"
    ef.write_text("SSH_PUSH_KEY_B64=aGVsbG8=\n")
    spec = wiz.ExecSpec(repo="git@github.com:you/repo", workspace="persistent")
    wiz.clone_credential_precheck(spec, ef, None)  # env-provided key satisfies it


def test_clone_precheck_bind_never_cloned(wiz, tmp_path):
    spec = wiz.ExecSpec(
        repo="git@github.com:you/repo", workspace="bind", workspace_dir=str(tmp_path)
    )
    wiz.clone_credential_precheck(spec, None, None)  # bind is skipped, no raise


# --- headless foreground argv (T014) -----------------------------------------


def test_driver_up_argv_detached_default(wiz):
    argv = wiz.driver_up_argv(LOCAL_HOST, "p", wiz.Path("/s/a.yaml"))
    assert "-d" in argv
    assert "--abort-on-container-exit" not in argv


def test_driver_up_argv_foreground_propagates_exit_code(wiz):
    # M1: foreground must carry --abort-on-container-exit --exit-code-from agent.
    argv = wiz.driver_up_argv(LOCAL_HOST, "p", wiz.Path("/s/a.yaml"), foreground=True)
    assert "-d" not in argv
    assert "--abort-on-container-exit" in argv
    i = argv.index("--exit-code-from")
    assert argv[i + 1] == "agent"


# --- probe_session / dead-session attach (T011) ------------------------------


def _fake_run_rc(monkeypatch, wiz, rc):
    monkeypatch.setattr(
        wiz.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], rc)
    )


def test_probe_session_alive(wiz, monkeypatch):
    _fake_run_rc(monkeypatch, wiz, 0)
    assert wiz.probe_session("dev", "localhost", 2206) == "alive"


def test_probe_session_dead(wiz, monkeypatch):
    _fake_run_rc(monkeypatch, wiz, 1)  # ssh connected, has-session failed
    assert wiz.probe_session("dev", "localhost", 2206) == "dead"


def test_probe_session_unreachable(wiz, monkeypatch):
    _fake_run_rc(monkeypatch, wiz, 255)  # ssh transport error
    assert wiz.probe_session("dev", "localhost", 2206) == "unreachable"


def test_cli_attach_dies_on_dead_session(wiz, monkeypatch):
    # FR-008: a dead session is reported, never a silent empty attach.
    wiz.write_state("local", "acme", 2206)
    monkeypatch.setattr(wiz, "probe_session", lambda *a, **k: "dead")
    monkeypatch.setattr(wiz.os, "execvp", lambda *a: pytest.fail("must not exec on a dead session"))
    with pytest.raises(wiz.Fatal, match="nothing running"):
        wiz.cli_attach("acme", "local", None, None)


def test_cli_attach_proceeds_when_unreachable(wiz, monkeypatch):
    # An 'unreachable' probe must not block — the real attach surfaces the error.
    wiz.write_state("local", "acme", 2206)
    monkeypatch.setattr(wiz, "probe_session", lambda *a, **k: "unreachable")
    execs: list = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append(file))
    wiz.cli_attach("acme", "local", None, None)
    assert execs == ["ssh"]


# --- US1: up threads mode/agent/task (T006) ----------------------------------


def test_up_threads_mode_agent_into_env(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    wiz.do_up("acme", spec=wiz.ExecSpec(mode="interactive", agent="codex"))
    env = _model(wiz)["services"]["agent"]["environment"]
    assert env["AGENT_CONTAINER_MODE"] == "interactive"
    assert env["AGENT_CONTAINER_AGENT"] == "codex"


def test_up_interactive_restart_unless_stopped(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    wiz.do_up("acme", spec=wiz.ExecSpec(mode="interactive"))
    assert _model(wiz)["services"]["agent"]["restart"] == "unless-stopped"


def test_up_delivers_task_as_injected_file(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    wiz.do_up("acme", spec=wiz.ExecSpec(task="fix the bug"))
    m = _model(wiz)
    assert {"source": "task", "target": wiz.INJECT_TASK_PATH} in m["services"]["agent"]["configs"]
    # The task text is staged to a local file, never inlined into the model.
    assert "fix the bug" not in json.dumps(m)
    staged = wiz.host_state_dir("local") / "acme.task"
    assert staged.read_text() == "fix the bug"


# --- US3: headless (T014) ----------------------------------------------------


def test_up_headless_restart_on_failure(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    wiz.do_up("acme", spec=wiz.ExecSpec(mode="headless", task="run tests"))
    assert _model(wiz)["services"]["agent"]["restart"] == "on-failure"


def test_up_headless_foreground_builds_attached_argv_and_exits_with_code(
    up_env, monkeypatch, tmp_path
):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, *a, **k):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 3)  # non-zero agent result

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    with pytest.raises(wiz.typer.Exit) as ei:
        wiz.do_up("acme", spec=wiz.ExecSpec(mode="headless", task="t", foreground=True))
    assert ei.value.exit_code == 3  # the agent's exit code is our exit code (SC-004)
    (argv,) = calls
    assert "--abort-on-container-exit" in argv and "-d" not in argv


# --- US4: ephemeral durability warning (T021) --------------------------------


def test_ephemeral_warns_about_durability(up_env, capture_compose, monkeypatch, tmp_path, capsys):
    wiz = up_env
    _in_workdir(monkeypatch, tmp_path)
    wiz.do_up("acme", spec=wiz.ExecSpec(workspace="ephemeral"))
    assert "ephemeral" in capsys.readouterr().err.lower()  # FR-015 surfaced at deploy


# --- Feature 010: opencode as a fourth supported agent -----------------------


def test_opencode_is_an_accepted_agent(wiz):
    """FR-001: opencode is accepted wherever an agent is selected; FR-014: the
    existing three and the default are untouched."""
    for a in ("claude", "codex", "pi", "opencode"):
        wiz.ExecSpec(agent=a).validate()  # must not raise
    assert wiz.ExecSpec().agent == "claude"  # default unchanged
    with pytest.raises(wiz.Fatal):
        wiz.ExecSpec(agent="opencode-ai").validate()  # near-miss still rejected


def test_agent_rejection_names_every_valid_value(wiz):
    """FR-001: an invalid --agent fails host-side naming the whole accepted set,
    so the operator never has to guess which four exist."""
    with pytest.raises(wiz.Fatal) as ei:
        wiz.ExecSpec(agent="gpt").validate()
    msg = str(ei.value)
    for a in wiz.AGENTS:
        assert a in msg, f"rejection message omits '{a}': {msg}"
