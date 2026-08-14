"""Command-construction tests: assert the exact argv/compose the CLI hands to
the container runtime and to ssh, WITHOUT docker/podman/ssh being present.
subprocess/exec entry points are captured, never executed.

Feature 001: the run mechanism is compose (generated file + `<rt> compose up`),
not imperative `docker run`; state is namespaced per host.
"""

from __future__ import annotations

import json
import subprocess

import pytest

# Feature 018: a pinned key for tests that attach. Any valid ed25519 public key
# works — nothing here verifies against a real container.
TEST_HOST_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample0000000000000000000000000000000="


@pytest.fixture
def capture_query(wiz, monkeypatch):
    """Replace wiz.query with a recorder returning success (used for ps/down)."""
    calls: list[list[str]] = []

    def fake_query(argv, timeout=None):
        # `timeout` is accepted because the real query takes it and host_ps_rows
        # passes it; a fake that refused it would fail on a call path that works.
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(wiz, "query", fake_query)
    return calls


@pytest.fixture
def capture_compose(wiz, monkeypatch):
    """Record subprocess.run argv (the `compose up` invocation) and succeed."""
    calls: list[list[str]] = []

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    return calls


def make_env_file(tmp_path, secret="hunter2-super-secret"):
    env_file = tmp_path / "acme.env"
    env_file.write_text(f"GITHUB_TOKEN={secret}\nGIT_AUTHOR_NAME=Agent\n")
    return env_file, secret


LOCAL_HOST = {"driver": "podman", "context": "", "address": "localhost"}


# --- compose up exec ----------------------------------------------------------


