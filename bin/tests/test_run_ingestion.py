"""Feature 016 US1 — ingestion, drain-on-contact, teardown ordering, `runs`.

Hermetic: no docker, no podman, no network. The runtime is replaced by a fake
that records the argv it is handed, which is the only thing the tool controls —
research R10 already measured that a throwaway container reads a volume whose
writer is gone, so what is left to prove here is that the tool asks for the right
thing, in the right order, and does the right thing with the bytes it gets back.

Requirement anchors are named in the bodies. Two tests exist specifically to prove
another test can fail (T018, and the drain-does-nothing case), because a teardown
ordering assertion that passes for a build where the drain is a no-op would be a
check that passes while the thing it names is broken.
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
import types

import pytest

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}
REMOTE_HOST = {"driver": "docker", "context": "vps", "address": "vps.example.com"}
ATTACH_ONLY_HOST = {"driver": "existing-ssh", "context": "", "address": "box.example.com"}


# --- fixtures ----------------------------------------------------------------


def _record_bytes(wiz, **over) -> bytes:
    kw = dict(
        run_id="20260809T101010Z-ab12",
        environment="acme",
        agent="claude",
        kind="headless",
        outcome="finished",
        started_at="2026-08-09T10:10:10Z",
        ended_at="2026-08-09T10:12:00Z",
        exit_code=0,
    )
    kw.update(over)
    return json.dumps(wiz.build_run_record(**kw)).encode()


def _pending_bytes(run_id="20260809T101010Z-ab12") -> bytes:
    """A record shaped exactly as the ENTRYPOINT writes it at start: `outcome` and
    `ended_at` both null (the pair that identifies a record no exit path
    completed), and `environment`/`host` both null because the container is told
    neither. It cannot go through build_run_record, which refuses a null outcome —
    which is the point: this is the one record the tool receives unvalidated.
    """
    return json.dumps(
        {
            "schema": 1,
            "run_id": run_id,
            "environment": None,
            "host": None,
            "agent": "claude",
            "kind": "headless",
            "task": "sleep 600",
            "started_at": "2026-08-09T10:10:10Z",
            "ended_at": None,
            "outcome": None,
            "exit_code": None,
            "repository": None,
            "usage": {"reported": False},
            "notes": [],
        }
    ).encode()


def _tarball(members: dict[str, bytes], dirs: tuple[str, ...] = ()) -> bytes:
    """A tar stream shaped like the one `tar cf - -C /mnt .` produces."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in dirs:
            info = tarfile.TarInfo(d)
            info.type = tarfile.DIRTYPE
            tf.addfile(info)
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _done(argv, rc=0, out=b"", err=b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(argv, rc, out, err)


@pytest.fixture(autouse=True)
def real_drain(wiz, monkeypatch):
    """Put the REAL drain back.

    conftest neutralises `drain_host_records` in every loaded instance, because it
    reaches the container runtime and the rest of the suite is documented as never
    needing one. This file is the one that proves the drain works, so it opts back
    in — and it fails loudly if conftest ever stops keeping the real function
    around, rather than silently testing the stand-in.
    """
    monkeypatch.setattr(wiz, "drain_host_records", wiz.real_drain_host_records)


@pytest.fixture
def runtime(wiz, monkeypatch):
    """A fake container runtime: `volume inspect` answers from `volumes`, the tar
    container returns `tar`, the clear container returns `clear_rc`.

    Every argv the tool issues lands in `calls`, in order — the ordering property
    C4 names is only observable as a sequence, so the fake records one.
    """
    state = types.SimpleNamespace(
        calls=[], volumes=set(), tar=b"", tar_rc=0, clear_rc=0, warnings=[], on_call=None
    )

    def fake_query(argv, timeout=None):
        state.calls.append(list(argv))
        if state.on_call is not None:
            state.on_call(list(argv))
        if "volume" in argv:
            return _done(argv, 0 if argv[-1] in state.volumes else 1)
        if "--entrypoint" in argv:  # the clear container
            return _done(argv, state.clear_rc, err="no such file")
        return _done(argv)

    def fake_run(argv, capture_output=False, timeout=None, **kw):
        state.calls.append(list(argv))
        if state.on_call is not None:
            state.on_call(list(argv))
        return _done(argv, state.tar_rc, state.tar, b"tar: cannot open")

    monkeypatch.setattr(wiz, "query", fake_query)
    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "host_ps_rows", lambda h, include_stopped=False: [])
    monkeypatch.setattr(wiz, "warn", state.warnings.append)
    return state


def _tar_calls(state) -> list[list[str]]:
    return [c for c in state.calls if "tar" in c]


def _clear_calls(state) -> list[list[str]]:
    return [c for c in state.calls if "rm" in c]


