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
from pathlib import Path

import pytest

# Feature 018: a pinned key for tests that attach. Any valid ed25519 public key
# works — nothing here verifies against a real container.
TEST_HOST_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample0000000000000000000000000000000="


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
    monkeypatch.setattr(wiz, "resolve_build_context", lambda *a, **k: tmp_path / "repo")
    return wiz


def _in_workdir(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    # Feature 011: a project keeps its env file in the project config directory.
    # The bare ./.env is no longer read (FR-001b).
    (work / ".agent-container").mkdir(exist_ok=True)
    (work / ".agent-container" / ".env").write_text("TOKEN=x\n")
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
    # The other nine volumes are still mounted + declared — including runs, which is
    # why Feature 016 gave the record its own volume: an ephemeral run declares no
    # workspace volume, and is exactly the run whose record most needs to survive.
    assert set(m["volumes"]) == set(wiz.other_container_volumes("acme"))
    assert len(m["volumes"]) == 9  # nine non-workspace volumes (016 added runs)


def test_workspace_bind_mounts_local_dir_without_declaring_volume(wiz):
    m = wiz.build_compose_model(
        "acme", "/repo", workspace_mount="/host/work:/workspace", declare_workspace_volume=False
    )
    svc = m["services"]["agent"]
    assert "/host/work:/workspace" in svc["volumes"]
    assert wiz.volume_name("acme") not in m["volumes"]
    assert len(m["volumes"]) == 9  # nine non-workspace volumes (016 added runs)


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


def test_task_rides_an_inline_config_to_an_ephemeral_target(wiz, tmp_path):
    """The task is delivered INLINE, and that is consistent rather than a relaxation.

    This asserted the text was referenced by path and never inlined. Two things make
    the inversion right. A `file:` config is a bind resolved daemon-side and cannot
    reach a daemon that shares no filesystem (measured, Feature 020) — so a path
    reference is a remote-deploy failure. And a task is NOT a credential: Feature 017
    settled that explicitly, and the tool EXPORTS task text to a telemetry collector
    by default, which would be indefensible if the text were secret.

    Constitution IX draws the line at secrets, not at everything an operator typed.
    The ephemeral /run target is unchanged.
    """
    task = "delete all the things AND phone home"
    m = wiz.build_compose_model(
        "acme", "/repo", injected_configs=[("task", task, wiz.INJECT_TASK_PATH)]
    )
    assert m["configs"]["task"] == {"content": task}
    assert "file" not in m["configs"]["task"]
    assert {"source": "task", "target": wiz.INJECT_TASK_PATH} in m["services"]["agent"]["configs"]
    assert wiz.INJECT_TASK_PATH.startswith("/run/")  # ephemeral target


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
        # Feature 017: always present, so `redeploy` can read the role back off a
        # running container rather than defaulting it.
        "AGENT_CONTAINER_ROLE": "agent",
        # FR-009f: an EXPLICIT value, not presence-signalled. An absent variable
        # is indistinguishable from a deploy predating the switch, and this is a
        # field whose exposure the operator chose.
        "AGENT_CONTAINER_EXPORT_TASK": "1",
    }
    # No endpoint declared in this test's environment, so no endpoint is
    # delivered — undeclared is not the same as declared-empty (C18c).
    assert "AGENT_CONTAINER_OTLP_ENDPOINT" not in e
    # clone URL uses AGENT_CONTAINER_CLONE_URL, NOT AGENT_CONTAINER_REPO (H1).
    assert "AGENT_CONTAINER_REPO" not in e
    # The control plane's own NAME is set only for that role, and only when the
    # caller passes one — `panic` self-exclusion and nested provenance both read
    # it, and neither can derive it from inside the container.
    assert "AGENT_CONTAINER_CONTROL_PLANE_NAME" not in e
    cp = wiz.ExecSpec(role=wiz.ROLE_CONTROL_PLANE).compose_environment("hub")
    assert cp["AGENT_CONTAINER_CONTROL_PLANE_NAME"] == "hub"
    assert cp["AGENT_CONTAINER_ROLE"] == "control-plane"


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
            # Matched on the mount TARGET rather than on the whole string: a bind
            # carries `:ro` (the container does not write to the operator's home),
            # so an `endswith(":/workspace")` check silently stopped seeing it —
            # and the ephemeral arm's negative form would have kept passing while
            # having stopped looking, which is the worse half of that failure.
            def _at_workspace(v: str) -> bool:
                parts = v.split(":")
                return len(parts) > 1 and parts[1] == "/workspace"

            if ws == "ephemeral":
                assert not any(_at_workspace(v) for v in svc["volumes"])
            elif ws == "persistent":
                assert f"{wiz.volume_name('acme')}:/workspace" in svc["volumes"]
            else:  # bind
                assert any(_at_workspace(v) for v in svc["volumes"])
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
    # READ-ONLY: a bind workspace is the operator's own directory shown to the
    # agent, and the container does not write to the operator's home. Writable
    # state is what the `persistent` mode's VOLUME is for.
    assert mount == f"{d.resolve()}:/workspace:ro"
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