def test_compose_up_exec_generates_file_and_runs(wiz, capture_compose, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    env_file, _ = make_env_file(tmp_path)

    wiz.compose_up_exec("local", LOCAL_HOST, "acme", env_file, [], None, [])

    # A compose file is written under the per-host state dir.
    cf = wiz.compose_file_path("local", "acme")
    assert cf.is_file()
    model = json.loads(cf.read_text())
    assert model["name"] == "agent-container-acme"
    assert model["services"]["agent"]["container_name"] == "agent-container-acme"
    assert model["services"]["agent"]["ports"] == ["2206:2222"]
    assert model["services"]["agent"]["env_file"] == [str(env_file)]
    assert set(model["volumes"]) == set(wiz.per_container_volumes("acme"))

    # compose up -d --build invoked on the host's runtime.
    (argv,) = capture_compose
    assert argv[0] == "podman"  # driver runtime (context "" -> bare)
    for tok in ("compose", "-p", "agent-container-acme", "-f", str(cf), "up", "-d", "--build"):
        assert tok in argv

    # State written under the host segment.
    assert wiz.read_state_port("local", "acme") == "2206"


def test_compose_up_exec_never_inlines_secrets(wiz, capture_compose, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    env_file, secret = make_env_file(tmp_path)

    wiz.compose_up_exec("local", LOCAL_HOST, "acme", env_file, [], None, [])

    (argv,) = capture_compose
    joined = "\x00".join(argv)
    assert secret not in joined  # env-file is referenced, not inlined
    assert "GITHUB_TOKEN" not in joined
    # And the generated compose file references the env file, never its contents.
    assert secret not in wiz.compose_file_path("local", "acme").read_text()


def test_compose_up_exec_port_is_name_hash(wiz, capture_compose, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    env_file, _ = make_env_file(tmp_path)
    wiz.compose_up_exec("local", LOCAL_HOST, "my-box", env_file, [], None, [])
    model = json.loads(wiz.compose_file_path("local", "my-box").read_text())
    assert model["services"]["agent"]["ports"] == ["2204:2222"]


def test_compose_up_exec_waits_for_busy_port_then_proceeds(
    wiz, capture_compose, monkeypatch, tmp_path
):
    """A busy port is a TRANSIENT teardown state, not a fatal error: the pre-check
    cannot reserve the port, so it waits and then defers to the daemon (which is the
    only component that can actually bind it). Previously this hard-failed, turning
    an in-progress teardown into 'port is already in use — pick a different name'."""
    waited = []
    monkeypatch.setattr(wiz, "port_free", lambda port: False)  # busy the whole time
    monkeypatch.setattr(wiz, "wait_port_released", lambda port, *a, **k: waited.append(port))
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    env_file, _ = make_env_file(tmp_path)
    wiz.compose_up_exec("local", LOCAL_HOST, "acme", env_file, [], None, [])
    assert waited == [2206]  # it waited for the port rather than dying
    assert capture_compose, "the deploy must still be attempted — the daemon decides"


def test_wait_port_released_reports_timeout_instead_of_silent_giveup(wiz, monkeypatch, capsys):
    """A silent give-up made the subsequent failure unattributable — the operator saw
    'port in use' with no hint that teardown simply had not finished."""
    monkeypatch.setattr(wiz, "port_free", lambda port: False)
    assert wiz.wait_port_released(2206, timeout=0.01) is False
    err = capsys.readouterr().err
    assert "2206" in err and "still held" in err


def test_port_free_uses_reuseaddr_matching_daemon_semantics(wiz):
    """Probing WITHOUT SO_REUSEADDR reports 'in use' for a TIME_WAIT socket that a
    daemon (which sets SO_REUSEADDR) would bind fine — a false negative that used to
    become a hard failure. The probe must ask what the DAEMON can do."""
    import socket

    opts = []
    real = socket.socket

    class Probe(real):  # type: ignore[misc]
        def setsockopt(self, level, optname, value):  # noqa: D102
            opts.append((level, optname, value))
            return super().setsockopt(level, optname, value)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(socket, "socket", Probe)
    try:
        wiz.port_free(0)  # port 0 always binds; we only care about the sockopt
    finally:
        monkey.undo()
    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in opts


def test_compose_up_exec_failed_run_writes_no_state(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    monkeypatch.setattr(
        wiz.subprocess, "run", lambda argv, *a, **k: subprocess.CompletedProcess(argv, 1)
    )
    env_file, _ = make_env_file(tmp_path)
    with pytest.raises(wiz.Fatal, match="compose up failed"):
        wiz.compose_up_exec("local", LOCAL_HOST, "acme", env_file, [], None, [])
    assert wiz.read_state_port("local", "acme") is None


def test_compose_up_exec_threads_binds_into_volumes(wiz, capture_compose, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    env_file, _ = make_env_file(tmp_path)
    wiz.compose_up_exec("local", LOCAL_HOST, "acme", env_file, ["/abs/host:/opt/data"], None, [])
    vols = json.loads(wiz.compose_file_path("local", "acme").read_text())["services"]["agent"][
        "volumes"
    ]
    assert "/abs/host:/opt/data" in vols
    assert "agent-container-acme-workspace:/workspace" in vols
    assert len(vols) == 10 + 1  # ten per-container volumes (016 added runs) + the bind


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
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path)
    assert wiz.resolve_bind_mount("proj") == f"{(tmp_path / 'proj').resolve()}:/workspace/proj"


def test_resolve_bind_mount_dereferences_symlinked_host(wiz, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert wiz.resolve_bind_mount(str(link)) == f"{real.resolve()}:/workspace/real"


# --- do_up orchestration (compose path) --------------------------------------


@pytest.fixture
def up_env(wiz, monkeypatch, tmp_path):
    # No registry -> implicit local host; no containers running; port free; a
    # resolvable build context; compose up is captured, not executed.
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: set())
    monkeypatch.setattr(wiz, "port_free", lambda port: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    return wiz


def test_do_up_resolves_env_file_and_runs(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".agent-container").mkdir(exist_ok=True)
    (work / ".agent-container" / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    wiz.do_up("acme")
    (argv,) = capture_compose
    assert "compose" in argv and "up" in argv
    model = json.loads(wiz.compose_file_path("local", "acme").read_text())
    assert model["services"]["agent"]["env_file"] == [str(work / ".agent-container" / ".env")]


def test_do_up_threads_mounts_through(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".agent-container").mkdir(exist_ok=True)
    (work / ".agent-container" / ".env").write_text("TOKEN=x\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(work)
    wiz.do_up("acme", mounts=[str(proj)])
    vols = json.loads(wiz.compose_file_path("local", "acme").read_text())["services"]["agent"][
        "volumes"
    ]
    assert f"{proj.resolve()}:/workspace/proj" in vols


def test_do_up_rejects_bad_mount_before_any_runtime_call(
    up_env, capture_compose, monkeypatch, tmp_path
):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".agent-container").mkdir(exist_ok=True)
    (work / ".agent-container" / ".env").write_text("TOKEN=x\n")
    monkeypatch.chdir(work)
    with pytest.raises(wiz.Fatal, match="does not exist or is not a directory"):
        wiz.do_up("acme", mounts=[str(tmp_path / "missing")])
    assert capture_compose == []


def test_do_up_dies_without_env_file(up_env, capture_compose, monkeypatch, tmp_path):
    wiz = up_env
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    with pytest.raises(wiz.Fatal, match="no env file found"):
        wiz.do_up("acme")
    assert capture_compose == []


def test_do_up_noop_when_already_running(up_env, capture_compose, monkeypatch):
    wiz = up_env
    monkeypatch.setattr(
        wiz, "host_container_names", lambda host, include_stopped=False: {"agent-container-acme"}
    )
    wiz.do_up("acme")  # logs and returns
    assert capture_compose == []


def test_do_up_dies_on_stopped_leftover(up_env, capture_compose, monkeypatch):
    wiz = up_env
    monkeypatch.setattr(
        wiz,
        "host_container_names",
        lambda host, include_stopped=False: {"agent-container-acme"} if include_stopped else set(),
    )
    with pytest.raises(wiz.Fatal, match="exists but is not running"):
        wiz.do_up("acme")
    assert capture_compose == []


def test_do_up_rejects_invalid_name_before_any_runtime_call(up_env, capture_compose):
    wiz = up_env
    with pytest.raises(wiz.Fatal, match="invalid <name>"):
        wiz.do_up("Bad Name")
    assert capture_compose == []


# --- down / purge via compose ------------------------------------------------


def _seed_compose(wiz, name="acme"):
    wiz.write_compose_file("local", name, wiz.build_compose_model(name, "/repo"))
    wiz.write_state("local", name, wiz.port_for_name(name))


def test_down_purge_uses_compose_down_volumes(wiz, capture_query, monkeypatch):
    _seed_compose(wiz)
    monkeypatch.setattr(
        wiz, "host_container_names", lambda h, include_stopped=False: {"agent-container-acme"}
    )
    monkeypatch.setattr(wiz, "wait_port_released", lambda port: None)
    wiz.down_container("local", LOCAL_HOST, "acme", purge=True)
    downs = [c for c in capture_query if "down" in c]
    assert downs and any("--volumes" in c for c in downs)
    assert wiz.read_state_port("local", "acme") is None  # state cleared
    assert not wiz.compose_file_path("local", "acme").is_file()  # artifact removed on purge


def test_down_without_purge_preserves_volumes(wiz, capture_query, monkeypatch):
    _seed_compose(wiz)
    monkeypatch.setattr(
        wiz, "host_container_names", lambda h, include_stopped=False: {"agent-container-acme"}
    )
    monkeypatch.setattr(wiz, "wait_port_released", lambda port: None)
    wiz.down_container("local", LOCAL_HOST, "acme", purge=False)
    downs = [c for c in capture_query if "down" in c]
    assert downs and not any("--volumes" in c for c in downs)
    assert wiz.compose_file_path("local", "acme").is_file()  # preserved


# --- attach argv -------------------------------------------------------------


def test_ssh_argv_is_the_canonical_attach_command(wiz):
    # Feature 018: the argv now carries verification. Asserted in full rather than
    # by prefix, because a missing -o here is an attach that connects unverified and
    # looks exactly like one that does not.
    opts = wiz.verification_opts()
    assert wiz.ssh_argv("dev", "localhost", 2206) == [
        "ssh",
        "dev@localhost",
        "-p",
        "2206",
        *opts,
        "-t",
        "tmux",
        "attach",
        "-t",
        "main",
    ]
    assert wiz.ssh_argv("dev", "vps.example.com", "2299") == [
        "ssh",
        "dev@vps.example.com",
        "-p",
        "2299",
        *opts,
        "-t",
        "tmux",
        "attach",
        "-t",
        "main",
    ]


def test_every_ssh_builder_carries_verification(wiz):
    """T017/FR-004. THREE builders reach the same endpoint, and each is a separate
    way out of the feature if it forgets: the attach argv, the dead-session probe
    (which on a different known_hosts would give two verifications that disagree),
    and the ssh-config stanza an operator pastes into their own config.
    """
    argv = wiz.ssh_argv("dev", "localhost", 2206)
    probe = wiz.ssh_probe_argv("dev", "localhost", 2206, "true")
    stanza = wiz.ssh_config_stanza("acme", "dev", "localhost", "2206")
    for got in (argv, probe):
        assert "StrictHostKeyChecking=yes" in got
        assert any(a.startswith("UserKnownHostsFile=") for a in got)
        # accept-new silently trusts an unpinned host — the behaviour 018 replaces.
        assert not any("accept-new" in a for a in got)
    assert "    StrictHostKeyChecking yes" in stanza
    assert "    UserKnownHostsFile " in stanza
    assert "accept-new" not in stanza


def test_verification_never_points_at_the_operators_own_known_hosts(wiz):
    """FR-006/SC-007: the tool manages its own file and never the operator's."""
    opts = " ".join(wiz.verification_opts())
    assert str(wiz.STATE_DIR) in opts
    assert "/.ssh/known_hosts" not in opts


def test_cli_attach_execs_ssh_with_full_handover(wiz, monkeypatch):
    wiz.write_state("local", "acme", 2206)
    # Feature 018: attach verifies, so these tests must start from a PINNED
    # environment — they exercise handover/window/probe, not the unpinned path
    # (which test_shell_integration.py owns).
    wiz.pin_host_key("local", "localhost", 2206, TEST_HOST_PUBKEY)
    monkeypatch.setattr(wiz, "probe_session", lambda *a, **k: "alive")  # FR-008 probe
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, list(argv))))
    wiz.cli_attach("acme", "local", None, None)
    assert execs == [
        (
            "ssh",
            [
                "ssh",
                "dev@localhost",
                "-p",
                "2206",
                *wiz.verification_opts(),
                "-t",
                "tmux",
                "attach",
                "-t",
                "main",
            ],
        ),
    ]


# --- attach --window ---------------------------------------------------------


def test_ssh_argv_with_window_selects_then_attaches_single_arg(wiz):
    opts = wiz.verification_opts()
    argv = wiz.ssh_argv("dev", "localhost", 2206, "agents")
    assert argv[: 5 + len(opts)] == ["ssh", "dev@localhost", "-p", "2206", *opts, "-t"]
    assert argv[5 + len(opts) :] == [
        "tmux select-window -t main:agents 2>/dev/null; exec tmux attach -t main"
    ]
    assert len(argv) == 6 + len(opts)


def test_ssh_argv_without_window_is_unchanged(wiz):
    assert wiz.ssh_argv("dev", "localhost", 2206) == [
        "ssh",
        "dev@localhost",
        "-p",
        "2206",
        *wiz.verification_opts(),
        "-t",
        "tmux",
        "attach",
        "-t",
        "main",
    ]


def test_cli_attach_window_execs_compound_remote_command(wiz, monkeypatch):
    wiz.write_state("local", "acme", 2206)
    # Feature 018: attach verifies, so these tests must start from a PINNED
    # environment — they exercise handover/window/probe, not the unpinned path
    # (which test_shell_integration.py owns).
    wiz.pin_host_key("local", "localhost", 2206, TEST_HOST_PUBKEY)
    monkeypatch.setattr(wiz, "probe_session", lambda *a, **k: "alive")  # FR-008 probe
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, list(argv))))
    wiz.cli_attach("acme", "local", None, None, "edit")
    assert execs == [
        (
            "ssh",
            [
                "ssh",
                "dev@localhost",
                "-p",
                "2206",
                *wiz.verification_opts(),
                "-t",
                "tmux select-window -t main:edit 2>/dev/null; exec tmux attach -t main",
            ],
        )
    ]


