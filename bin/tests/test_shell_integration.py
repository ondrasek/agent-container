"""Feature 005 (shell integration) unit tests — hermetic, no live runtime.

Cover the compute-action-then-realize seam: the ShellAction, the per-dialect
renderers (posix/fish/pwsh) and their eval-safe quoting (POSIX proven by a real
`sh -c` eval round-trip; fish/pwsh by their documented quoting rules), the
stdout/stderr/exit discipline, print==execute parity, the no-secret invariant,
and the `host env` emitter (var per driver / --endpoint / name-free --unset /
registry-only, unknown-host).

Requirement anchors are named in the test bodies (FR-###/SC-###).
"""

from __future__ import annotations

import subprocess

import pytest

DOCKER_HOST_REC = {
    "driver": "docker",
    "context": "agent-container-hz1",
    "address": "vps.example.com",
}
PODMAN_HOST_REC = {"driver": "podman", "context": "acp", "address": "10.0.0.5"}

ADVERSARIAL = ["a b", "a;rm -rf ~", "$(touch pwned)", "a'b\"c", "back\\slash", "$env:x", "líbë"]


# --- quoting: real POSIX eval round-trip (FR-004) ----------------------------


def _posix_eval_var(wiz, token: str) -> str:
    """Render `export X=<token>` for POSIX, eval it in a real sh, echo $X back.
    If quoting is eval-safe, the echoed value equals the original token exactly."""
    rendered = wiz.render_action(wiz.ShellAction(env_set=[("X", token)]), "posix")
    r = subprocess.run(["sh", "-c", rendered + '\nprintf %s "$X"'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("token", ADVERSARIAL)
def test_posix_quoting_is_eval_safe(wiz, token):
    assert _posix_eval_var(wiz, token) == token  # no word-split, no injection, no expansion


def _posix_eval_side_effect_free(wiz, token: str, tmp_path) -> bool:
    """A malicious token must not execute anything when eval'd."""
    marker = tmp_path / "pwned"
    rendered = wiz.render_action(wiz.ShellAction(env_set=[("X", token)]), "posix")
    subprocess.run(["sh", "-c", rendered], capture_output=True, text=True, cwd=tmp_path)
    return not marker.exists()


def test_posix_injection_does_not_execute(wiz, tmp_path):
    assert _posix_eval_side_effect_free(wiz, "$(touch pwned)", tmp_path)
    assert _posix_eval_side_effect_free(wiz, "x; touch pwned", tmp_path)


def test_fish_quoting_escapes_backslash_and_quote(wiz):
    # fish single-quote: backslash and single-quote are backslash-escaped.
    assert wiz._quote_fish("a b") == "'a b'"
    assert wiz._quote_fish("a'b") == "'a\\'b'"
    assert wiz._quote_fish("a\\b") == "'a\\\\b'"


def test_pwsh_quoting_doubles_single_quote(wiz):
    assert wiz._quote_pwsh("a b") == "'a b'"
    assert wiz._quote_pwsh("a'b") == "'a''b'"
    assert wiz._quote_pwsh("$env:x") == "'$env:x'"  # single quotes suppress expansion


# --- render_action per dialect -----------------------------------------------


def test_render_posix_env_and_command(wiz):
    a = wiz.ShellAction(
        env_set=[("DOCKER_CONTEXT", "hz1")], commands=[["ssh", "dev@h", "-p", "22"]]
    )
    assert wiz.render_action(a, "posix") == "export DOCKER_CONTEXT=hz1\nssh dev@h -p 22\n"


def test_render_fish_env_and_unset(wiz):
    a = wiz.ShellAction(env_set=[("DOCKER_CONTEXT", "hz1")], env_unset=["DOCKER_HOST"])
    # fish quoter always wraps in single quotes (safe).
    assert wiz.render_action(a, "fish") == "set -x DOCKER_CONTEXT 'hz1'\nset -e DOCKER_HOST\n"


def test_render_pwsh_env_unset_and_command(wiz):
    a = wiz.ShellAction(
        env_set=[("DOCKER_CONTEXT", "hz1")], env_unset=["DOCKER_HOST", "CONTAINER_HOST"]
    )
    out = wiz.render_action(a, "pwsh")
    assert "$env:DOCKER_CONTEXT = 'hz1'" in out
    assert "Remove-Item Env:DOCKER_HOST,Env:CONTAINER_HOST -ErrorAction SilentlyContinue" in out


def test_render_pwsh_command_leaves_executable_unquoted(wiz):
    # In pwsh a quoted string at statement start is a value, not an invocation.
    a = wiz.ShellAction(commands=[["ssh", "dev@h", "-p", "2206"]])
    out = wiz.render_action(a, "pwsh")
    assert out.startswith("ssh 'dev@h' '-p' '2206'")


def test_render_empty_action_is_empty_string(wiz):
    assert wiz.render_action(wiz.ShellAction(), "posix") == ""


def test_render_bad_dialect_dies(wiz):
    with pytest.raises(wiz.Fatal, match="--shell must be one of"):
        wiz.render_action(wiz.ShellAction(env_set=[("X", "y")]), "csh")


def test_render_is_idempotent(wiz):
    # SC-005: rendering the same action twice is byte-identical, no side effect.
    a = wiz.ShellAction(env_set=[("DOCKER_CONTEXT", "hz1")])
    assert wiz.render_action(a, "posix") == wiz.render_action(a, "posix")


# --- attach print + parity (FR-006/FR-007/FR-010) ----------------------------


def test_attach_action_is_the_ssh_argv(wiz):
    # FR-010 parity: the print action's command IS exactly ssh_argv's output.
    assert wiz.attach_shell_action("dev", "localhost", "2206").commands[0] == wiz.ssh_argv(
        "dev", "localhost", "2206"
    )
    assert wiz.attach_shell_action("dev", "localhost", "2206", "edit").commands[0] == wiz.ssh_argv(
        "dev", "localhost", "2206", "edit"
    )


def test_cli_attach_print_emits_only_the_command(wiz, capsys):
    wiz.write_state("local", "acme", 2206)
    wiz.cli_attach("acme", "local", None, None, print_mode=True, shell="posix")
    out = capsys.readouterr()
    assert out.out == "ssh dev@localhost -p 2206 -t tmux attach -t main\n"  # only the command


def test_cli_attach_print_unknown_target_empty_stdout_nonzero(wiz, capsys):
    with pytest.raises(wiz.Fatal):
        wiz.cli_attach("nope", "local", None, None, print_mode=True)
    assert capsys.readouterr().out == ""  # eval-safe: nothing on stdout on error


def test_cli_attach_ssh_config_stanza(wiz, capsys):
    wiz.write_state("local", "acme", 2206)
    wiz.cli_attach("acme", "local", None, None, ssh_config=True)
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "Host acme",
        "    HostName localhost",
        "    User dev",
        "    Port 2206",
        "    RequestTTY yes",
        "    RemoteCommand tmux attach -t main",
    ]


# --- host env (FR-008/FR-008a) -----------------------------------------------


def test_host_env_action_docker_default_context(wiz):
    a = wiz.host_env_action(DOCKER_HOST_REC, endpoint=False)
    assert a.env_set == [("DOCKER_CONTEXT", "agent-container-hz1")]


def test_host_env_action_podman_default_connection(wiz):
    a = wiz.host_env_action(PODMAN_HOST_REC, endpoint=False)
    assert a.env_set == [("CONTAINER_CONNECTION", "acp")]


def test_host_env_action_endpoint_form(wiz):
    assert wiz.host_env_action(DOCKER_HOST_REC, endpoint=True).env_set == [
        ("DOCKER_HOST", "ssh://vps.example.com")
    ]
    assert wiz.host_env_action(PODMAN_HOST_REC, endpoint=True).env_set == [
        ("CONTAINER_HOST", "ssh://10.0.0.5")
    ]


def test_host_env_action_endpoint_uses_ssh_context_verbatim(wiz):
    rec = {"driver": "docker", "context": "ssh://ops@vps:22", "address": "vps"}
    assert wiz.host_env_action(rec, endpoint=True).env_set == [("DOCKER_HOST", "ssh://ops@vps:22")]


def test_host_env_endpoint_strips_password_from_ssh_uri(wiz):
    # Constitution III: a password in an ssh:// context must NEVER reach stdout.
    rec = {"driver": "docker", "context": "ssh://ops:hunter2@vps:22", "address": "vps"}
    action = wiz.host_env_action(rec, endpoint=True)
    assert action.env_set == [("DOCKER_HOST", "ssh://ops@vps:22")]
    assert "hunter2" not in wiz.render_action(action, "posix")


def test_host_env_action_attach_only_driver_dies(wiz):
    with pytest.raises(wiz.Fatal, match="attach-only"):
        wiz.host_env_action(
            {"driver": "existing-ssh", "context": "", "address": "h"}, endpoint=False
        )


def test_cli_host_env_unset_clears_all_four_vars(wiz, capsys):
    # FR-008a: name-free, all four candidate vars.
    wiz.cli_host_env(None, endpoint=False, unset=True, shell="posix")
    assert capsys.readouterr().out == "unset " + " ".join(wiz.HOST_ENV_VARS) + "\n"


def test_cli_host_env_unknown_host_empty_stdout_nonzero(wiz, make_registry, capsys):
    make_registry({"hosts": {}})
    with pytest.raises(wiz.Fatal, match="unknown host"):
        wiz.cli_host_env("ghost", endpoint=False, unset=False, shell="posix")
    assert capsys.readouterr().out == ""


def test_cli_host_env_registry_only_no_subprocess(wiz, make_registry, monkeypatch, capsys):
    # FR-005: producing the output connects to nothing — no subprocess is spawned.
    make_registry({"hosts": {"hz1": DOCKER_HOST_REC}})
    monkeypatch.setattr(
        wiz.subprocess, "run", lambda *a, **k: pytest.fail("host env must not spawn a subprocess")
    )
    wiz.cli_host_env("hz1", endpoint=False, unset=False, shell="posix")
    assert capsys.readouterr().out == "export DOCKER_CONTEXT=agent-container-hz1\n"


def test_cli_host_env_bad_shell_dies_empty_stdout(wiz, capsys):
    with pytest.raises(wiz.Fatal, match="--shell must be one of"):
        wiz.cli_host_env(None, endpoint=False, unset=True, shell="tcsh")
    assert capsys.readouterr().out == ""


def test_cli_host_env_requires_name_without_unset(wiz):
    with pytest.raises(wiz.Fatal, match="NAME is required"):
        wiz.cli_host_env(None, endpoint=False, unset=False, shell="posix")


# --- no-secret invariant (Constitution III) ----------------------------------


def test_no_secret_in_host_env_output(wiz, make_registry, capsys):
    # A host record that (hypothetically) also carried a secret must never see it
    # rendered — only the context/endpoint coordinate is emitted.
    rec = {**DOCKER_HOST_REC, "token": "SUPER-SECRET-TOKEN", "automation_key": "PRIVATE"}
    make_registry({"hosts": {"hz1": rec}})
    wiz.cli_host_env("hz1", endpoint=False, unset=False, shell="posix")
    out = capsys.readouterr().out
    assert "SUPER-SECRET-TOKEN" not in out and "PRIVATE" not in out
    assert out == "export DOCKER_CONTEXT=agent-container-hz1\n"
