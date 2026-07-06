"""Command-construction tests: assert the exact argv the wizard would hand to
the container runtime and to ssh, WITHOUT docker/podman/ssh being present.
subprocess/exec entry points are captured, never executed.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture
def capture_query(wiz, monkeypatch):
    """Replace wiz.query with a recorder returning success."""
    calls: list[list[str]] = []

    def fake_query(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(wiz, "query", fake_query)
    return calls


# --- container start argv -------------------------------------------------------


def make_env_file(tmp_path, secret="hunter2-super-secret"):
    env_file = tmp_path / "acme.env"
    env_file.write_text(f"GITHUB_TOKEN={secret}\nGIT_AUTHOR_NAME=Agent\n")
    return env_file, secret


def test_launch_container_argv_flag_for_flag(wiz, capture_query, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    env_file, _ = make_env_file(tmp_path)

    wiz.launch_container("podman", "acme", env_file)

    # Seven per-container named volumes in the canonical order, then --restart.
    # This argv is the load-bearing container start command; pin it exactly.
    # Container-side port is 2222 (rootless sshd runs as dev, cannot bind 22).
    assert capture_query == [[
        "podman", "run", "-d",
        "--name", "agent-container-acme",
        "--env-file", str(env_file),
        "-p", "2206:2222",
        "-v", "agent-container-acme-workspace:/workspace",
        "-v", "agent-container-acme-claude:/home/dev/.claude",
        "-v", "agent-container-acme-codex:/home/dev/.codex",
        "-v", "agent-container-acme-pi:/home/dev/.pi",
        "-v", "agent-container-acme-shellenv:/home/dev/.agent-container",
        "-v", "agent-container-acme-tmux:/home/dev/.config/tmux",
        "-v", "agent-container-acme-ssh:/home/dev/.ssh",
        "--restart", "unless-stopped",
        "localhost/agent-container:latest",
    ]]
    # state file written (the completions and `attach` read it)
    assert wiz.read_state_port("acme") == "2206"


def test_launch_container_appends_binds_after_volumes(wiz, capture_query, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    env_file, _ = make_env_file(tmp_path)

    wiz.launch_container(
        "podman", "acme", env_file,
        ["/abs/host:/opt/data", "/another:/workspace/another"],
    )

    (argv,) = capture_query
    # Binds land immediately after the five standard volumes, before --restart.
    ri = argv.index("--restart")
    assert argv[ri - 4:ri] == [
        "-v", "/abs/host:/opt/data",
        "-v", "/another:/workspace/another",
    ]
    assert argv[ri:] == ["--restart", "unless-stopped", "localhost/agent-container:latest"]
    # First -v is still the workspace volume.
    assert argv[argv.index("-v") + 1] == "agent-container-acme-workspace:/workspace"


# --- bind-mount resolution (--mount) -----------------------------------------


def test_resolve_bind_mount_default_container_path(wiz, tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    assert wiz.resolve_bind_mount(str(d)) == f"{d.resolve()}:/workspace/proj"


def test_resolve_bind_mount_explicit_container_path(wiz, tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    assert wiz.resolve_bind_mount(f"{d}:/opt/data") == f"{d.resolve()}:/opt/data"


def test_resolve_bind_mount_rejects_missing_dir(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="does not exist or is not a directory"):
        wiz.resolve_bind_mount(str(tmp_path / "nope"))


def test_resolve_bind_mount_rejects_relative_container_path(wiz, tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    with pytest.raises(wiz.Fatal, match="must be absolute"):
        wiz.resolve_bind_mount(f"{d}:relative/path")


def test_resolve_bind_mount_rejects_file(wiz, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(wiz.Fatal, match="is not a directory"):
        wiz.resolve_bind_mount(str(f))


def test_resolve_bind_mount_makes_relative_host_absolute(wiz, tmp_path, monkeypatch):
    # A relative host dir must become absolute (would fail if .resolve() dropped).
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path)
    assert wiz.resolve_bind_mount("proj") == f"{(tmp_path / 'proj').resolve()}:/workspace/proj"


def test_resolve_bind_mount_dereferences_symlinked_host(wiz, tmp_path):
    # The load-bearing pwd -P / Path.resolve() behavior: a symlinked host dir
    # resolves to its real target, and the container basename follows the target.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert wiz.resolve_bind_mount(str(link)) == f"{real.resolve()}:/workspace/real"


def test_launch_container_never_inlines_secrets(wiz, capture_query, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    env_file, secret = make_env_file(tmp_path)

    wiz.launch_container("docker", "acme", env_file)

    (argv,) = capture_query
    joined = "\x00".join(argv)
    assert secret not in joined
    assert "GITHUB_TOKEN" not in joined
    assert "-e" not in argv and "--env" not in argv  # only --env-file is allowed
    assert "--env-file" in argv
    assert argv[argv.index("--env-file") + 1] == str(env_file)


def test_launch_container_port_is_name_hash(wiz, capture_query, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    env_file, _ = make_env_file(tmp_path)
    wiz.launch_container("podman", "my-box", env_file)
    (argv,) = capture_query
    assert argv[argv.index("-p") + 1] == "2204:2222"
    assert argv[argv.index("-v") + 1] == "agent-container-my-box-workspace:/workspace"


def test_launch_container_aborts_on_busy_port(wiz, capture_query, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: False)
    env_file, _ = make_env_file(tmp_path)
    with pytest.raises(wiz.Fatal, match="port 2206 is already in use"):
        wiz.launch_container("podman", "acme", env_file)
    assert capture_query == []  # no `run` attempted
    assert wiz.read_state_port("acme") is None  # no state written


def test_launch_container_failed_run_writes_no_state(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(
        wiz, "query",
        lambda argv: subprocess.CompletedProcess(argv, 125, stdout="", stderr="boom"),
    )
    env_file, _ = make_env_file(tmp_path)
    with pytest.raises(wiz.Fatal, match="run failed"):
        wiz.launch_container("podman", "acme", env_file)
    assert wiz.read_state_port("acme") is None


# --- do_up orchestration (no runtime calls beyond the mocks) ----------------------


@pytest.fixture
def up_env(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "container_running", lambda rt, cname: False)
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: False)
    monkeypatch.setattr(wiz, "image_exists", lambda rt, tag: True)
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    return wiz


def test_do_up_resolves_env_file_and_runs(up_env, capture_query, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    wiz.do_up("acme")
    (argv,) = capture_query
    assert argv[argv.index("--env-file") + 1] == str(work / ".env")


def test_do_up_threads_mounts_through_to_argv(up_env, capture_query, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("TOKEN=x\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(work)
    wiz.do_up("acme", mounts=[str(proj)])
    (argv,) = capture_query
    assert "-v" in argv and f"{proj.resolve()}:/workspace/proj" in argv


def test_do_up_rejects_bad_mount_before_any_runtime_call(up_env, capture_query, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    with pytest.raises(wiz.Fatal, match="does not exist or is not a directory"):
        wiz.do_up("acme", mounts=[str(tmp_path / "missing")])
    assert capture_query == []


def test_do_up_dies_without_env_file(up_env, capture_query, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    with pytest.raises(wiz.Fatal, match="no .env found"):
        wiz.do_up("acme")
    assert capture_query == []


def test_do_up_noop_when_already_running(up_env, capture_query, monkeypatch):
    wiz = up_env
    monkeypatch.setattr(wiz, "container_running", lambda rt, cname: True)
    wiz.do_up("acme")  # logs and returns
    assert capture_query == []


def test_do_up_dies_on_stopped_leftover(up_env, monkeypatch):
    wiz = up_env
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: True)
    with pytest.raises(wiz.Fatal, match="exists but is not running"):
        wiz.do_up("acme")


def test_do_up_dies_when_image_missing(up_env, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    monkeypatch.setattr(wiz, "image_exists", lambda rt, tag: False)
    with pytest.raises(wiz.Fatal, match="image .* not found"):
        wiz.do_up("acme")


def test_do_up_rejects_invalid_name_before_any_runtime_call(up_env, capture_query):
    wiz = up_env
    with pytest.raises(wiz.Fatal, match="invalid <name>"):
        wiz.do_up("Bad Name")
    assert capture_query == []


# --- down / purge volume removal ----------------------------------------------------


def test_down_purge_removes_all_seven_volumes(wiz, capture_query, monkeypatch):
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: False)
    wiz.write_state("acme", 2206)
    wiz.down_container("podman", "acme", purge=True)
    removed = [c[3] for c in capture_query if c[:3] == ["podman", "volume", "rm"]]
    assert removed == [
        "agent-container-acme-workspace",
        "agent-container-acme-claude",
        "agent-container-acme-codex",
        "agent-container-acme-pi",
        "agent-container-acme-shellenv",
        "agent-container-acme-tmux",
        "agent-container-acme-ssh",
    ]
    assert wiz.read_state_port("acme") is None  # state cleared


def test_down_without_purge_removes_no_volumes(wiz, capture_query, monkeypatch):
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: True)
    wiz.down_container("podman", "acme", purge=False)
    assert not any(c[:3] == ["podman", "volume", "rm"] for c in capture_query)


# --- attach argv -------------------------------------------------------------------


def test_ssh_argv_is_the_canonical_attach_command(wiz):
    assert wiz.ssh_argv("dev", "localhost", 2206) == [
        "ssh", "dev@localhost", "-p", "2206", "-t", "tmux", "attach", "-t", "main",
    ]
    # port may arrive as str (state file / hosts.conf) — same argv either way
    assert wiz.ssh_argv("dev", "vps.example.com", "2299") == [
        "ssh", "dev@vps.example.com", "-p", "2299", "-t", "tmux", "attach", "-t", "main",
    ]


def test_cli_attach_execs_ssh_with_full_handover(wiz, monkeypatch):
    wiz.write_state("acme", 2206)
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, list(argv))))
    wiz.cli_attach("acme", "local", None, None)
    assert execs == [
        ("ssh", ["ssh", "dev@localhost", "-p", "2206", "-t", "tmux", "attach", "-t", "main"]),
    ]


# --- attach --window ---------------------------------------------------------------


def test_ssh_argv_with_window_selects_then_attaches_single_arg(wiz):
    argv = wiz.ssh_argv("dev", "localhost", 2206, "agents")
    # Prefix unchanged; the remote command is ONE compound string (select then attach).
    assert argv[:5] == ["ssh", "dev@localhost", "-p", "2206", "-t"]
    assert argv[5:] == [
        "tmux select-window -t main:agents 2>/dev/null; exec tmux attach -t main"
    ]
    assert len(argv) == 6  # -t is followed by exactly one remote-command arg


def test_ssh_argv_without_window_is_unchanged(wiz):
    # Parity guard: the no-window argv must never gain the compound form.
    assert wiz.ssh_argv("dev", "localhost", 2206) == [
        "ssh", "dev@localhost", "-p", "2206", "-t", "tmux", "attach", "-t", "main",
    ]


def test_cli_attach_window_execs_compound_remote_command(wiz, monkeypatch):
    wiz.write_state("acme", 2206)
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, list(argv))))
    wiz.cli_attach("acme", "local", None, None, "edit")
    assert execs == [(
        "ssh",
        ["ssh", "dev@localhost", "-p", "2206", "-t",
         "tmux select-window -t main:edit 2>/dev/null; exec tmux attach -t main"],
    )]


def test_cli_attach_rejects_bad_window_before_exec(wiz, monkeypatch):
    wiz.write_state("acme", 2206)
    execs: list = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, argv)))
    with pytest.raises(wiz.Fatal, match="invalid tmux window"):
        wiz.cli_attach("acme", "local", None, None, "a; rm -rf ~")
    assert execs == []  # never reached ssh


# --- attach target resolution --------------------------------------------------------


def write_hosts(wiz, text):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text(text)


def test_resolve_local_from_state_file(wiz):
    wiz.write_state("acme", 2206)
    assert wiz.resolve_attach_target("acme", "local") == ("dev", "localhost", "2206", "local")


def test_resolve_local_honours_agent_container_host_and_user(wiz, monkeypatch):
    wiz.write_state("acme", 2206)
    monkeypatch.setenv("AGENT_CONTAINER_HOST", "lima-vm")
    monkeypatch.setenv("AGENT_CONTAINER_USER", "ops")
    assert wiz.resolve_attach_target("acme", "local") == ("ops", "lima-vm", "2206", "local")


def test_resolve_remote_from_hosts_conf(wiz):
    write_hosts(wiz, "MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2204\n")
    assert wiz.resolve_attach_target("my-box", "remote") == (
        "dev", "vps.example.com", "2204", "remote",
    )


def test_resolve_auto_prefers_remote_over_local_state(wiz):
    wiz.write_state("acme", 2206)
    write_hosts(wiz, "ACME_HOST=vps.example.com\nACME_PORT=2299\n")
    assert wiz.resolve_attach_target("acme", "auto") == (
        "dev", "vps.example.com", "2299", "remote",
    )


def test_resolve_auto_falls_back_to_local_state(wiz):
    wiz.write_state("acme", 2206)
    assert wiz.resolve_attach_target("acme", "auto") == ("dev", "localhost", "2206", "local")


def test_resolve_name_is_case_insensitive(wiz):
    write_hosts(wiz, "MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2204\n")
    assert wiz.resolve_attach_target("My-Box", "remote")[1] == "vps.example.com"


def test_resolve_remote_requires_hosts_conf(wiz):
    with pytest.raises(wiz.Fatal, match="no hosts config"):
        wiz.resolve_attach_target("acme", "remote")


def test_resolve_remote_requires_both_keys(wiz):
    write_hosts(wiz, "ACME_HOST=vps.example.com\n")  # _PORT missing
    with pytest.raises(wiz.Fatal, match="no host configured for acme"):
        wiz.resolve_attach_target("acme", "remote")


def test_resolve_local_without_state_dies_with_hint(wiz):
    with pytest.raises(wiz.Fatal, match="no local state for acme"):
        wiz.resolve_attach_target("acme", "local")


def test_resolve_auto_with_nothing_dies(wiz):
    with pytest.raises(wiz.Fatal, match="no attach target for acme"):
        wiz.resolve_attach_target("acme", "auto")


def test_resolve_rejects_host_option_injection(wiz):
    wiz.write_state("acme", 2206)
    with pytest.raises(wiz.Fatal, match="invalid ssh host"):
        wiz.resolve_attach_target("acme", "local", host_override="-oProxyCommand=evil")


# --- list / stale-state rows -----------------------------------------------------------


def test_gather_rows_marks_orphaned_state_files_stale(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "ps_agent_container", lambda rt, include_stopped=False: [
        ("agent-container-acme", "localhost/agent-container:latest", "Up 2 hours", "2 hours ago"),
    ])
    wiz.write_state("acme", 2206)
    wiz.write_state("ghost", 2299)
    rows = wiz.gather_rows("podman")
    by_name = {r["name"]: r for r in rows}
    assert by_name["agent-container-acme"]["port"] == "2206"
    assert by_name["agent-container-acme"]["stale"] is False
    assert by_name["agent-container-ghost"]["port"] == "2299"
    assert by_name["agent-container-ghost"]["stale"] is True
    assert by_name["agent-container-ghost"]["status"] == "stale"
