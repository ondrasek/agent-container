"""Feature 024 FR-020/FR-020a: the interpreter cannot act, and that is provable.

THIS IS THE FEATURE'S LOAD-BEARING SECURITY PROPERTY, and it is an ABSENCE — the
kind that quietly stops being true. An interpreter reads content written by the
processes it supervises; the threat model treats a run record as the container's
own account of itself and not as evidence against an agent that set out to
misreport. An interpreter that could act on what it read would be an agent whose
instructions can be written by the thing it supervises.

Two independent guarantees, because one of them can be edited away:

  1. STRUCTURAL — the agent image installs no container runtime client, so
     `detect_runtime()` cannot resolve and every management command refuses. This
     is 017's stated reason for giving the CONTROL-PLANE image both clients,
     applied here in reverse and on purpose.
  2. COMPOSITIONAL — no mutating helper is reachable from any `interpret`
     command, walked transitively rather than observed on the paths a test
     happened to exercise.

The second is what catches the future edit that adds a call. An acceptance test
catches a mutation only when the scenario triggers it, so a reachable-but-not-yet-
called writer passes every behavioural test and fails only here.
"""

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _reachable_names(wiz, root_func) -> set[str]:
    """Every global name reachable from `root_func`, transitively.

    Lifted deliberately from `test_doctor.py` rather than imported: the two guards
    protect different properties and must be able to diverge without one quietly
    changing the other's meaning.
    """
    seen: set[str] = set()
    stack = [root_func]
    while stack:
        fn = stack.pop()
        code = getattr(fn, "__code__", None)
        if code is None:
            continue
        for n in code.co_names:
            if n in seen:
                continue
            seen.add(n)
            nxt = getattr(wiz, n, None)
            if callable(nxt) and getattr(nxt, "__module__", None) == wiz.__name__:
                stack.append(nxt)
    return seen


# The writers an interpreter must never reach. Named individually rather than
# detected by heuristic: a guard that guesses which helpers mutate is one that
# stops guessing correctly the moment a new writer is added under a different
# naming convention.
_FORBIDDEN = (
    "compose_up_exec",
    "down_container",
    "record_inventory_creation",
    "set_inventory_outcome",
    "migrate_flat_state",
    "drain_host_records",
    "deliver_secrets",
    "pin_host_key",
    "write_state",
    "write_inventory_entry",
)

_INTERPRET_COMMANDS = ("interpret_ls", "interpret_show")


def test_no_interpret_command_reaches_a_mutating_helper(wiz):
    """FR-020, compositionally."""
    for cmd in _INTERPRET_COMMANDS:
        fn = getattr(wiz, cmd)
        reachable = _reachable_names(wiz, fn)
        for forbidden in _FORBIDDEN:
            assert forbidden not in reachable, (
                f"`{cmd}` can reach `{forbidden}`. An interpreter's input is written "
                f"by the agents it supervises, so a path from a read command to a "
                f"writer is a path from agent output to a fleet change."
            )


def test_the_authority_guard_CAN_fail(wiz):
    """A guard nobody has seen fail is a guard nobody knows works.

    `do_up` really does reach the writers the previous test forbids, so the walker
    is looking at something real rather than at an empty set it computed by
    accident — which is exactly how this kind of guard rots into decoration.
    """
    reachable = _reachable_names(wiz, wiz.do_up)
    hit = [f for f in _FORBIDDEN if f in reachable]
    assert hit, (
        "the walker found NO forbidden helper reachable from do_up, which deploys "
        "containers — the guard is not looking at anything and the test above is "
        "passing vacuously"
    )


def test_the_interpret_group_has_NO_ACTING_VERB(wiz):
    """FR-020a: no dormant command surface against the future authority feature.

    A capability that exists but is switched off is one an operator cannot verify
    the absence of, and the absence is the whole property. This asserts the group's
    surface rather than its behaviour, because a command that refuses today is one
    line from a command that does not.
    """
    src = Path(wiz.__file__).read_text()
    i = src.index("interpret_app = typer.Typer(")
    j = src.index("telemetry_app = typer.Typer(", i)
    block = src[i:j]
    registered = set(re.findall(r'@interpret_app\.command\("([a-z-]+)"\)', block))
    assert registered, "no interpret commands found — the anchor above has moved"
    for verb in ("stop", "start", "run", "act", "destroy", "redeploy", "task", "apply"):
        assert verb not in registered, (
            f"`interpret {verb}` exists. FR-020a forbids a command surface that "
            f"would act if a credential were supplied later."
        )


