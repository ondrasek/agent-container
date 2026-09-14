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