# --- T015: the argv the throwaway container is given (research R10) ----------


def test_the_ingest_container_overrides_the_image_entrypoint(wiz):
    """The single most dangerous omission in this mechanism. The agent image sets
    ENTRYPOINT to entrypoint.sh, so without `--entrypoint tar` the tar arguments
    are handed to the entrypoint and stdout carries its output instead — which
    parses as an empty archive and reports a successful drain of nothing, for
    every record, forever.
    """
    argv = wiz.driver_ingest_argv(LOCAL_HOST, "agent-container-acme-runs", "img")
    assert "--entrypoint" in argv
    assert argv[argv.index("--entrypoint") + 1] == "tar"
    # …and the entrypoint override must precede the image, or it is an argument
    # to the container rather than an option to `run`.
    assert argv.index("--entrypoint") < argv.index("img")


def test_the_ingest_container_targets_the_HOST_runtime_not_the_local_one(wiz):
    """R10's whole point: the operator's machine shares no filesystem with the
    host, so this must run on the host's daemon and only bytes cross the boundary.
    A builder that dropped the context would read a volume that does not exist
    locally and report a clean, empty drain."""
    argv = wiz.driver_ingest_argv(REMOTE_HOST, "v", "img")
    assert argv[:3] == ["docker", "--context", "vps"]


def test_the_ingest_container_mounts_read_only_and_without_a_network(wiz):
    argv = wiz.driver_ingest_argv(LOCAL_HOST, "v", "img")
    assert "v:/mnt:ro" in argv
    assert argv[argv.index("--network") + 1] == "none"


def test_the_clear_container_names_every_file_and_uses_no_wildcard(wiz):
    """A run that wrote a record between the tar read and the clear has not been
    ingested. A wildcard would delete it unread — and it is precisely the record
    nobody would ever notice was missing."""
    argv = wiz.driver_ingest_clear_argv(LOCAL_HOST, "v", "img", ["a.json", "b.json"])
    assert argv[-3:] == ["--", "/mnt/a.json", "/mnt/b.json"]
    assert not any("*" in a for a in argv)
    # `rm` as the entrypoint means no shell exists anywhere in the chain, so a
    # metacharacter in a filename has nothing to be interpreted by.
    assert argv[argv.index("--entrypoint") + 1] == "rm"


def test_the_ingest_image_prefers_the_environments_own_container(wiz, monkeypatch):
    """R10 measured the mechanism with `alpine`, which assumes a registry pull —
    an assumption a host with a declared egress boundary (Feature 012) can refuse.
    The environment's own image is present by construction, because the records
    exist only because that container ran there."""
    images = {wiz.container_name("acme"): "acme-project-agent"}
    assert wiz.resolve_ingest_image(images, "acme") == "acme-project-agent"
    assert wiz.resolve_ingest_image({}, "acme") == wiz.IMAGE_NAME
    monkeypatch.setenv("AGENT_CONTAINER_INGEST_IMAGE", "operators-choice")
    assert wiz.resolve_ingest_image(images, "acme") == "operators-choice"


# --- T015: what comes back out of the tar ------------------------------------


def test_a_record_round_trips_out_of_the_tar_stream(wiz):
    blob = _tarball({"./20260809T101010Z-ab12.json": _record_bytes(wiz)})
    got = wiz.pending_records_from_tar(blob)
    assert [name for name, _ in got] == ["20260809T101010Z-ab12.json"]
    assert got[0][1]["outcome"] == "finished"


@pytest.mark.parametrize(
    "member",
    ["../escape.json", "sub/dir.json", "/absolute.json", ".hidden.json", "notes.txt"],
)
def test_a_member_that_is_not_a_plain_run_record_is_refused(wiz, monkeypatch, member):
    """Member names arrive from inside the container and each would become a
    filename in the operator's store. Refused, never repaired: an extractor that
    "cleans" a hostile name is one silent bug away from writing outside the store,
    and `tar cf - -C /mnt .` emits `./<run-id>.json` for a record and nothing else.
    """
    monkeypatch.setattr(wiz, "warn", lambda _m: None)
    assert wiz.pending_records_from_tar(_tarball({member: _record_bytes(wiz)})) == []


