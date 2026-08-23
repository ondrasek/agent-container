"""Feature 020 — the public-key collection, PYTHON side only.

The region parser is shell and is tested by the harness that EXECUTES shell
(`test_entrypoint.sh` sections 7e/7f). Nothing in this file may stand in for
entrypoint behaviour: a Python test that reads `entrypoint.sh` as text and asserts
on its source cannot fail when the shell logic is wrong, and grep-the-source
coverage for the mechanism this whole feature rests on is exactly the defect shape
020 exists to remove.

Compose-model assertions live in `test_compose.py`, which already owns them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _keygen(tmp_path: Path, comment: str) -> tuple[str, str]:
    """A real ed25519 keypair. Returns (public line, private key text).

    Real keys, not fixtures shaped like keys: validation runs `ssh-keygen -l`, so a
    hand-written string would test the error path only.
    """
    priv = tmp_path / f"id_{comment}"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(priv)],
        check=True,
    )
    return priv.with_suffix(".pub").read_text().strip(), priv.read_text()


# --- C1/C2/C3/C4: resolution and the three states ----------------------------


def test_undeclared_collection_resolves_to_none(wiz, tmp_path):
    """C3: absent at both levels is UNDECLARED — not empty (Constitution VIII)."""
    assert wiz.resolve_key_collection(tmp_path / "not-a-project") is None


def test_user_level_collection_resolves(wiz, tmp_path):
    """C1: with only a user-level file, that file wins."""
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    src, keys = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert src == wiz.CONFIG_DIR / "authorized_keys"
    assert keys == [pub]


def test_declared_empty_is_distinguishable_from_undeclared(wiz, tmp_path):
    """C4 vs C3 — the distinction Constitution VIII exists to protect.

    `len(keys) == 0` cannot tell these apart, which is why the resolver returns
    None for one and an empty list for the other.
    """
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text("# only a comment\n\n")
    declared = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert declared is not None
    assert declared[1] == []
    (wiz.CONFIG_DIR / "authorized_keys").unlink()
    assert wiz.resolve_key_collection(tmp_path / "elsewhere") is None


def test_project_replaces_user_entirely(wiz, tmp_path):
    """C2/FR-002: the winning FILE wins — not a per-key merge.

    Merging would let a project only WIDEN the admit set, never narrow it, and
    narrowing is the entire point of the project override: a client repository must
    not inherit an operator's personal phone.
    """
    user_pub, _ = _keygen(tmp_path, "phone")
    proj_pub, _ = _keygen(tmp_path, "workstation")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(user_pub + "\n")
    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "authorized_keys").write_text(proj_pub + "\n")
    src, keys = wiz.resolve_key_collection(proj)
    assert keys == [proj_pub]
    assert user_pub not in keys  # NOT merged — the project narrowed the set
    assert src == proj / ".agent-container" / "authorized_keys"


def test_options_prefix_survives_verbatim(wiz, tmp_path):
    """`from=`/`restrict` are legal authorized_keys syntax and none of our business."""
    pub, _ = _keygen(tmp_path, "restricted")
    line = f'restrict,from="10.0.0.0/8" {pub}'
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(line + "\n")
    _, keys = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert keys == [line]


# --- C6/C7/C9: validation refuses before anything is created -----------------


def test_malformed_entry_refuses_naming_file_and_line(wiz, tmp_path):
    """C6/SC-004: the message must name the file AND the line number."""
    bad = tmp_path / "collection"
    bad.write_text("ssh-ed25519 NOT-VALID-BASE64 broken\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_public_key_line("ssh-ed25519 NOT-VALID-BASE64 broken", str(bad), 1)
    assert str(bad) in str(e.value)
    assert ":1" in str(e.value)


def test_private_key_is_refused_as_private(wiz, tmp_path):
    """C7/SC-005: refused, and the message SAYS it is private.

    `id_ed25519` and `id_ed25519.pub` differ by four characters and the mistake is
    one `cat` away. It is also the only error here whose cost is not recoverable by
    editing a file, so a generic "invalid key" would be the wrong message.
    """
    _, priv = _keygen(tmp_path, "oops")
    first = priv.splitlines()[0]
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_public_key_line(first, "collection", 3)
    assert "PRIVATE" in str(e.value).upper()
    assert "collection:3" in str(e.value)


def test_a_real_public_key_validates_to_a_fingerprint(wiz, tmp_path):
    """The guard above must not be passing because everything fails."""
    pub, _ = _keygen(tmp_path, "good")
    fp = wiz.validate_public_key_line(pub, "collection", 1)
    assert fp.startswith("SHA256:")


# --- C10/C11: the admit set and its attribution ------------------------------


def test_flag_is_additive_and_each_entry_is_attributed(wiz, tmp_path):
    """C11/FR-008: --authorized-key widens the collection; neither wins silently."""
    coll_pub, _ = _keygen(tmp_path, "laptop")
    flag_pub, _ = _keygen(tmp_path, "iphone")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(coll_pub + "\n")
    flag = tmp_path / "iphone.pub"
    flag.write_text(flag_pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert declared is True
    assert [e.line for e in entries] == [coll_pub, flag_pub]
    assert str(src) in entries[0].source
    assert "--authorized-key" in entries[1].source
    assert {e.comment for e in entries} == {"laptop", "iphone"}


def test_a_duplicate_across_sources_is_admitted_once(wiz, tmp_path):
    """A duplicate is deduped on key MATERIAL, and is not an error."""
    pub, _ = _keygen(tmp_path, "same")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    flag = tmp_path / "same.pub"
    flag.write_text(pub + "\n")
    entries, _, _ = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert len(entries) == 1


def test_undeclared_plus_flag_admits_exactly_the_flag(wiz, tmp_path):
    """SC-007: the undeclared path behaves exactly as it does today."""
    flag_pub, _ = _keygen(tmp_path, "only")
    flag = tmp_path / "only.pub"
    flag.write_text(flag_pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert declared is False
    assert src is None
    assert [e.line for e in entries] == [flag_pub]


def test_a_missing_flag_file_refuses(wiz, tmp_path):
    """FR-012/C8: refuse before any runtime call, naming the path."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.resolved_admit_set([tmp_path / "nope.pub"], cwd=tmp_path)
    assert "nope.pub" in str(e.value)


# --- C4/C3 at the reporting surface -----------------------------------------


def test_declared_empty_warns_and_undeclared_stays_silent(wiz, tmp_path, capsys):
    """SC-011: the two runs must differ in OUTPUT, not merely in behaviour.

    The asymmetry is deliberate. A hand-edited file can be truncated by accident;
    where there is no file there is nothing to truncate, and FR-009 requires the
    undeclared path keep behaving exactly as it does today — which is silently.
    """
    wiz.report_admit_set([], Path("/cfg/authorized_keys"), declared=True)
    declared_out = capsys.readouterr()
    combined = declared_out.out + declared_out.err
    assert "EMPTY" in combined
    assert "/cfg/authorized_keys" in combined

    wiz.report_admit_set([], None, declared=False)
    undeclared = capsys.readouterr()
    assert (undeclared.out + undeclared.err).strip() == ""


def test_the_statement_names_fingerprints_never_blobs(wiz, tmp_path, capsys):
    """C10: a fingerprint identifies a device; the full blob is noise."""
    pub, _ = _keygen(tmp_path, "macbook")
    flag = tmp_path / "macbook.pub"
    flag.write_text(pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    wiz.report_admit_set(entries, src, declared)
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "macbook" in combined
    assert entries[0].fingerprint in combined
    assert pub.split()[1] not in combined  # the base64 body must not be printed