def test_cli_attach_rejects_bad_window_before_exec(wiz, monkeypatch):
    wiz.write_state("local", "acme", 2206)
    execs: list = []
    monkeypatch.setattr(wiz.os, "execvp", lambda file, argv: execs.append((file, argv)))
    with pytest.raises(wiz.Fatal, match="invalid tmux window"):
        wiz.cli_attach("acme", "local", None, None, "a; rm -rf ~")
    assert execs == []


# --- attach target resolution ------------------------------------------------


def write_hosts(wiz, text):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text(text)


def test_resolve_local_from_state_file(wiz):
    wiz.write_state("local", "acme", 2206)
    assert wiz.resolve_attach_target("acme", "local") == ("dev", "localhost", "2206", "local")


def test_resolve_local_honours_agent_container_host_and_user(wiz, monkeypatch):
    wiz.write_state("local", "acme", 2206)
    monkeypatch.setenv("AGENT_CONTAINER_HOST", "lima-vm")
    monkeypatch.setenv("AGENT_CONTAINER_USER", "ops")
    assert wiz.resolve_attach_target("acme", "local") == ("ops", "lima-vm", "2206", "local")


def test_resolve_remote_from_hosts_conf(wiz):
    write_hosts(wiz, "MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2204\n")
    assert wiz.resolve_attach_target("my-box", "remote") == (
        "dev",
        "vps.example.com",
        "2204",
        "remote",
    )