def test_the_traversal_guard_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail. Widen RUN_ID_RE to the everything-pattern a careless
    'just let names through' change would produce, and `../escape` must then be
    accepted — otherwise the test above would keep passing for a build with no
    guard at all, which is the shape this project keeps finding."""
    import re

    monkeypatch.setattr(wiz, "RUN_ID_RE", re.compile(r".*"))
    monkeypatch.setattr(wiz, "warn", lambda _m: None)
    got = wiz.pending_records_from_tar(_tarball({"../escape.json": _record_bytes(wiz)}))
    assert [name for name, _ in got] == ["../escape.json"]


def test_a_directory_member_is_skipped_without_complaint(wiz, monkeypatch):
    """`tar cf - -C /mnt .` always emits `./` itself. Warning about it would put a
    line of noise on every single drain."""
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    blob = _tarball({"./r.json": _record_bytes(wiz)}, dirs=("./",))
    assert len(wiz.pending_records_from_tar(blob)) == 1
    assert warnings == []


def test_an_oversized_member_is_refused_rather_than_read(wiz, monkeypatch):
    """A record is a summary, not a log. A member that large is not a record, and
    reading it to find that out is how a small helper becomes a way to exhaust the
    CLI's memory from inside a container."""
    monkeypatch.setattr(wiz, "MAX_RECORD_BYTES", 8)
    monkeypatch.setattr(wiz, "warn", lambda _m: None)
    assert wiz.pending_records_from_tar(_tarball({"./r.json": _record_bytes(wiz)})) == []


def test_a_record_from_a_future_schema_is_left_alone_and_said_out_loud(wiz, monkeypatch):
    """`schema` exists so a consumer can REFUSE a record instead of misreading it
    (data-model §1) — which means something only if something actually refuses.
    Refused is not dropped: it stays on the volume for a build that understands it.
    """
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    body = json.dumps({"schema": 99, "run_id": "x"}).encode()
    assert wiz.pending_records_from_tar(_tarball({"./x.json": body})) == []
    assert any("schema" in m for m in warnings)


def test_an_unparseable_record_is_named_not_skipped_silently(wiz, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    assert wiz.pending_records_from_tar(_tarball({"./bad.json": b"{partial"})) == []
    assert any("bad.json" in m for m in warnings)


# --- T015/T016: ingestion end to end -----------------------------------------


def test_ingestion_stores_the_record_and_stamps_the_host(wiz, runtime):
    """The host is stamped HERE and nowhere else: the container knows which daemon
    it runs on, not what the operator's registry calls it (data-model §1)."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./20260809T101010Z-ab12.json": _record_bytes(wiz)})
    assert wiz.ingest_records("vps", REMOTE_HOST, "acme", "img") == ["20260809T101010Z-ab12"]
    stored = json.loads(
        (wiz.runs_store_dir("vps", "acme") / "20260809T101010Z-ab12.json").read_text()
    )
    assert stored["host"] == "vps"
    assert stored["run_id"] == "20260809T101010Z-ab12"


def test_ingestion_stamps_the_environment_the_volume_came_from(wiz, runtime):
    """`environment` is stamped here for the same reason `host` is: the container
    writes null on purpose (telling it its own name would create a second copy
    that can drift from the volume the tool keys on). Left null, `runs list` with
    no environment argument would show `?` in the column that says which
    deployment a run belongs to."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1", environment=None)})
    wiz.ingest_records("vps", REMOTE_HOST, "acme", "img")
    stored = json.loads((wiz.runs_store_dir("vps", "acme") / "r1.json").read_text())
    assert stored["environment"] == "acme"


def test_a_pending_record_from_a_dead_container_is_completed_as_stopped(wiz, runtime):
    """SC-008 / data-model §7. SIGKILL runs no trap, so the start-side write is all
    there is. Storing it untouched would list the killed run with a null outcome —
    the record would exist and still not say the one thing it knows."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _pending_bytes("r1")})
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img", live=False) == ["r1"]
    stored = json.loads((wiz.runs_store_dir("local", "acme") / "r1.json").read_text())
    assert stored["outcome"] == "stopped"
    # `ended_at` is NOT invented: the container's clock stopped at an instant
    # nobody observed, and the ingestion time can be the next morning.
    assert stored["ended_at"] is None
    assert any("reconstructed" in n for n in stored["notes"])
    assert _clear_calls(runtime), "a finalised record must not be left on the volume"


def test_a_pending_record_from_a_LIVE_container_is_left_alone(wiz, runtime):
    """The wrong answer that looks right. A drain during a detached run finds the
    same pending record a killed run leaves — the ONLY difference is that its
    writer is still alive. Calling it `stopped` would be a false statement about a
    run in progress, and clearing it would mean a SIGKILL a second later leaves
    nothing on the volume to finalise."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _pending_bytes("r1")})
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img", live=True) == ["r1"]
    stored = json.loads((wiz.runs_store_dir("local", "acme") / "r1.json").read_text())
    assert stored["outcome"] is None
    assert _clear_calls(runtime) == []


def test_reconstruction_never_overwrites_an_outcome_the_container_reported(wiz):
    """The complementary half: a record that DID complete keeps its own ending.
    A reconstruction that fired unconditionally would turn every `finished` run
    into a `stopped` one — and the store would be uniformly wrong rather than
    obviously broken."""
    rec = {"outcome": "finished", "ended_at": "2026-08-09T10:12:00Z", "notes": []}
    assert wiz._reconstruct_pending(dict(rec)) == rec


