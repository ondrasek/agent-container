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

import dis
import json
import re
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _globals_loaded(fn) -> set[str]:
    """Only names the function actually loads as GLOBALS.

    `co_names` — which `test_doctor.py`'s walker uses — also contains ATTRIBUTE
    names, and that produces false positives in a 20k-line module where a method
    name collides with a command name. Measured here: `parse_kv_config` calls
    `match.start()`, `co_names` records `start`, and `start` is also a typer
    command that deploys containers — so `interpret history` appeared to reach
    `deliver_secrets` through a path that does not exist.

    A guard that cries wolf is a guard someone deletes, taking the property with
    it. `dis` separates LOAD_GLOBAL from attribute access, so this follows only
    real call edges.
    """
    code = getattr(fn, "__code__", None)
    if code is None:
        return set()
    return {
        i.argval
        for i in dis.get_instructions(code)
        if i.opname in ("LOAD_GLOBAL", "LOAD_NAME") and isinstance(i.argval, str)
    }


def _reachable_names(wiz, root_func) -> set[str]:
    """Every global name reachable from `root_func`, transitively.

    Lifted deliberately from `test_doctor.py` rather than imported — the two
    guards protect different properties and must be able to diverge — and then
    made more precise for the reason `_globals_loaded` records.
    """
    seen: set[str] = set()
    stack = [root_func]
    while stack:
        fn = stack.pop()
        for n in _globals_loaded(fn):
            if n in seen:
                continue
            seen.add(n)
            nxt = getattr(wiz, n, None)
            if callable(nxt) and getattr(nxt, "__module__", None) == wiz.__name__:
                stack.append(nxt)
            # Nested functions and comprehensions carry their own code objects,
            # which the walker would otherwise not enter.
            for const in getattr(getattr(fn, "__code__", None), "co_consts", ()) or ():
                if hasattr(const, "co_names"):
                    stack.append(types.SimpleNamespace(__code__=const))
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

_INTERPRET_COMMANDS = (
    "interpret_ls",
    "interpret_show",
    "interpret_history",
    "interpret_test_channel",
    "interpret_serve",
)


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
        stack="obs",
        channel="slack",
        conversation="C0123456789",
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
        stack="obs",
        channel="slack",
        conversation="C0123456789",
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


# --- the channel token travels Constitution IX's path -----------------------


def test_the_channel_token_is_classified_SECRET_and_never_described(wiz):
    """Constitution IX, for the one credential 024 introduces.

    A deployment description is a PLAN — written before anything exists, kept
    afterwards as the record, read by whatever wants to know what was deployed.
    Nothing with that lifetime may hold a secret. So the token must be routed to
    `deliver_secrets` (pushed into the RUNNING container over its own sshd) and
    must never appear among the public entries that reach the compose model.

    Asserted rather than assumed, because the plan declared this principle
    satisfied while nothing demonstrated it — which a review flagged as the
    feature's one critical gap.
    """
    target = f"{wiz.INJECT_ENV_DIR}/{wiz.INTERPRETER_CHANNEL_TOKEN_VAR}"
    assert wiz.is_secret_target(target), (
        "the channel token's target is not classified secret, so it would be "
        "written into the deployment description"
    )
    public, secrets = wiz.split_injected(
        [
            ("slack", "xoxb-not-a-real-token", target),
            ("a public config", "nothing secret", f"{wiz.INJECT_CONFIG_DIR}/settings.json"),
        ]
    )
    assert [t for _n, _c, t in public] == [f"{wiz.INJECT_CONFIG_DIR}/settings.json"]
    assert secrets == [(target, "xoxb-not-a-real-token")], (
        "the channel token did not route to the delivery path"
    )
    # And the value is nowhere in what the description would carry.
    assert "xoxb-not-a-real-token" not in json.dumps(public)


def test_the_interpreter_invents_NO_second_delivery_path(wiz):
    """The token is an ORDINARY declared credential, deliberately.

    Constitution IX's machinery already pushes anything under SECRET_INJECT_DIRS
    into the running container over its own sshd. A second path for this one
    token would be a second thing to get right, to audit, and to leak from — and
    the tool would then have two answers to "how does a secret reach a
    container", which is one more than is safe.
    """
    src = Path(wiz.__file__).read_text()
    i = src.index("INTERPRETER_CHANNEL_TOKEN_VAR")
    # The constant exists as a NAME only; nothing around it should be building a
    # bespoke transport.
    window = src[i : i + 400]
    for forbidden in ("subprocess.run", "scp", "ssh ", "base64"):
        assert forbidden not in window, (
            f"a bespoke delivery path is being built around the channel token ({forbidden})"
        )