def test_resolve_auto_prefers_remote_over_local_state(wiz):
    wiz.write_state("local", "acme", 2206)
    write_hosts(wiz, "ACME_HOST=vps.example.com\nACME_PORT=2299\n")
    assert wiz.resolve_attach_target("acme", "auto") == (
        "dev",
        "vps.example.com",
        "2299",
        "remote",
    )


def test_resolve_auto_falls_back_to_local_state(wiz):
    wiz.write_state("local", "acme", 2206)
    assert wiz.resolve_attach_target("acme", "auto") == ("dev", "localhost", "2206", "local")


def test_resolve_name_is_case_insensitive(wiz):
    write_hosts(wiz, "MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2204\n")
    assert wiz.resolve_attach_target("My-Box", "remote")[1] == "vps.example.com"


def test_resolve_remote_requires_hosts_conf(wiz):
    with pytest.raises(wiz.Fatal, match="no hosts config"):
        wiz.resolve_attach_target("acme", "remote")


def test_resolve_remote_requires_both_keys(wiz):
    write_hosts(wiz, "ACME_HOST=vps.example.com\n")
    with pytest.raises(wiz.Fatal, match="no host configured for acme"):
        wiz.resolve_attach_target("acme", "remote")


def test_resolve_local_without_state_dies_with_hint(wiz):
    with pytest.raises(wiz.Fatal, match="no local state for acme"):
        wiz.resolve_attach_target("acme", "local")