def test_clone_on_start_over_ssh_is_two_phase_not_a_precheck(wiz):
    """Feature 019 (FR-013) INVERTED `clone_credential_precheck`'s premise.

    That function refused to start when `--repo` was an SSH URL and no push key was
    supplied. The key is now generated INSIDE the container, so on a first boot it
    cannot be registered yet and no precheck could ever pass — refusing would leave
    the operator with no container to read the key from.

    These five tests covered the precheck's branches. What replaces them is the
    assertion that the precheck is GONE, plus the two-phase behaviour it became: the
    entrypoint records the clone as pending rather than dying, and the CLI exits with
    a distinct code.
    """
    assert not hasattr(wiz, "clone_credential_precheck")
    assert wiz.EXIT_PENDING_REGISTRATION == 3


def test_the_pending_exit_code_is_distinct_from_failure_and_refusal(wiz):
    """An automated caller must be able to tell "started, needs a key registered" from
    "broken" WITHOUT parsing prose — it is the difference between registering a key and
    tearing the environment down, and tearing it down destroys the key."""
    assert wiz.EXIT_PENDING_REGISTRATION not in (wiz.EXIT_OK, wiz.EXIT_FAILURE, wiz.EXIT_REFUSED)


def test_the_entrypoint_records_a_pending_clone_instead_of_dying(wiz):
    """The half that makes the exit code survivable: dying on a first boot would leave
    no container to read the public key from, so the operator could never register it.

    The slice ends at the case arm's `;;` rather than after a fixed character count:
    a fixed window silently shrinks the assertion every time the branch grows, and
    twice already it pushed a line being asserted out of view — a check that fails for
    a reason unrelated to what it is checking."""
    entry = (Path(wiz.__file__).parents[1] / "image" / "entrypoint.sh").read_text()
    i = entry.index("clone-on-start: cloning via SSH")
    block = entry[i : entry.index("\n                ;;", i)]
    assert ".clone_pending" in block
    assert ".clone_done" in block  # both outcomes marked, or the CLI cannot tell
    assert "Do NOT tear this environment down" in block
    # A BARE redeploy, deliberately: it inherits the clone URL. This assertion pinned
    # `--repo ${CLONE_URL}` for exactly one commit, when the message worked around a
    # redeploy that silently unset the URL. Fixing redeploy made the workaround the
    # wrong contract to pin.
    assert "redeploy <name>" in block
    assert "--repo" not in block


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
    # Feature 018: attach verifies, so these tests must start from a PINNED
    # environment — they exercise handover/window/probe, not the unpinned path
    # (which test_shell_integration.py owns).
    wiz.pin_host_key("local", "localhost", 2206, TEST_HOST_PUBKEY)
    monkeypatch.setattr(wiz, "probe_session", lambda *a, **k: "dead")
    monkeypatch.setattr(wiz.os, "execvp", lambda *a: pytest.fail("must not exec on a dead session"))
    with pytest.raises(wiz.Fatal, match="nothing running"):
        wiz.cli_attach("acme", "local", None, None)


def test_cli_attach_proceeds_when_unreachable(wiz, monkeypatch):
    # An 'unreachable' probe must not block — the real attach surfaces the error.
    wiz.write_state("local", "acme", 2206)
    # Feature 018: attach verifies, so these tests must start from a PINNED
    # environment — they exercise handover/window/probe, not the unpinned path
    # (which test_shell_integration.py owns).
    wiz.pin_host_key("local", "localhost", 2206, TEST_HOST_PUBKEY)
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
    # Inline, and NO local file staged: a staged path is a bind the daemon may not be
    # able to resolve. A task is not a credential (Feature 017), so inlining it is
    # within Constitution IX rather than an exception to it.
    assert m["configs"]["task"] == {"content": "fix the bug"}
    assert not (wiz.host_state_dir("local") / "acme.task").exists()


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
    compose_argv = next(a for a in calls if "--abort-on-container-exit" in a)
    assert "-d" not in compose_argv
    # The exit code is now read FROM THE CONTAINER, so the container is asked. This
    # stub returns no stdout, which exercises the FALLBACK arm — compose's own
    # status, i.e. exactly the behaviour this test pinned before.
    assert any("inspect" in a for a in calls), "the container was never asked"


def test_the_agent_exit_code_comes_from_the_container_not_from_compose(wiz, monkeypatch):
    """SC-004 must survive compose failing to propagate it.

    `--exit-code-from` requires compose to still be following the log stream when
    the workload exits. Under podman a fast-exiting agent wins that race: the
    follow request is cancelled and compose reports 1 for a run that exited 0.
    Measured at 5 failures in 6 consecutive isolated runs of the concurrent-records
    acceptance test before this changed. The container recorded the truth, so the
    container is what we ask.
    """
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(
        wiz, "query", lambda *_a, **_k: subprocess.CompletedProcess([], 0, "0\n", "")
    )
    # compose said 1; the container says 0. The container wins.
    assert wiz.agent_exit_code({}, "acme", fallback=1) == 0


def test_an_unreadable_container_falls_back_to_composes_status(wiz, monkeypatch):
    """A finished run must not become a tool error because the container vanished."""
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(
        wiz, "query", lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", "no such object")
    )
    assert wiz.agent_exit_code({}, "acme", fallback=3) == 3
    monkeypatch.setattr(
        wiz, "query", lambda *_a, **_k: subprocess.CompletedProcess([], 0, "not-a-number", "")
    )
    assert wiz.agent_exit_code({}, "acme", fallback=3) == 3


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
