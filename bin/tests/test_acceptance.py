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


def _exec(name: str, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [RUNTIME, "exec", f"agent-container-{name}", *argv],
        capture_output=True,
        text=True,
    )


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
        name, *, authorized_key=None, host_key=None, env_extra=None, push_key=None, known_hosts=None
    ) -> int:  # noqa: E501
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
        r = _run_cli(argv, state_dir)
        assert r.returncode == 0, f"up {name} failed:\n{r.stderr}"
        started.append(name)
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
    rows = json.loads(r.stdout)
    dead = [x for x in rows if x["host"] == "dead"]
    assert dead and all(x["status"] == "unreachable" for x in dead)  # never 'Up', never dropped
    assert any(x["name"] == "agent-container-acclist" for x in rows)  # local still listed

    rows_local = json.loads(run_list("--local").stdout)
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
    (work / f"agent-container.{name}.services.yaml").write_text(_SIDECAR_YAML)

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
    (work / f"agent-container.{name}.anthropic.key").write_text(ant_val + "\n")
    (work / f"agent-container.{name}.openai.key").write_text(oai_val + "\n")

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
    (work / f"agent-container.{name}.openai.key").write_text("sk-oai-SECRET\n")
    cfg = work / f"agent-container.{name}.config" / "codex"
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
    cfg = work / f"agent-container.{name}.config" / "claude"
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
    key_file = work / f"agent-container.{name}.anthropic.key"
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