def test_resolve_auto_with_nothing_dies(wiz):
    with pytest.raises(wiz.Fatal, match="no attach target for acme"):
        wiz.resolve_attach_target("acme", "auto")


def test_resolve_rejects_host_option_injection(wiz):
    wiz.write_state("local", "acme", 2206)
    with pytest.raises(wiz.Fatal, match="invalid ssh host"):
        wiz.resolve_attach_target("acme", "local", host_override="-oProxyCommand=evil")


# --- list / stale-state rows -------------------------------------------------


def test_gather_rows_marks_orphaned_state_files_stale(wiz, monkeypatch):
    monkeypatch.setattr(
        wiz,
        "ps_agent_container",
        lambda rt, include_stopped=False, strict=False: [
            (
                "agent-container-acme",
                "localhost/agent-container:latest",
                "Up 2 hours",
                "2 hours ago",
            ),
        ],
    )
    wiz.write_state("local", "acme", 2206)
    wiz.write_state("local", "ghost", 2299)
    rows = wiz.gather_rows("podman")
    by_name = {r["name"]: r for r in rows}
    assert by_name["agent-container-acme"]["port"] == "2206"
    assert by_name["agent-container-acme"]["stale"] is False
    assert by_name["agent-container-acme"]["host"] == "local"
    assert by_name["agent-container-ghost"]["port"] == "2299"
    assert by_name["agent-container-ghost"]["stale"] is True
    assert by_name["agent-container-ghost"]["status"] == "stale"


