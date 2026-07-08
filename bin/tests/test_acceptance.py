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
    return env


def _run_cli(argv: list[str], state_dir: Path, timeout: int = 600):
    return subprocess.run(
        argv,
        env=_cli_env(state_dir),
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

    def up(name, *, authorized_key=None, host_key=None, env_extra=None) -> int:
        env_file = work / f"{name}.env"
        lines = ["GH_TOKEN=x", "GIT_USER_NAME=Test", "GIT_USER_EMAIL=t@example.com"]
        lines += list(env_extra or [])
        env_file.write_text("\n".join(lines) + "\n")
        argv = [*AGENT_CONTAINER, "up", name, "--env-file", str(env_file)]
        if host_key is not None:
            argv += ["--host-key", str(host_key)]
        for ak in authorized_key or []:
            argv += ["--authorized-key", str(ak)]
        r = _run_cli(argv, state_dir)
        assert r.returncode == 0, f"up {name} failed:\n{r.stderr}"
        started.append(name)
        port = int((state_dir / "agent-container" / f"{name}.port").read_text().strip())
        _wait_sshd(port)
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

    yield types.SimpleNamespace(
        up=up,
        down=down,
        keys=keys,
        volumes_of=volumes_of,
        tmp=work,
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


def test_purge_removes_all_seven_volumes(acc):
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("accpurge", authorized_key=[laptop.with_suffix(".pub")])
    assert len(acc.volumes_of("accpurge")) == 7
    acc.down("accpurge", purge=True)
    assert acc.volumes_of("accpurge") == []


def test_distinct_containers_get_distinct_identities(acc):
    """Per-container identity (constitution Principle IV): two auto-generated
    containers have different host keys."""
    acc.up("accdist1")
    acc.up("accdist2")
    assert _container_hostkey_fp("accdist1") != _container_hostkey_fp("accdist2")
