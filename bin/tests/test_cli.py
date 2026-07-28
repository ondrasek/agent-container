"""CLI behavior: exit codes, help, unknown subcommands, and the non-TTY guard.

In-process tests drive the Typer app with CliRunner; two subprocess smoke
tests exercise the real `#!/usr/bin/env -S uv run --script` entry path
(skipped when uv is not installed).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest
from conftest import SCRIPT_PATH
from typer.testing import CliRunner

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_CHARS = "│╭╮╰╯─"


def combined_output(result) -> str:
    """stdout + stderr regardless of the installed click version."""
    parts = [result.output]
    try:
        parts.append(result.stderr)
    except ValueError, AttributeError:
        pass  # click<8.2 mixes stderr into .output already
    return "".join(parts)


def flat_output(result) -> str:
    """combined_output with ANSI colors, Rich box borders, and line wrapping
    normalized to single spaces. Rich (typer>=0.12) renders BadParameter errors
    in a fixed-width box and *wraps* long values, which splits phrases like
    'does not exist' across `│`-bordered lines — brittle for substring asserts.
    Flattening rejoins space-separated words regardless of where the box wraps."""
    text = _ANSI_RE.sub("", combined_output(result))
    text = text.translate({ord(c): " " for c in _BOX_CHARS})
    return re.sub(r"\s+", " ", text)


# --- help / unknown subcommand -----------------------------------------------


def test_help_exits_zero(wiz):
    result = runner.invoke(wiz.app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    for sub in ("build", "up", "down", "list", "attach", "logs", "purge", "menu", "completions"):
        assert sub in result.output


@pytest.mark.parametrize(
    "sub", ["up", "down", "attach", "logs", "list", "build", "purge", "completions"]
)
def test_subcommand_help_exits_zero(wiz, sub):
    result = runner.invoke(wiz.app, [sub, "--help"])
    assert result.exit_code == 0


def test_unknown_subcommand_exits_nonzero(wiz):
    result = runner.invoke(wiz.app, ["frobnicate"])
    assert result.exit_code != 0
    assert "Traceback" not in combined_output(result)


def test_attach_local_and_remote_are_mutually_exclusive(wiz):
    result = runner.invoke(wiz.app, ["attach", "acme", "--local", "--remote"])
    assert result.exit_code != 0
    assert "mutually exclusive" in combined_output(result)


def test_up_rejects_missing_env_file_option(wiz, tmp_path):
    result = runner.invoke(wiz.app, ["up", "acme", "--env-file", str(tmp_path / "nope.env")])
    assert result.exit_code != 0
    # flat_output: the boxed BadParameter error wraps the (long) tmp path, so the
    # substring must be matched against wrap-normalized text (see flat_output).
    assert "does not exist" in flat_output(result)


def test_fatal_errors_surface_as_fatal_not_traceback(wiz):
    # `attach --local` with no state file raises Fatal; the script's __main__
    # guard turns it into `FATAL: ...` + exit 1 (asserted end-to-end below in
    # test_script_fatal_exits_one_via_uv). In-process we assert the type.
    result = runner.invoke(wiz.app, ["attach", "acme", "--local"])
    assert result.exit_code == 1
    assert isinstance(result.exception, wiz.Fatal)
    assert "no local state for acme" in str(result.exception)
    assert "Traceback" not in combined_output(result)


# --- non-TTY wizard guard -------------------------------------------------------


def test_wizard_loop_refuses_non_tty(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "is_tty", lambda: False)
    assert wiz.wizard_loop() == 2


def test_bare_invocation_without_tty_exits_2_with_hint(wiz):
    # CliRunner stdin/stdout are pipes, so is_tty() is False organically.
    result = runner.invoke(wiz.app, [])
    assert result.exit_code == 2
    out = combined_output(result)
    assert "no TTY" in out
    assert "--help" in out  # the hint points at the scriptable CLI
    assert "Traceback" not in out


def test_down_without_yes_refuses_on_non_tty(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(wiz, "quadlet_active", lambda name: False)
    result = runner.invoke(wiz.app, ["down", "acme"])
    assert result.exit_code == 2
    assert "-y/--yes" in combined_output(result)


# --- completions subcommand --------------------------------------------------------


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_completions_prints_checked_in_script(wiz, shell):
    result = runner.invoke(wiz.app, ["completions", shell])
    assert result.exit_code == 0
    expected = (wiz.REPO_ROOT / "completions" / f"agent-container.{shell}").read_text()
    assert result.output == expected


def test_completions_invalid_shell_is_fatal_not_traceback(wiz):
    result = runner.invoke(wiz.app, ["completions", "fish"])
    assert result.exit_code == 1
    assert isinstance(result.exception, wiz.Fatal)
    assert "usage: agent-container completions <bash|zsh>" in str(result.exception)
    assert "Traceback" not in combined_output(result)


def test_completions_missing_arg_is_fatal(wiz):
    result = runner.invoke(wiz.app, ["completions"])
    assert result.exit_code == 1
    assert isinstance(result.exception, wiz.Fatal)


# --- self-test interop corpus ------------------------------------------------------


def test_self_test_passes(wiz):
    result = runner.invoke(wiz.app, ["--self-test"])
    assert result.exit_code == 0
    assert "PASS" in result.output


def test_version_prints_semver(wiz):
    # Single-sourced from pyproject.toml (via REPO_ROOT here); assert the SHAPE,
    # not a literal value, so release bumps don't break the test.
    result = runner.invoke(wiz.app, ["--version"])
    assert result.exit_code == 0
    assert re.fullmatch(r"\d+\.\d+\.\d+(\+\w+)?", result.output.strip()), result.output


# --- real entrypoint smoke tests (shebang -> uv run --script) ------------------------

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")


@needs_uv
def test_script_help_via_uv(tmp_path):
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Usage" in proc.stdout


@needs_uv
def test_script_bare_non_tty_via_uv(tmp_path):
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    assert proc.returncode == 2
    assert "no TTY" in proc.stderr
    assert "Traceback" not in proc.stderr


@needs_uv
def test_script_fatal_exits_one_via_uv(tmp_path):
    # Isolated HOME/XDG: no state file for 'acme' can possibly exist.
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    for var in ("AGENT_CONTAINER_RUNTIME", "AGENT_CONTAINER_HOST", "AGENT_CONTAINER_USER"):
        env.pop(var, None)
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH), "attach", "acme", "--local"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
        env=env,
    )
    assert proc.returncode == 1
    assert "FATAL: no local state for acme" in proc.stderr
    assert "Traceback" not in proc.stderr


def _short_flag_offenders(wiz) -> list[str]:
    """Every (command, param) whose option declares a short flag but no long one."""
    import inspect

    commands = list(wiz.app.registered_commands)
    for g in wiz.app.registered_groups:  # a sub-app's own commands count too
        commands += list(g.typer_instance.registered_commands)

    offenders: list[str] = []
    for cmd in commands:
        cb = cmd.callback
        if cb is None:
            continue
        for pname, param in inspect.signature(cb).parameters.items():
            decls = getattr(param.default, "param_decls", None) or ()
            shorts = [d for d in decls if re.fullmatch(r"-[a-zA-Z]", d)]
            longs = [d for d in decls if d.startswith("--")]
            if shorts and not longs:
                offenders.append(f"{cmd.name or cb.__name__}:{pname} declares {shorts}")
    return offenders


def test_every_short_flag_has_a_long_form(wiz):
    """Project convention: a short flag MUST always be accompanied by a long one.

    Short flags are scarce, collide easily and read as noise in scripts and docs;
    the long form is the name, the short one is a convenience. Enforced here so it
    stays true as commands are added — the same treatment the supported-agent and
    command lists get, rather than relying on reviewer memory.
    """
    assert not (o := _short_flag_offenders(wiz)), (
        "short flags with no long form:\n  " + "\n  ".join(o)
    )


def test_the_short_flag_check_actually_catches_a_violation(wiz, monkeypatch):
    """The convention test above passes today because the codebase complies. This
    proves it would FAIL if it stopped complying — a passing test that cannot fail
    is worse than no test, and this project has been bitten by exactly that."""
    import typer

    @wiz.app.command("temp-violator")
    def _violator(bad: bool = typer.Option(False, "-Z", help="short only, no long form")):
        pass

    try:
        offenders = _short_flag_offenders(wiz)
        assert any("-Z" in o for o in offenders), f"the check missed a violation: {offenders}"
    finally:
        wiz.app.registered_commands[:] = [
            c for c in wiz.app.registered_commands if c.name != "temp-violator"
        ]


# --- Feature 011: repeatable -e/--env-file (FR-001d, contract C2a) -----------


def test_env_file_option_is_repeatable_and_stacks_in_order(wiz, tmp_path):
    """Multiple `-e` stack in the order given, later winning on conflicting keys.

    The ordering is not logic of ours: the compose model emits `env_file:` as a
    list and Compose applies it in order with later entries winning (research
    R2b). This asserts the list reaches the model in the order the operator gave
    — reversing it would silently invert precedence.
    """
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    a.write_text("A=1\nB=1\n")
    b.write_text("B=2\n")
    model = wiz.build_compose_model("acme", tmp_path / "repo", env_file=[a, b])
    assert model["services"]["agent"]["env_file"] == [str(a), str(b)]


def test_single_env_file_still_accepted_as_a_bare_path(wiz, tmp_path):
    """Widening the parameter must not break the single-file callers (the
    declarative path passes one)."""
    a = tmp_path / "a.env"
    a.write_text("A=1\n")
    assert wiz.build_compose_model("acme", tmp_path / "repo", env_file=a)["services"]["agent"][
        "env_file"
    ] == [str(a)]


def test_explicit_env_files_replace_the_discovery_chain(wiz, tmp_path, monkeypatch):
    """FR-001d: naming files is a statement that the operator is in control, so
    discovered files are NOT merged underneath — that would make the effective
    environment depend on directory contents they were bypassing."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "acme.env").write_text("DISCOVERED=1\n")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("EXPLICIT=1\n")
    monkeypatch.chdir(root)
    assert wiz._resolve_env_files("acme", [explicit]) == [explicit]
    assert wiz._resolve_env_files("acme", None) == [
        root.resolve() / ".agent-container" / "acme.env"
    ]