# --- SSH injection: staging (compose secrets/configs) + keys subcommand ------


def test_stage_ssh_injection_writes_local_files(wiz, tmp_path):
    p1 = tmp_path / "a.pub"
    p1.write_text("ssh-ed25519 AAAAA a\n")
    p2 = tmp_path / "b.pub"
    p2.write_text("ssh-ed25519 BBBBB b")  # no trailing newline -> normalized
    ak_file = wiz.stage_ssh_injection("local", "acme", [p1, p2])
    assert ak_file.read_text() == "ssh-ed25519 AAAAA a\nssh-ed25519 BBBBB b\n"
    # 0644: compose exposes the source mode into the container, where dev
    # (uid 1000 != host uid) must read it. Public keys, so 0644 costs nothing —
    # and Feature 018 removed the private key that used to be staged the same way,
    # BECAUSE it could not be staged any more tightly than this.
    assert (ak_file.stat().st_mode & 0o777) == 0o644
    assert (wiz.host_state_dir("local").stat().st_mode & 0o777) == 0o700


def test_stage_ssh_injection_none_when_absent(wiz):
    assert wiz.stage_ssh_injection("local", "acme", []) is None


def test_stage_ssh_injection_rejects_missing_files(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="--authorized-key"):
        wiz.stage_ssh_injection("local", "acme", [tmp_path / "nope.pub"])


def test_keys_streams_secrets_over_stdin_never_argv(wiz, monkeypatch, tmp_path):
    """Public keys go via stdin, never argv (so they cannot leak through the process
    table), and land in the running container by exec.

    Feature 018 removed this path's private-host-key arm — `keys --host-key` used to
    install a PRIVATE key into a live container. What remains is public material, and
    the stdin discipline is kept anyway: it costs nothing and the habit is the point.
    """
    calls: list[tuple[list[str], object]] = []

    def fake_run(argv, **kw):
        calls.append((list(argv), kw.get("input")))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    pub = tmp_path / "p.pub"
    pub.write_bytes(b"ssh-ed25519 PUBPUB u")

    wiz.inject_keys("podman", "acme", [pub])
    ak_argv, ak_input = calls[0]
    assert ak_input == b"ssh-ed25519 PUBPUB u"
    assert ak_argv[:4] == ["podman", "exec", "-i", "agent-container-acme"]
    # The material is on stdin, never on argv, where the process table would show it.
    assert all(b"PUBPUB" not in a.encode() for a in ak_argv)


# --- driver argv builders (Feature 001) --------------------------------------


def test_driver_runtime_argv_docker_and_podman(wiz):
    assert wiz.driver_runtime_argv({"driver": "docker", "context": "lima"}) == [
        "docker",
        "--context",
        "lima",
    ]
    assert wiz.driver_runtime_argv({"driver": "podman", "context": "vps"}) == [
        "podman",
        "--connection",
        "vps",
    ]
    assert wiz.driver_runtime_argv({"driver": "docker", "context": ""}) == ["docker"]


def test_driver_runtime_argv_existing_ssh_is_attach_only(wiz):
    with pytest.raises(wiz.Fatal, match="attach-only"):
        wiz.driver_runtime_argv({"driver": "existing-ssh", "address": "vps"})


def test_driver_up_and_down_argv(wiz, tmp_path):
    host = {"driver": "docker", "context": "lima"}
    f = tmp_path / "acme.compose.yaml"
    up = wiz.driver_up_argv(host, "agent-container-acme", f)
    assert up == [
        "docker",
        "--context",
        "lima",
        "compose",
        "-p",
        "agent-container-acme",
        "-f",
        str(f),
        "up",
        "-d",
        "--build",
    ]
    down = wiz.driver_down_argv(host, "agent-container-acme", f)
    assert down[-2:] == ["down", "--remove-orphans"]
    down_purge = wiz.driver_down_argv(host, "agent-container-acme", f, purge=True)
    assert down_purge[-3:] == ["down", "--remove-orphans", "--volumes"]