def test_the_authority_vocabulary_has_exactly_one_value(wiz):
    """Also FR-020a, one layer down. A field that already accepted `act` would be
    a dormant path: untested, unreachable, and one edit from live."""
    assert wiz.INTERPRETER_AUTHORITIES == ("observe",)


def test_the_agent_image_installs_NO_CONTAINER_RUNTIME_CLIENT():
    """The structural half, asserted against the artifact.

    Without a client `detect_runtime()` cannot resolve and every management command
    refuses — which is why the CONTROL-PLANE image installs both, and why this one
    must not. If a future change adds docker-cli or podman-remote to the agent
    image for some unrelated convenience, every interpreter silently gains the
    ability to act and nothing else in this suite would notice.
    """
    dockerfile = (_ROOT / "image" / "Dockerfile").read_text()
    # Package installs only: the file legitimately MENTIONS both runtimes in
    # comments about build compatibility, and a bare substring search would fail
    # on prose.
    installs = re.findall(r"^\s*(?:apt-get install|&&\s*apt-get install)[^\n]*", dockerfile, re.M)
    body = "\n".join(installs)
    for client in ("docker-cli", "podman-remote", "docker.io", "podman"):
        assert client not in body, (
            f"the agent image installs `{client}`. That gives every interpreter a "
            f"path to a container daemon, and FR-020's refusal stops being "
            f"structural."
        )


def test_an_interpreter_is_never_given_the_control_plane_key(wiz):
    """The other half of "holds nothing that can act": no standing host identity.

    The control-plane keypair is minted only for ROLE_CONTROL_PLANE. This asserts
    the branch still reads that way, because an interpreter handed that key would
    satisfy every other test in this file and be able to do anything.
    """
    src = Path(wiz.__file__).read_text()
    for marker in ("CONTROL-PLANE KEY PASSPHRASE", "control_plane_permitted_hosts"):
        i = src.index(marker)
        window = src[max(0, i - 600) : i + 600]
        assert wiz.ROLE_INTERPRETER not in window and "interpreter" not in window, (
            f"the control-plane key path mentions the interpreter role near "
            f"{marker!r} — that key is not scoped to inspect"
        )


def test_the_kill_switch_SEES_an_interpreter(wiz, tmp_path, monkeypatch):
    """FR-030. `panic` acts on the INVENTORY, so a new role is covered the moment
    it is recorded there — but "covered by construction" is the kind of claim that
    is true until a selector somewhere starts filtering by role.

    Asserted against the entry the tool actually writes, rather than by reading
    `do_panic` and reasoning about it.
    """
    entry = wiz.build_inventory_entry(
        "watcher",
        "vps1",
        True,
        role=wiz.ROLE_INTERPRETER,
        watched_scope=["vps1"],
        channel="C0123456789",
        authority="observe",
    )
    assert entry["role"] == wiz.ROLE_INTERPRETER
    assert entry["outcome"] == "active"
    # The fields `panic` reads to decide what to act on, present and populated.
    assert entry["name"] == "watcher" and entry["host"] == "vps1"


def test_the_channel_id_is_VALIDATED_not_passed_through(wiz):
    """Feature 014's threat-model row rests on the inventory having NO free-text
    field: unlike a run record, whose `task` carries whatever an operator typed,
    nothing here can carry a credential structurally.

    Three operator-influenced fields were added by 024, which is exactly how such
    a property is lost by accident. The channel is constrained at the door.
    """
    assert wiz.validate_interpreter_channel_id("C0123456789", "x") == "C0123456789"
    for bad in ("", "c0123", "C", "not an id", "C0123456789'; rm -rf /", "C" * 64):
        try:
            wiz.validate_interpreter_channel_id(bad, "--slack-conversation")
        except wiz.Fatal:
            continue
        raise AssertionError(f"the inventory would have accepted {bad!r} as a channel id")


def test_the_WATCHED_SCOPE_is_validated_like_everything_else_in_the_store(wiz):
    """The claim on INVENTORY_FIELDS, made true.

    It asserted that all three fields 024 adds are validated rather than free
    text, and Feature 014's threat-model row rests on this store having no
    free-text field at all. For this field the claim was FALSE until a review
    said so: `--watch` went in verbatim, so `--watch "$(cat ~/.token)"` would have
    written a credential into the durable store the threat model says structurally
    cannot hold one.

    Worse, the test commit that followed re-asserted the property across all three
    fields while this one still had no validation — strengthening the claim
    without closing the hole, which makes a gap less likely to be noticed, not
    more.
    """
    assert wiz.validate_interpreter_scope(["vps1", "vps1/api"]) == ["vps1", "vps1/api"]
    for hostile in (
        ["vps1; rm -rf /"],
        ["../../etc/passwd"],
        ["env with spaces"],
        ["vps1/"],
        [""],
    ):
        try:
            wiz.validate_interpreter_scope(hostile)
        except wiz.Fatal:
            continue
        raise AssertionError(f"the inventory would have stored {hostile!r} verbatim")