@pytest.mark.parametrize(
    ("status", "alive"),
    [
        ("Up 4 seconds", True),
        ("Restarting (1) 2 seconds ago", True),
        ("Exited (137) 1 minute", False),
    ],
)
def test_liveness_comes_from_the_same_ps_as_the_image(wiz, monkeypatch, status, alive):
    """Both facts come from ONE `ps` so they cannot disagree, and `Restarting`
    counts as alive: the conservative direction is to leave a record pending,
    because that is corrected by the next contact while a false `stopped` is not.
    """
    monkeypatch.setattr(
        wiz,
        "host_ps_rows",
        lambda h, include_stopped=False: [(wiz.container_name("acme"), "img", status, "1m")],
    )
    images, live = wiz.host_drain_facts(LOCAL_HOST)
    assert images == {wiz.container_name("acme"): "img"}
    assert (wiz.container_name("acme") in live) is alive


def test_a_missing_volume_is_never_probed_into_existence(wiz, runtime):
    """`run -v <name>:…` CREATES a named volume as a side effect. A drain that ran
    unconditionally would quietly re-create the volume it found missing — erasing
    the evidence that records were lost to an out-of-band `volume rm`, which is a
    spec edge case something later has to be able to detect."""
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img") == []
    assert _tar_calls(runtime) == []
    assert _clear_calls(runtime) == []


def test_records_are_cleared_only_AFTER_they_are_durable(wiz, runtime):
    """The order of the last two steps is the property. Clearing first would trade
    a record that is merely un-ingested for one that is gone."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    durable_at_clear: list[bool] = []
    runtime.on_call = lambda argv: (
        durable_at_clear.append((wiz.runs_store_dir("local", "acme") / "r1.json").is_file())
        if "rm" in argv
        else None
    )
    wiz.ingest_records("local", LOCAL_HOST, "acme", "img")
    assert durable_at_clear == [True], "the volume was cleared before the record was stored"


def test_nothing_is_cleared_when_nothing_was_stored(wiz, runtime):
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({})
    wiz.ingest_records("local", LOCAL_HOST, "acme", "img")
    assert _clear_calls(runtime) == []


def test_a_failed_read_warns_and_says_the_records_are_still_at_risk(wiz, runtime):
    """FR-008 applied to the tool's side: never fatal, never silent. A drain that
    failed quietly is indistinguishable from a host with nothing pending — the one
    thing an operator would never think to check."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar_rc = 1
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img") == []
    assert any("--purge" in m for m in runtime.warnings)


def test_a_failed_clear_keeps_the_record_and_warns(wiz, runtime):
    """The records are already durable, so a failed clear is a warning and not a
    failure — and re-ingesting them is idempotent because a record's id IS its
    filename."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    runtime.clear_rc = 1
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img") == ["r1"]
    assert (wiz.runs_store_dir("local", "acme") / "r1.json").is_file()
    assert any("could not clear" in m for m in runtime.warnings)


def test_an_unstorable_record_is_left_on_the_volume(wiz, runtime, monkeypatch):
    """If the durable write fails, the volume copy is the only copy left — so it
    must not be among the names handed to the clear step."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    monkeypatch.setattr(
        wiz, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    assert wiz.ingest_records("local", LOCAL_HOST, "acme", "img") == []
    assert _clear_calls(runtime) == []


# --- T016: drain-on-contact ---------------------------------------------------


def test_the_known_environments_come_from_the_state_dir(wiz):
    """The state dir is what still remembers an environment whose container is
    gone — precisely the environment whose records are still pending."""
    d = wiz.host_state_dir("vps")
    d.mkdir(parents=True, exist_ok=True)
    (d / "acme.port").write_text("2206\n")
    (d / "blog.compose.yaml").write_text("{}")
    (d / "ignored.host_key").write_text("x")
    assert wiz.host_environments("vps") == ["acme", "blog"]


def test_draining_a_host_covers_every_environment_it_knows(wiz, runtime):
    d = wiz.host_state_dir("local")
    d.mkdir(parents=True, exist_ok=True)
    for env in ("acme", "blog"):
        (d / f"{env}.port").write_text("2206\n")
        runtime.volumes.add(wiz.runs_volume_name(env))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    # Both environments are drained; both store the same id under their own
    # directory, because the tar is a fixture and not the point here.
    assert wiz.drain_host_records("local", LOCAL_HOST) == ["r1", "r1"]
    assert (wiz.runs_store_dir("local", "acme") / "r1.json").is_file()
    assert (wiz.runs_store_dir("local", "blog") / "r1.json").is_file()