def test_remove_orphans_is_on_down_only(wiz, tmp_path):
    """Reproduced defect: dropping an `egress:` declaration regenerates a compose
    file without the proxy service, and a plain `down` then leaves
    `agent-egress-<name>` Up — under `restart: unless-stopped`, invisible to `list`,
    to every wizard picker and to assert_host_empty — while STILL EXITING 0.

    But the flag must NOT reach up/redeploy: there it would remove an operator's own
    helper services from `<name>.services.yaml`, which are legitimately absent from
    the generated file. This test is the guard on that asymmetry.
    """
    host, f = {"driver": "docker", "context": "lima"}, tmp_path / "acme.compose.yaml"
    assert "--remove-orphans" in wiz.driver_down_argv(host, "p", f)
    assert "--remove-orphans" not in wiz.driver_up_argv(host, "p", f)
    assert "--remove-orphans" not in wiz.driver_redeploy_argv(host, "p", f)


def test_driver_reachable_address(wiz):
    assert wiz.driver_reachable_address({"address": "1.2.3.4"}) == "1.2.3.4"
    assert wiz.driver_reachable_address({}) == "localhost"


# --- sidecar / helper services (Feature 002 US4, R5) -------------------------

DOCKER_H = {"driver": "docker", "context": "lima"}
VALID_SIDECAR = "services:\n  cache:\n    image: redis:7\n"