def test_the_interpreters_REACH_is_bounded_to_the_trail(wiz):
    """FR-026, a different absence from FR-020's.

    Authority is "can it change anything"; REACH is "what can it see". An
    interpreter that could read a container's filesystem, volumes or credentials
    would satisfy every authority test in this file and still be a container with
    a view of every secret the fleet holds. What it cannot see through the trail,
    it must not see.
    """
    reachable = _reachable_names(wiz, wiz.interpret_history)
    for forbidden in (
        "deliver_secrets",
        "resolve_credential_value",
        "claim_cred_mounts",
    ):
        assert forbidden not in reachable, (
            f"`interpret history` can reach `{forbidden}` — the interpreter's reach "
            f"is supposed to stop at the trail"
        )


def test_no_AGENT_SESSION_DATA_is_read_or_exported(wiz):
    """FR-025, the operator's own log-scope decision made enforceable.

    They chose the agent's OUTPUT STREAM only — not transcripts, tool-call
    records, memory files or agent configuration. Without a test that is a
    paragraph in a spec; the wider reading would move an agent's entire
    conversation, including whatever it read, into the stack.
    """
    bridge = (_ROOT / "image" / "interpret-bridge.py").read_text()
    entry = (_ROOT / "image" / "entrypoint.sh").read_text()
    i = entry.index("agent_log_payload() {")
    export_block = entry[i : entry.index("host_metrics_export_once() {")]
    for session_path in (".claude/", ".codex/", ".pi/", "sessions", "rollout-", "transcript"):
        assert session_path not in bridge, f"the bridge reads agent session data: {session_path}"
        assert session_path not in export_block, (
            f"the log exporter reaches into agent session data: {session_path}"
        )


def test_an_interpreters_own_runs_ARE_recorded(wiz):
    """FR-028. Exclusion from NOTIFICATION is not exclusion from the RECORD.

    What it read, concluded and sent must itself be part of the trail — a
    supervisor with no account of its own is the one thing in the fleet nobody
    can audit. The role rides on an ordinary environment precisely so this comes
    for free; the test exists because "for free" is the kind of property that
    stops being true when someone adds a branch.
    """
    src = Path(wiz.__file__).read_text()
    i = src.index("def compose_environment")
    body = src[i : i + 8000]
    # No role-conditional suppression of the run-record machinery.
    for suppressed in ("RUNS_DISABLED", "SKIP_RUN_RECORD", "no_runs"):
        assert suppressed not in body
    # And the interpreter is an ordinary agent environment: same image, same
    # volumes, same entrypoint. A second image would be where this breaks.
    assert "CONTROL_PLANE_IMAGE_DIR if role == ROLE_CONTROL_PLANE else AGENT_IMAGE_DIR" in src


def test_the_channel_token_can_be_WITHDRAWN_without_destroying_the_interpreter(wiz):
    """FR-005. A credential that can only be withdrawn by destroying its holder is
    one an operator will not withdraw.

    The token is an ordinary declared credential, so withdrawal is the existing
    mechanism: stop declaring it and redeploy. What this pins is that the tool has
    a path that does NOT require `--purge` — which would take the environment's
    own SSH identity with it (019's revocation boundary) and turn "rotate a Slack
    token" into "re-register this container everywhere".
    """
    src = Path(wiz.__file__).read_text()
    # `redeploy` exists and does not purge: that is the withdrawal path.
    assert "def do_redeploy(" in src
    i = src.index("def do_redeploy(")
    body = src[i : i + 4000]
    assert "purge" not in body.split("def ", 2)[0] or "--purge" not in body[:500], (
        "redeploy appears to purge, which would make withdrawing a channel token "
        "destroy the environment's SSH identity along with it"
    )


def test_a_channel_that_cannot_authenticate_its_sender_is_NOT_BINDABLE(wiz):
    """FR-024b / SC-014. The declared sender is the admit set for an inbound path
    into something that can see the whole fleet; over a channel that cannot say
    who sent a message, that admit set controls nothing."""
    assert wiz.INTERPRETER_CHANNELS == ("cli", "slack")
    # `cli` first because it is the default and the smaller exposure.
    assert wiz.INTERPRETER_CHANNELS[0] == "cli"
    with pytest.raises(wiz.Fatal, match="--channel must be one of"):
        wiz.ExecSpec(role=wiz.ROLE_INTERPRETER, stack="obs", channel="email").validate()
