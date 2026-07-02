"""Packaging integrity guards (runtime-free; no uv/docker/ssh).

Keeps the two dependency declarations, the console-script entry point, the
importable-module symlink, and the __main__ routing consistent, so the
`uv tool install` path and the `uv run --script` path can't silently diverge.
"""

from __future__ import annotations

import ast
import os
import sys
import tomllib
from pathlib import Path

import pytest

from conftest import SCRIPT_PATH

REPO_ROOT = SCRIPT_PATH.parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _pep723_metadata() -> dict:
    """Parse the '# /// script ... # ///' PEP 723 block from bin/devenv-wiz."""
    lines = SCRIPT_PATH.read_text().splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if line.strip() == "# /// script":
            start = i
        elif start is not None and line.strip() == "# ///":
            end = i
            break
    assert start is not None and end is not None, "PEP 723 script block not found"
    body = "\n".join(
        (ln[2:] if ln.startswith("# ") else ln.lstrip("#")) for ln in lines[start + 1:end]
    )
    return tomllib.loads(body)


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_pyproject_dependencies_match_pep723():
    assert _pyproject()["project"]["dependencies"] == _pep723_metadata()["dependencies"]


def test_pyproject_requires_python_matches_pep723():
    assert _pyproject()["project"]["requires-python"] == _pep723_metadata()["requires-python"]


def test_entry_point_module_and_attr_resolve(wiz):
    # [project.scripts] devenv-wiz = "<module>:<attr>"; the module name must be
    # 'devenv_wiz' (the symlink's basename) and the attr must exist + be callable.
    module_name, _, attr = _pyproject()["project"]["scripts"]["devenv-wiz"].partition(":")
    assert module_name == "devenv_wiz"
    assert hasattr(wiz, attr) and callable(getattr(wiz, attr))


def test_cli_translates_fatal_to_exit_one(wiz, monkeypatch):
    # The entry point must turn a Fatal into exit 1 (not a traceback). With an
    # isolated HOME, 'attach acme --local' has no state file -> Fatal.
    monkeypatch.setattr(sys, "argv", ["devenv-wiz", "attach", "acme", "--local"])
    with pytest.raises(SystemExit) as exc:
        wiz.cli()
    assert exc.value.code == 1


def test_module_symlink_integrity():
    link = REPO_ROOT / "bin" / "devenv_wiz.py"
    assert link.is_symlink(), "bin/devenv_wiz.py must be a symlink (mode 120000)"
    assert os.readlink(link) == "devenv-wiz"
    assert link.resolve().samefile(SCRIPT_PATH)


def test_main_guard_routes_through_cli():
    # The __main__ guard must call cli() (which wraps app() with Fatal handling),
    # not app() directly — else `uv run --script` loses Fatal->exit-1.
    tree = ast.parse(SCRIPT_PATH.read_text())
    guard = next(
        (n for n in tree.body
         if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
         and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"),
        None,
    )
    assert guard is not None, "`if __name__ == \"__main__\":` guard not found"
    assert len(guard.body) == 1
    stmt = guard.body[0]
    assert isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
    assert isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "cli"