def test_env_file_outside_the_project_is_usable(wiz, tmp_path, monkeypatch):
    """FR-001e: `-e ~/.env` — an env file anywhere. This is the escape hatch that
    makes dropping the implicit `./.env` reasonable: the tool stops guessing and
    gains a way to be told."""
    outside = tmp_path / "home" / ".env"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("X=1\n")
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    monkeypatch.chdir(root)
    assert wiz._resolve_env_files("acme", [outside]) == [outside]


def test_build_without_image_sources_fails_actionably(wiz, tmp_path, monkeypatch):
    """FR-008 / contract C4. A tree that is not a checkout must say what was
    expected and where — never a traceback, and never a bare "no checkout" while
    the operator is standing inside one (research R1)."""
    not_a_checkout = tmp_path / "elsewhere"
    not_a_checkout.mkdir()
    monkeypatch.setenv("AGENT_CONTAINER_REPO", str(not_a_checkout))
    with pytest.raises(wiz.Fatal) as ei:
        wiz.do_build("x:y")
    msg = str(ei.value)
    assert "image/Dockerfile" in msg, f"the message must name what is missing: {msg}"


def test_build_inside_a_pre011_checkout_names_the_move(wiz, tmp_path, monkeypatch):
    """Post-release fix. Research R1 predicted this failure verbatim:

        "a stale marker degrades to 'no checkout reachable' — build fails with a
         message about a missing checkout while standing INSIDE one."

    It shipped anyway, because T018 exercised the AGENT_CONTAINER_REPO path — which
    does name image/Dockerfile — and not the bare-cwd path, which does not. Telling
    an operator to "run from a checkout" while they are standing in one is useless
    advice; the message must name what actually changed.
    """
    old = tmp_path / "old-checkout"
    (old / "completions").mkdir(parents=True)
    (old / "Dockerfile").write_text("FROM debian\n")
    (old / "completions" / "agent-container.bash").write_text("# complete\n")
    monkeypatch.chdir(old)
    monkeypatch.delenv("AGENT_CONTAINER_REPO", raising=False)
    monkeypatch.setattr(wiz, "REPO_ROOT", None)

    with pytest.raises(wiz.Fatal) as ei:
        wiz.do_build("x:y")
    msg = str(ei.value)
    assert "image/" in msg, f"the message must name the move: {msg}"
    assert "before v0.18.0" in msg
    assert "run from a checkout" not in msg, "must not tell them to do what they are doing"


def test_build_outside_any_checkout_still_says_so(wiz, tmp_path, monkeypatch):
    """The upgraded message must not swallow the ordinary case: someone genuinely
    outside a checkout still gets the generic guidance, now naming what is looked
    for."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_CONTAINER_REPO", raising=False)
    monkeypatch.setattr(wiz, "REPO_ROOT", None)
    with pytest.raises(wiz.Fatal) as ei:
        wiz.do_build("x:y")
    msg = str(ei.value)
    assert "image/Dockerfile" in msg
    assert "AGENT_CONTAINER_REPO" in msg