def test_the_scope_validator_does_NOT_claim_to_detect_a_secret(wiz):
    """The limit, asserted so nobody later reads the validator as more than it is.

    An opaque alphanumeric token is a WELL-FORMED NAME. No validator can separate
    it from a hostname without knowing which hosts exist, so `--watch <token>` is
    still storable and 014's "no free-text field" describes the SHAPE of what is
    stored, not a guarantee about its meaning. Pinned as a known limit rather than
    left as an implied promise — the same way this project records what
    reconciliation does not catch.
    """
    token_shaped = "ghp0realtokenvaluegoeshere"
    assert wiz.validate_interpreter_scope([token_shaped]) == [token_shaped]


def test_the_DECLARED_SENDER_is_recorded_not_merely_demanded(wiz):
    """FR-021/SC-012. It was required at deploy, called "the admit set for an
    inbound path into something that can see your whole fleet", and then dropped:
    unvalidated, unrecorded, never delivered.

    That is verbatim the failure the role validation condemns twenty lines
    earlier — a flag that is silently inert is worse than one that is refused,
    because the operator believes they configured something. An admit set nobody
    can read back after the deploy is exactly that.
    """
    entry = wiz.build_inventory_entry(
        "watcher",
        "vps1",
        True,
        role=wiz.ROLE_INTERPRETER,
        watched_scope=["vps1"],
        channel="C0123456789",
        declared_sender="U0987654321",
        authority="observe",
    )
    assert entry["declared_sender"] == "U0987654321"
    assert "declared_sender" in wiz.INVENTORY_FIELDS


# --- the stack read path: None is not empty ---------------------------------


def _stub_query(wiz, monkeypatch, *, rc=0, out=""):
    class R:
        returncode = rc
        stdout = out
        stderr = ""

    monkeypatch.setattr(wiz, "query", lambda *a, **k: R())
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda *a, **k: ["docker"])


def test_an_UNREACHABLE_stack_reads_as_None_never_as_empty(wiz, monkeypatch):
    """FR-013, and the distinction the whole feature's honesty rests on.

    An interpreter that cannot reach its stack and one whose stack holds nothing
    must not produce the same answer. Collapsing them lets "I could not look"
    become "nothing happened", which is the false green 023 exists to kill,
    arriving on the operator's phone with a supervisor's credibility attached.
    """
    _stub_query(wiz, monkeypatch, rc=7, out="")
    assert wiz.stack_query_lines({}, "c", '{x="y"}') is None

    # A body that is not JSON is UNREACHABLE too — a truncated or error response
    # must not read as an empty store.
    _stub_query(wiz, monkeypatch, rc=0, out="<html>502 Bad Gateway</html>")
    assert wiz.stack_query_lines({}, "c", '{x="y"}') is None

    # Well-formed and genuinely empty is EMPTY, and that is a different answer.
    _stub_query(wiz, monkeypatch, rc=0, out='{"data":{"result":[]}}')
    assert wiz.stack_query_lines({}, "c", '{x="y"}') == []


def test_lines_come_back_in_time_order_with_their_labels(wiz, monkeypatch):
    """Ordering is not cosmetic: an interpretation quotes spans of output, and a
    span assembled out of order would misrepresent what the agent did."""
    body = json.dumps(
        {
            "data": {
                "result": [
                    {"stream": {"agent_container_run_id": "r1"}, "values": [["20", "later"]]},
                    {"stream": {"agent_container_run_id": "r1"}, "values": [["10", "earlier"]]},
                ]
            }
        }
    )
    _stub_query(wiz, monkeypatch, rc=0, out=body)
    got = wiz.stack_query_lines({}, "c", '{x="y"}')
    assert [e["line"] for e in got] == ["earlier", "later"]
    assert got[0]["labels"]["agent_container_run_id"] == "r1"


def test_a_malformed_entry_is_SKIPPED_rather_than_misread(wiz, monkeypatch):
    """016's rule for a record whose schema this build does not understand:
    refuse it rather than guess at its shape."""
    body = json.dumps(
        {"data": {"result": [{"stream": {}, "values": [["10", "ok"], ["bad"], "nonsense"]}]}}
    )
    _stub_query(wiz, monkeypatch, rc=0, out=body)
    assert [e["line"] for e in wiz.stack_query_lines({}, "c", '{x="y"}')] == ["ok"]
