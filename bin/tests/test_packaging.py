"""Packaging integrity guards (runtime-free; no uv/docker/ssh).

Keeps the two dependency declarations, the console-script entry point, the
wheel force-include mapping (module + completions as package data), and the
__main__ routing consistent, so the `uv tool install` / PyPI path and the
`uv run --script` path can't silently diverge.
"""

from __future__ import annotations

import ast
import sys
import tomllib

import pytest
from conftest import SCRIPT_PATH

REPO_ROOT = SCRIPT_PATH.parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _pep723_metadata() -> dict:
    """Parse the '# /// script ... # ///' PEP 723 block from bin/agent-container."""
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
        (ln[2:] if ln.startswith("# ") else ln.lstrip("#")) for ln in lines[start + 1 : end]
    )
    return tomllib.loads(body)


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_pyproject_dependencies_match_pep723():
    assert _pyproject()["project"]["dependencies"] == _pep723_metadata()["dependencies"]


def test_pyproject_requires_python_matches_pep723():
    assert _pyproject()["project"]["requires-python"] == _pep723_metadata()["requires-python"]


def test_entry_point_module_and_attr_resolve(wiz):
    # [project.scripts] agent-container = "<module>:<attr>"; the module name must be
    # 'agent_container' (the force-included module name) and the attr must exist +
    # be callable.
    module_name, _, attr = _pyproject()["project"]["scripts"]["agent-container"].partition(":")
    assert module_name == "agent_container"
    assert hasattr(wiz, attr) and callable(getattr(wiz, attr))


def test_wheel_force_include_ships_module_and_completions():
    # The non-editable wheel must copy the single-file script in as
    # agent_container/__init__.py and bundle both completion scripts as package data
    # (agent_container/completions/*), so a PyPI install has the module AND the
    # completions without a repo checkout.
    force_include = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["bin/agent-container"] == "agent_container/__init__.py"
    assert (
        force_include["completions/agent-container.bash"]
        == "agent_container/completions/agent-container.bash"
    )
    assert (
        force_include["completions/agent-container.zsh"]
        == "agent_container/completions/agent-container.zsh"
    )


def test_wheel_bypasses_selection():
    # There is no conventionally-named package dir, so hatchling's auto file
    # selection must be bypassed (force-include supplies everything).
    assert _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["bypass-selection"] is True


def test_no_module_symlink_remains():
    # The old bin/agent_container.py importable-module symlink is gone; force-include
    # now supplies the `agent_container` module name.
    assert not (REPO_ROOT / "bin" / "agent_container.py").exists()


def test_pyproject_declares_mit_license_and_metadata():
    proj = _pyproject()["project"]
    assert proj["license"] == "MIT"
    assert proj["license-files"] == ["LICENSE"]
    assert (REPO_ROOT / "LICENSE").is_file()
    assert proj["description"]
    assert proj["readme"] == "README.md"
    assert proj["urls"]["Homepage"] == "https://github.com/ondrasek/agent-container"


def test_cli_translates_fatal_to_exit_one(wiz, monkeypatch):
    # The entry point must turn a Fatal into exit 1 (not a traceback). With an
    # isolated HOME, 'attach acme --local' has no state file -> Fatal.
    monkeypatch.setattr(sys, "argv", ["agent-container", "attach", "acme", "--local"])
    with pytest.raises(SystemExit) as exc:
        wiz.cli()
    assert exc.value.code == 1


def test_main_guard_routes_through_cli():
    # The __main__ guard must call cli() (which wraps app() with Fatal handling),
    # not app() directly — else `uv run --script` loses Fatal->exit-1.
    tree = ast.parse(SCRIPT_PATH.read_text())
    guard = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
        ),
        None,
    )
    assert guard is not None, '`if __name__ == "__main__":` guard not found'
    assert len(guard.body) == 1
    stmt = guard.body[0]
    assert isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
    assert isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "cli"


# --- location-independent REPO_ROOT + gated build ------------------------------


def test_find_repo_root_honours_agent_container_repo(wiz, monkeypatch, tmp_path):
    # AGENT_CONTAINER_REPO wins when it satisfies the checkout marker (Dockerfile +
    # completions/agent-container.bash — the repo-specific sentinel).
    checkout = tmp_path / "fake-checkout"
    (checkout / "completions").mkdir(parents=True)
    (checkout / "Dockerfile").write_text("FROM scratch\n")
    (checkout / "completions" / "agent-container.bash").write_text("# complete\n")
    monkeypatch.setenv("AGENT_CONTAINER_REPO", str(checkout))
    assert wiz._find_repo_root() == checkout.resolve()


def test_find_repo_root_rejects_agent_container_repo_without_marker(wiz, monkeypatch, tmp_path):
    # A wrong/typo'd override that lacks the sentinel is NOT trusted: it resolves
    # to None (build then dies actionably) rather than a bogus root. A bare
    # Dockerfile + empty completions/ dir is no longer sufficient.
    stray = tmp_path / "not-a-checkout"
    (stray / "completions").mkdir(parents=True)
    (stray / "Dockerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("AGENT_CONTAINER_REPO", str(stray))
    assert wiz._find_repo_root() is None


def test_do_build_dies_on_invalid_agent_container_repo(wiz, monkeypatch, tmp_path):
    # AGENT_CONTAINER_REPO set but not a checkout -> actionable Fatal naming the var,
    # before any runtime call.
    stray = tmp_path / "not-a-checkout"
    stray.mkdir()
    monkeypatch.setattr(wiz, "REPO_ROOT", None)
    monkeypatch.setenv("AGENT_CONTAINER_REPO", str(stray))
    with pytest.raises(wiz.Fatal) as exc:
        wiz.do_build("localhost/agent-container:latest")
    assert "is not an agent-container checkout" in str(exc.value)


def test_find_repo_root_is_none_without_checkout(wiz, monkeypatch, tmp_path):
    # No AGENT_CONTAINER_REPO, __file__ relocated out of any repo, and cwd moved to a
    # marker-free dir -> the resolver returns None (mirrors a PyPI install).
    monkeypatch.delenv("AGENT_CONTAINER_REPO", raising=False)
    stray = tmp_path / "site-packages" / "agent_container" / "__init__.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("")
    monkeypatch.setattr(wiz, "__file__", str(stray))
    monkeypatch.chdir(tmp_path)
    assert wiz._find_repo_root() is None


def test_do_build_dies_without_context_or_checkout(wiz, monkeypatch):
    # REPO_ROOT None + no --context + no AGENT_CONTAINER_REPO -> actionable Fatal
    # (not a traceback), and before any runtime call.
    monkeypatch.delenv("AGENT_CONTAINER_REPO", raising=False)
    monkeypatch.setattr(wiz, "REPO_ROOT", None)
    with pytest.raises(wiz.Fatal) as exc:
        wiz.do_build("localhost/agent-container:latest")
    assert "no repo checkout for the docker build context" in str(exc.value)


def test_completion_script_reads_from_checkout(wiz):
    # In dev / script mode REPO_ROOT resolves via the __file__ marker, so the
    # completion text comes straight off disk.
    assert wiz.REPO_ROOT is not None
    text = wiz._completion_script("bash")
    assert text == (wiz.REPO_ROOT / "completions" / "agent-container.bash").read_text()
