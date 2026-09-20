"""Feature 006/024: an interpreter is DECLARABLE, and declares no less than it must.

Until this, `container.role` was refused by the spec validator while `role` was
already inheritable and already readable off a running container — so an
interpreter and a control plane could only be created imperatively. A feature
reachable from one surface and not the other is one half the users never see.

THE RISK THIS CREATES is the reason most of these tests are refusals. The
imperative path refuses an interpreter without a stack, and a Slack channel
without a conversation and a declared sender. If the declarative path is looser,
a spec becomes the way to obtain a deployment the tool would otherwise decline:
the surface splits, and the weaker half wins.
"""

import pytest

pytestmark = pytest.mark.usefixtures("wiz")


def _env(**kw):
    base = {"name": "watcher", "host": "local", "container": {"role": "interpreter"}}
    base.update(kw)
    return base


def _ok(wiz, env):
    wiz.validate_environment(env, "environments[0]")


def _refused(wiz, env, *, saying):
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_environment(env, "environments[0]")
    assert saying in str(e.value), f"refused, but not for the stated reason: {e.value}"


# --- the role itself --------------------------------------------------------


def test_a_role_is_accepted_in_the_container_block(wiz):
    _ok(wiz, _env(interpreter={"stack": "obs", "watch": ["local"]}))


def test_an_unknown_role_is_refused_naming_the_allowed_set(wiz):
    _refused(wiz, _env(container={"role": "overlord"}), saying="not one of")


def test_an_ordinary_agent_environment_still_needs_no_role(wiz):
    """The default must keep working untouched: every existing spec in the world
    omits this field, and they all mean `agent`."""
    _ok(wiz, {"name": "a", "host": "local", "container": {"mode": "headless"}})


# --- what an interpreter must declare ---------------------------------------


def test_an_interpreter_without_an_interpreter_block_is_refused(wiz):
    """A stack is REQUIRED imperatively (`--stack` is not optional), so it is
    required here. An interpreter with nothing to read is not a smaller
    interpreter, it is one that reports an empty fleet as a quiet one."""
    _refused(wiz, _env(), saying="requires an 'interpreter:' block")


def test_an_interpreter_without_a_stack_is_refused(wiz):
    _refused(wiz, _env(interpreter={"watch": ["local"]}), saying="interpreter.stack is required")


def test_a_watch_list_must_be_a_list_of_names(wiz):
    _refused(
        wiz,
        _env(interpreter={"stack": "obs", "watch": "local"}),
        saying="must be a list",
    )


def test_an_empty_watch_is_allowed_because_it_is_DECLARED(wiz):
    """Absent, declared-empty and defaulted are three different things
    (Constitution VIII). Deploying with no scope already prints that there will
    be nothing to interpret; refusing it here would make the spec unable to
    express a choice the CLI accepts."""
    _ok(wiz, _env(interpreter={"stack": "obs", "watch": []}))


# --- the Slack channel's admit set ------------------------------------------


def test_the_slack_channel_requires_a_conversation_and_a_declared_sender(wiz):
    """FR-023: there is no value that admits everyone, and a spec is exactly
    where an absent field gets read as 'fine'."""
    for missing in ("slack_conversation", "declared_sender"):
        block = {
            "stack": "obs",
            "channel": "slack",
            "slack_conversation": "C0123456789",
            "declared_sender": "U0987654321",
        }
        del block[missing]
        _refused(wiz, _env(interpreter=block), saying=f"interpreter.{missing} is required")


def test_the_cli_channel_needs_neither(wiz):
    _ok(wiz, _env(interpreter={"stack": "obs", "channel": "cli"}))


def test_an_unknown_channel_is_refused(wiz):
    _refused(
        wiz, _env(interpreter={"stack": "obs", "channel": "carrier-pigeon"}), saying="not one of"
    )


# --- the block belongs to the role ------------------------------------------


def test_an_interpreter_block_on_a_plain_agent_is_REFUSED_not_ignored(wiz):
    """Ignoring it would leave an operator believing their fleet is watched by
    something that is not watching it."""
    _refused(
        wiz,
        {
            "name": "a",
            "host": "local",
            "container": {"mode": "headless"},
            "interpreter": {"stack": "obs", "watch": ["local"]},
        },
        saying="only valid with container.role: interpreter",
    )


def test_an_unknown_interpreter_key_is_refused(wiz):
    _refused(
        wiz,
        _env(interpreter={"stack": "obs", "listen_port": 8080}),
        saying="unknown interpreter key",
    )


# --- the declared spec reaches the SAME ExecSpec the CLI builds --------------


def test_the_declared_fields_reach_the_exec_spec(wiz):
    """Both routes must converge before anything is validated or deployed, or
    each grows behaviour the other lacks."""
    spec = wiz.env_exec_spec(
        _env(
            container={"role": "interpreter", "mode": "interactive"},
            interpreter={
                "stack": "obs",
                "watch": ["vps1", "vps1/demo"],
                "channel": "slack",
                "slack_conversation": "C0123456789",
                "declared_sender": "U0987654321",
            },
        )
    )
    assert spec.role == "interpreter"
    assert spec.stack == "obs"
    assert spec.watch == ["vps1", "vps1/demo"]
    assert spec.channel == "slack"
    assert spec.slack_conversation == "C0123456789"
    assert spec.declared_sender == "U0987654321"
    spec.validate()  # the imperative path's own checks must also pass


def test_a_plain_environment_gets_the_exec_spec_defaults(wiz):
    spec = wiz.env_exec_spec({"name": "a", "host": "local", "container": {}})
    assert spec.role == wiz.ROLE_AGENT
    assert spec.stack is None and spec.watch == []


# --- drift ------------------------------------------------------------------


def test_a_changed_role_is_reported_as_drift(wiz):
    """An environment redeclared from interpreter to agent GAINED an agent and a
    credential path. Reporting that as matching hides a privilege change behind
    an unchanged name."""
    diffs = wiz.config_drift({"role": "agent"}, {"role": "interpreter"})
    assert ("role", "agent", "interpreter") in diffs


def test_a_container_deployed_before_roles_existed_is_not_drifted(wiz):
    """It carries no AGENT_CONTAINER_ROLE, and absent means `agent` — the default
    it was deployed under. Without this every pre-024 container reports drift on
    a field nobody touched, and a status that cries drift stops being read."""
    assert wiz.config_drift({"role": "agent"}, {"role": None}) == []
