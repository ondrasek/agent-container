"""CLI behavior: exit codes, help, unknown subcommands, and the non-TTY guard.

In-process tests drive the Typer app with CliRunner; two subprocess smoke
tests exercise the real `#!/usr/bin/env -S uv run --script` entry path
(skipped when uv is not installed).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from conftest import SCRIPT_PATH

runner = CliRunner()


def combined_output(result) -> str:
    """stdout + stderr regardless of the installed click version."""
    parts = [result.output]
    try:
        parts.append(result.stderr)
    except (ValueError, AttributeError):
        pass  # click<8.2 mixes stderr into .output already
    return "".join(parts)


# --- help / unknown subcommand -----------------------------------------------


def test_help_exits_zero(wiz):
    result = runner.invoke(wiz.app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    for sub in ("build", "up", "down", "list", "attach", "logs", "purge", "menu", "completions"):
        assert sub in result.output


@pytest.mark.parametrize("sub", ["up", "down", "attach", "logs", "list", "build", "purge", "completions"])
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
    assert "does not exist" in combined_output(result)


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
    expected = (wiz.REPO_ROOT / "completions" / f"devenv-wiz.{shell}").read_text()
    assert result.output == expected


def test_completions_invalid_shell_is_fatal_not_traceback(wiz):
    result = runner.invoke(wiz.app, ["completions", "fish"])
    assert result.exit_code == 1
    assert isinstance(result.exception, wiz.Fatal)
    assert "usage: devenv-wiz completions <bash|zsh>" in str(result.exception)
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


# --- real entrypoint smoke tests (shebang -> uv run --script) ------------------------

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")


@needs_uv
def test_script_help_via_uv(tmp_path):
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH), "--help"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Usage" in proc.stdout


@needs_uv
def test_script_bare_non_tty_via_uv(tmp_path):
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300,
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
    for var in ("DEVENV_RUNTIME", "DEVENV_HOST", "DEVENV_USER"):
        env.pop(var, None)
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT_PATH), "attach", "acme", "--local"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300, env=env,
    )
    assert proc.returncode == 1
    assert "FATAL: no local state for acme" in proc.stderr
    assert "Traceback" not in proc.stderr