def test_draining_a_named_environment_touches_only_that_one(wiz, runtime):
    """Lifecycle commands pass the one environment they act on. Draining every
    environment on every `up` would start a throwaway container per environment on
    every deploy, and nothing is lost: an undrained record waits on its volume."""
    d = wiz.host_state_dir("local")
    d.mkdir(parents=True, exist_ok=True)
    for env in ("acme", "blog"):
        (d / f"{env}.port").write_text("2206\n")
        runtime.volumes.add(wiz.runs_volume_name(env))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    wiz.drain_host_records("local", LOCAL_HOST, ["acme"])
    assert (wiz.runs_store_dir("local", "acme") / "r1.json").is_file()
    assert not (wiz.runs_store_dir("local", "blog") / "r1.json").exists()


def test_an_attach_only_host_is_never_asked_to_run_a_container(wiz, runtime):
    """`existing-ssh` hosts are reachable over ssh and have no queryable daemon;
    driver_runtime_argv dies on them. A drain must not be the thing that turns an
    attach-only host into a fatal error on every command."""
    d = wiz.host_state_dir("box")
    d.mkdir(parents=True, exist_ok=True)
    (d / "acme.port").write_text("2206\n")
    assert wiz.drain_host_records("box", ATTACH_ONLY_HOST) == []
    assert runtime.calls == []


def test_a_host_with_no_known_environments_does_nothing(wiz, runtime):
    assert wiz.drain_host_records("local", LOCAL_HOST) == []
    assert runtime.calls == []


# --- T017/T018: teardown drains BEFORE it removes (FR-001b, C4) --------------


@pytest.fixture
def teardown_ready(wiz, monkeypatch):
    """A deployment that `down_container` will actually try to tear down."""
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda h, include_stopped=False: set())
    monkeypatch.setattr(wiz, "wait_port_released", lambda *a, **k: True)
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "log", lambda _m: None)
    wiz.write_compose_file("local", "acme", {"volumes": {}})


def _teardown_events(wiz, monkeypatch, teardown) -> list[str]:
    """Run a teardown and return its three steps in the order they happened.

    The classification is by argv rather than by call count because the teardown
    issues TWO runtime commands and they mean opposite things: `stop` lets the
    container write its own final record, `down` destroys the volume that record
    is on. A fake that called both "remove" would report the correct
    implementation as broken — and, worse, would have no way to see the stop go
    missing.
    """
    events: list[str] = []
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: events.append("drain") or [])
    monkeypatch.setattr(
        wiz,
        "query",
        lambda argv, timeout=None: (
            events.append("stop" if "stop" in argv else "remove") or _done(argv)
        ),
    )
    teardown()
    return events


def _assert_drain_precedes_removal(wiz, monkeypatch, teardown) -> None:
    """The ordering assertion itself, factored out so the swapped-order case below
    runs exactly this code against a deliberately wrong teardown. An assertion
    that only ever sees the correct implementation proves nothing about the
    property it claims to check."""
    events = _teardown_events(wiz, monkeypatch, teardown)
    assert "drain" in events, "the teardown never drained at all"
    assert "remove" in events, "the teardown never removed anything"
    assert events.index("drain") < events.index("remove"), (
        f"a drain after removal is not a late drain, it is no drain: {events}"
    )


def _assert_stop_precedes_drain(wiz, monkeypatch, teardown) -> None:
    """The other half of C4's ordering, and the one that is invisible in the
    argv alone: `compose down --volumes` kills the container and drops its volume
    in a single step, so unless the container is stopped FIRST there is no instant
    at which its own completed record exists to be drained. Measured against a
    real container: without the stop, tearing down a running environment stored
    the pending record and destroyed the `stopped` one."""
    events = _teardown_events(wiz, monkeypatch, teardown)
    assert "stop" in events, "the teardown never stopped the container"
    assert "drain" in events, "the teardown never drained at all"
    assert events.index("stop") < events.index("drain"), (
        f"draining before the container is stopped collects the PENDING record and then "
        f"destroys the completed one: {events}"
    )


def test_teardown_drains_before_removing_volumes(wiz, monkeypatch, teardown_ready):
    _assert_drain_precedes_removal(
        wiz,
        monkeypatch,
        lambda: wiz.down_container("local", dict(LOCAL_HOST), "acme", purge=True),
    )


def test_teardown_stops_the_container_before_it_drains(wiz, monkeypatch, teardown_ready):
    _assert_stop_precedes_drain(
        wiz,
        monkeypatch,
        lambda: wiz.down_container("local", dict(LOCAL_HOST), "acme", purge=True),
    )