def _write_override(path, text=VALID_SIDECAR):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_sidecar_override_discovery_prefers_project_local(wiz, monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    proj_local = _write_override(work / ".agent-container" / "acme.services.yaml")
    _write_override(wiz.CONFIG_DIR / "acme.services.yaml")  # also present, lower priority
    assert wiz.resolve_sidecar_override("acme") == proj_local


def test_sidecar_override_falls_back_to_user_config(wiz, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no project-local file here
    cfg = _write_override(wiz.CONFIG_DIR / "acme.services.yaml")
    assert wiz.resolve_sidecar_override("acme") == cfg


def test_sidecar_override_absent_returns_none(wiz, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert wiz.resolve_sidecar_override("acme") is None


def test_driver_argv_builders_merge_override_as_second_f(wiz, tmp_path):
    f = tmp_path / "acme.compose.yaml"
    ov = tmp_path / "side.yaml"
    for build in (wiz.driver_up_argv, wiz.driver_redeploy_argv, wiz.driver_stop_argv,
                  wiz.driver_start_argv):  # fmt: skip
        argv = build(DOCKER_H, "p", f, ov)
        # exactly one extra -f, right after the generated file, before the verb
        assert argv[6:10] == ["-f", str(f), "-f", str(ov)]
    down = wiz.driver_down_argv(DOCKER_H, "p", f, purge=True, rmi_local=True, override=ov)
    assert down[6:10] == ["-f", str(f), "-f", str(ov)]
    # override doesn't disturb args; --remove-orphans rides with the verb (down only)
    assert down[-5:] == ["down", "--remove-orphans", "--volumes", "--rmi", "local"]


def test_driver_argv_without_override_is_unchanged(wiz, tmp_path):
    f = tmp_path / "acme.compose.yaml"
    assert wiz.driver_stop_argv(DOCKER_H, "p", f).count("-f") == 1  # no phantom second -f


@pytest.mark.parametrize(
    "text, match",
    [
        ("", "empty"),
        ("   \n\n", "empty"),
        ("volumes:\n  data: {}\n", "no `services:`"),  # not a services fragment
        ("services:\n  cache:\n    image: redis\nvolumes:\n  d: {}\n", "services-only"),
        ("name: hijack\nservices:\n  cache:\n    image: redis\n", "services-only"),
        ("services:\n  agent:\n    image: evil\n", "must not redefine the 'agent'"),
    ],
)
def test_validate_sidecar_override_rejects(wiz, tmp_path, text, match):
    p = _write_override(tmp_path / "bad.services.yaml", text)
    with pytest.raises(wiz.Fatal, match=match):
        wiz.validate_sidecar_override(p)


def test_validate_sidecar_override_accepts_yaml_and_json(wiz, tmp_path):
    wiz.validate_sidecar_override(_write_override(tmp_path / "a.services.yaml", VALID_SIDECAR))
    # JSON is a YAML subset — a JSON override is validated exactly, not scanned.
    js = json.dumps({"services": {"cache": {"image": "redis:7"}}})
    wiz.validate_sidecar_override(_write_override(tmp_path / "b.services.yaml", js))
    # `version:` alongside services is tolerated (compose-deprecated but harmless).
    wiz.validate_sidecar_override(
        _write_override(tmp_path / "c.services.yaml", "version: '3'\n" + VALID_SIDECAR)
    )


def test_resolve_sidecar_override_fatal_on_invalid(wiz, monkeypatch, tmp_path):
    """A present-but-invalid override is fatal (FR-018), never silently skipped."""
    monkeypatch.chdir(tmp_path)
    _write_override(
        tmp_path / ".agent-container" / "acme.services.yaml", "services:\n  agent:\n    image: x\n"
    )
    with pytest.raises(wiz.Fatal, match="must not redefine"):
        wiz.resolve_sidecar_override("acme")


def test_compose_up_exec_merges_discovered_override(wiz, capture_compose, monkeypatch, tmp_path):
    """End-to-end: a discovered override rides as a second -f in the real up argv."""
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    ov = _write_override(work / ".agent-container" / "acme.services.yaml")
    env_file, _ = make_env_file(tmp_path)
    wiz.compose_up_exec("local", dict(LOCAL_HOST), "acme", env_file, [], None, [])
    argv = capture_compose[-1]
    assert argv.count("-f") == 2 and str(ov) in argv
    assert argv[argv.index(str(ov)) - 1] == "-f"


# --- `logs --egress`: reaching the refusal record (T130/FR-020d) --------------


@pytest.fixture
def capture_logs(wiz, monkeypatch):
    """Record the argv `do_logs` hands the runtime, and report every container as
    existing so the flag's own routing is what the test measures."""
    calls: list[list[str]] = []

    def fake_run_child(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "run_child", fake_run_child)
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: True)
    return calls


def test_logs_reads_the_agent_container_by_default(wiz, capture_logs):
    """The pre-T130 behaviour is unchanged — the flag adds a stream, it does not
    move the existing one."""
    assert wiz.do_logs("acme", follow=False) == 0
    (argv,) = capture_logs
    assert argv == ["podman", "logs", "agent-container-acme"]


def test_logs_egress_reads_the_boundary_not_the_agent(wiz, capture_logs):
    """T130/FR-020d. unbound's reply log is the ONLY record of a refused
    resolution, and it is written by the egress container — which is deliberately
    outside the `agent-container-*` namespace, so no other command can reach it.
    Reading the agent's log here would show a failed lookup with no cause.
    """
    assert wiz.do_logs("acme", follow=True, egress=True) == 0
    (argv,) = capture_logs
    assert argv == ["podman", "logs", "-f", wiz.egress_container_name("acme")]
    assert wiz.container_name("acme") not in argv


def test_logs_egress_names_the_missing_boundary_as_policy_not_breakage(wiz, monkeypatch):
    """An environment with no declaration has no boundary container. The runtime's
    bare 'no such container' reads as a tool fault; the truth is that nothing was
    ever deployed to log, which is the same conflation FR-020e forbids one level
    down.
    """
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "container_exists", lambda rt, cname: False)
    monkeypatch.setattr(wiz, "run_child", lambda argv: pytest.fail("must not reach the runtime"))
    with pytest.raises(wiz.Fatal) as e:
        wiz.do_logs("acme", follow=False, egress=True)
    msg = str(e.value)
    assert wiz.egress_container_name("acme") in msg, "name the container that is absent"
    assert "egress:" in msg, "and why it is absent — the spec never declared one"