def test_the_ordering_assertion_fails_when_the_order_is_swapped(wiz, monkeypatch, teardown_ready):
    """T018. Swap the two steps and the SAME assertion must fail — otherwise the
    test above would pass for a build whose drain runs after `compose down
    --volumes`, i.e. for a build with no drain at all."""

    def swapped_teardown() -> None:
        wiz.query(["docker", "compose", "down", "--volumes"])
        wiz.drain_host_records("local", dict(LOCAL_HOST), ["acme"])

    with pytest.raises(AssertionError, match="not a late drain"):
        _assert_drain_precedes_removal(wiz, monkeypatch, swapped_teardown)


def test_the_stop_assertion_fails_when_the_stop_is_missing(wiz, monkeypatch, teardown_ready):
    """The same proof for the stop. A teardown that drains a still-running
    container reads as correct to every argv-level check — the only observable
    difference is that the record it collects is the pending one — so the
    assertion above must be shown to fail for the build that omits the stop."""

    def unstopped_teardown() -> None:
        wiz.drain_host_records("local", dict(LOCAL_HOST), ["acme"])
        wiz.query(["docker", "compose", "down", "--volumes"])

    with pytest.raises(AssertionError, match="never stopped the container"):
        _assert_stop_precedes_drain(wiz, monkeypatch, unstopped_teardown)


def test_the_teardown_drain_actually_moves_a_record(wiz, runtime, monkeypatch, teardown_ready):
    """The other half of T018: ordering is worthless if the drain is a no-op. Run
    the REAL drain through the fake runtime and check the record is in the durable
    store at the moment `compose down` is issued — not merely that a function was
    called first."""
    runtime.volumes.add(wiz.runs_volume_name("acme"))
    runtime.tar = _tarball({"./r1.json": _record_bytes(wiz, run_id="r1")})
    durable_at_removal: list[bool] = []
    runtime.on_call = lambda argv: (
        durable_at_removal.append((wiz.runs_store_dir("local", "acme") / "r1.json").is_file())
        if "down" in argv
        else None
    )
    wiz.down_container("local", dict(LOCAL_HOST), "acme", purge=True)
    assert durable_at_removal == [True], "the record was not durable when the volumes were removed"


# --- T019: `never-started` is authored by the CLI (C6, research R5) ----------


def test_up_drains_the_environment_before_it_deploys(wiz, monkeypatch):
    """The wiring conftest neutralises for the rest of the suite, asserted here so
    it is tested exactly once rather than nowhere. Order matters for the same
    reason it does at teardown: `up` recreates the container, and a record still
    pending from the previous run is on the volume that recreation reuses."""
    events: list[str] = []
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda h, include_stopped=False: set())
    monkeypatch.setattr(wiz, "log", lambda _m: None)
    monkeypatch.setattr(
        wiz, "drain_host_records", lambda hn, hr, names=None: events.append(f"drain:{names}") or []
    )
    monkeypatch.setattr(wiz, "compose_up_exec", lambda *a, **k: events.append("deploy"))
    monkeypatch.setattr(wiz, "refuse_superseded_layout", lambda n, root=None: None)
    monkeypatch.setattr(wiz, "_resolve_env_files", lambda n, o: [])
    wiz.do_up("acme", spec=wiz.ExecSpec(mode="headless", agent="claude", task="t"))
    assert events == ["drain:['acme']", "deploy"]


def test_a_never_started_record_says_null_and_not_zero(wiz):
    """A `0` exit code would read as a clean run that never happened, and an empty
    repository effect would claim the run changed nothing when the truth is that
    it never looked."""
    run_id = wiz.record_never_started(
        "vps", "acme", wiz.ExecSpec(mode="headless", agent="claude", task="do it"), "image missing"
    )
    rec = json.loads((wiz.runs_store_dir("vps", "acme") / f"{run_id}.json").read_text())
    assert rec["outcome"] == "never-started"
    assert rec["exit_code"] is None
    assert rec["repository"] is None
    assert rec["host"] == "vps"
    assert rec["task"] == "do it"
    assert rec["notes"] == ["image missing"]


def test_an_interactive_session_that_never_started_is_not_recorded(wiz):
    """`never-started` is absent from the interactive vocabulary (data-model §2),
    so a session that failed to come up is UNREPRESENTABLE rather than filed under
    a borrowed word."""
    assert wiz.record_never_started("local", "acme", wiz.ExecSpec(mode="interactive"), "x") is None
    assert wiz.stored_environments("local") == []


def test_a_failed_up_records_the_run_as_never_started(wiz, monkeypatch):
    """The wiring, not just the helper: a deploy that dies before the container
    exists is a run that never started, and only the tool can say so."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    monkeypatch.setattr(wiz, "host_container_names", lambda h, include_stopped=False: set())
    monkeypatch.setattr(wiz, "log", lambda _m: None)
    monkeypatch.setattr(
        wiz,
        "refuse_superseded_layout",
        lambda n, root=None: wiz.die("the image is not built here"),
    )
    spec = wiz.ExecSpec(mode="headless", agent="claude", task="print ok")
    with pytest.raises(wiz.Fatal):
        wiz.do_up("acme", spec=spec)
    records = wiz.stored_records("local", ["acme"])
    assert [r["outcome"] for r in records] == ["never-started"]
    assert "the image is not built here" in records[0]["notes"][0]


# --- T020/T021: `runs list` and `runs show` (C1, C2) -------------------------


@pytest.fixture
def store(wiz, monkeypatch):
    """A durable store with three records across two environments, and no drain —
    these commands are being tested as READERS."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    for env, run_id, started in (
        ("acme", "r-old", "2026-08-09T09:00:00Z"),
        ("acme", "r-new", "2026-08-09T11:00:00Z"),
        ("blog", "r-mid", "2026-08-09T10:00:00Z"),
    ):
        rec = json.loads(_record_bytes(wiz, run_id=run_id, environment=env, started_at=started))
        rec["host"] = "local"
        wiz.atomic_write_json(wiz.runs_store_dir("local", env), f"{run_id}.json", rec)
    return wiz


def test_listing_is_newest_first_across_environments(store, wiz, capsys):
    """Ordered by `started_at` and not by file mtime: mtime is when the record was
    INGESTED, and a whole host drained in one contact shares it to the second — an
    mtime ordering would sort by nothing at all while looking chronological."""
    wiz.set_json_mode(True)
    wiz.do_runs_list(None, None, True)
    payload = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in payload["data"]["runs"]] == ["r-new", "r-mid", "r-old"]


def test_listing_one_environment_lists_only_it(store, wiz, capsys):
    wiz.set_json_mode(True)
    wiz.do_runs_list("blog", None, True)
    payload = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in payload["data"]["runs"]] == ["r-mid"]


def test_an_environment_with_no_runs_says_so_in_both_modes(wiz, monkeypatch, capsys):
    """C1: an empty screen and "nothing happened" look identical, and one of them
    is a bug the operator would go looking for in the wrong place."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    said: list[str] = []
    monkeypatch.setattr(wiz, "log", said.append)
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False)
    assert any("no run records for acme" in m for m in said)
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True)
    # `unpushed` and `usage` are present and empty rather than absent (T030, T036):
    # a key that appeared only when non-empty would leave a consumer unable to tell
    # "no run committed without pushing" from "this build does not report it", and
    # the same trap holds for an aggregate whose unknown-component count vanished
    # exactly when it was zero.
    assert json.loads(capsys.readouterr().out)["data"] == {
        "runs": [],
        "unpushed": [],
        "usage": {"runs": 0, "unknown_components": 0, "by_agent": {}},
    }


def test_a_record_survives_the_environment_it_came_from(store, wiz, capsys):
    """C3/SC-001 on the read side: `stored_environments` reads the durable store
    and not the state dir, so an environment torn down last month still answers.
    Nothing here has ever written a state file for 'acme'."""
    assert wiz.host_environments("local") == []
    wiz.set_json_mode(True)
    wiz.do_runs_list(None, None, True)
    envs = {r["environment"] for r in json.loads(capsys.readouterr().out)["data"]["runs"]}
    assert envs == {"acme", "blog"}


def test_show_emits_the_record_verbatim(store, wiz, capsys):
    """C2. `runs show --json` is how an agent reads a record; a rendering step
    would make the machine-readable form a derivative of the human one rather than
    the record itself."""
    wiz.set_json_mode(True)
    wiz.do_runs_show("r-mid", None, True)
    payload = json.loads(capsys.readouterr().out)["data"]
    on_disk = json.loads((wiz.runs_store_dir("local", "blog") / "r-mid.json").read_text())
    assert payload == on_disk


def test_show_refuses_an_id_that_is_a_path(wiz, monkeypatch):
    """The id is joined to a store path. Refused, not sanitised: there is no
    legitimate run id this rejects, and a `..` reaching the join turns a read
    command into a way to read arbitrary files."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    with pytest.raises(wiz.Fatal, match="not a run id"):
        wiz.do_runs_show("../../../etc/passwd", None, True)


def test_show_names_a_missing_record_instead_of_printing_nothing(store, wiz):
    with pytest.raises(wiz.Fatal, match="no run record"):
        wiz.do_runs_show("r-absent", None, True)


def test_human_show_renders_unknown_usage_as_the_word(store, wiz, capsys):
    """C2/C9: never `0`. A false zero silently understates every total it enters,
    and a total that is quietly wrong is worse than one that admits a gap."""
    wiz.set_json_mode(False)
    wiz.do_runs_show("r-mid", None, False)
    out = capsys.readouterr().out
    assert "unknown" in out
    assert "usage" in out


def test_human_show_points_at_the_logs_rather_than_imitating_them(store, wiz, capsys):
    """C15/FR-014. The two have opposite lifetimes — the record outlives the
    container and the logs do not — so the rendering must not promise detail that
    is already gone."""
    wiz.set_json_mode(False)
    wiz.do_runs_show("r-mid", None, False)
    out = capsys.readouterr().out
    assert "agent-container logs blog" in out
    assert "summary" in out


def test_commit_without_push_is_stated_in_words(wiz):
    """C8/FR-005: the failure Constitution I exists to prevent. A renderer that
    printed `pushed: false` among nine other fields would technically contain the
    information while guaranteeing nobody reads it."""
    rows = dict(wiz.render_repository({"state": "ok", "commits": ["abc123"], "pushed": False}))
    assert "COMMITTED WITHOUT PUSHING" in rows["!! push"]


def test_no_upstream_reads_as_could_not_tell_and_never_as_did_not_push(wiz):
    """`pushed: null` is not `false`. Conflating "could not tell" with "did not
    push" would make the loudest signal in the feature unreliable in the one
    direction that matters."""
    rows = dict(wiz.render_repository({"state": "no-upstream", "commits": ["abc"], "pushed": None}))
    assert "could not tell" in rows["push"]
    assert "!! push" not in rows


# --- the `runs` group is part of the machine-readable surface ----------------


def test_both_runs_commands_take_json(wiz):
    """Feature 009's contract: a new command cannot quietly miss the
    machine-readable surface. The existing coverage test walks top-level commands
    only, so a sub-app's commands need their own assertion or they are exempt by
    accident."""
    import inspect

    group = next(g for g in wiz.app.registered_groups if g.name == "runs")
    names = set()
    for cmd in group.typer_instance.registered_commands:
        names.add(cmd.name)
        assert "as_json" in inspect.signature(cmd.callback).parameters, cmd.name
    assert names == {"list", "show"}


# --- adversarial review: the alarm must not go quiet on an UNKNOWN commit list


def test_commit_without_push_alarms_even_when_the_commit_list_is_unknown(wiz):
    """The HIGH finding from adversarial review, reproduced before it was fixed.

    `pushed: false` is computed as NOT `merge-base --is-ancestor <end_head> @{u}` —
    the exit head is PROVABLY not on the upstream, so something is outstanding by
    definition. But the writer emits `commits: []` when the list is UNKNOWN as well
    as when it is empty (unattributable history, a `rev-list` failure, or the
    exit-capture deadline expiring under SIGTERM). Classifying on `commits` read
    that as reassurance and returned "nothing to push".

    The result was SC-003's exact failure — a run whose work existed only in the
    container, reported as a clean success by the check written to prevent it.
    """
    unknown_list = {
        "state": "ok",
        "commits": [],
        "paths": [],
        "paths_truncated": True,
        "pushed": False,
        "upstream": "origin/main",
    }
    assert wiz.push_status(unknown_list) == wiz.PUSH_UNPUSHED
    assert wiz.unpushed_run_ids([{"run_id": "r1", "repository": unknown_list}]) == ["r1"]
    rendered = dict(wiz.render_repository(unknown_list))
    assert "nothing to push" not in " ".join(rendered.values()).lower()


def test_the_alarm_is_not_triggered_by_a_clean_pushed_run(wiz):
    """The positive control. Without it the assertion above passes for a build that
    alarms on everything, which would be useless in a different direction."""
    clean = {"state": "ok", "commits": ["abc"], "pushed": True, "upstream": "origin/main"}
    assert wiz.push_status(clean) == "pushed"
    assert wiz.unpushed_run_ids([{"run_id": "r2", "repository": clean}]) == []


def test_an_unknown_path_list_is_not_reported_as_no_files_changed(wiz):
    """Same shape one row down: an empty list flagged truncated is UNKNOWN, and
    "no files changed" is a definite claim about data the writer never had — in the
    same words a genuinely clean run produces, which is what makes it undetectable."""
    assert "UNKNOWN" in wiz.render_changed_paths([], True)
    assert wiz.render_changed_paths([], False) == "no files changed"


def test_no_push_row_can_claim_nothing_to_push(wiz):
    """`push_status` can no longer return "nothing", so no row may render it. Pins
    the removal: re-adding the row would resurrect the affirmative falsehood even if
    the classifier stayed correct."""
    assert "nothing" not in wiz.PUSH_ROWS
    assert all("nothing to push" not in text for _, text in wiz.PUSH_ROWS.values())
