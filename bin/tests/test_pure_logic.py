"""Pure-logic tests: every value here pins the byte-for-byte on-disk contract
that agent-container defines — the port hash, container/volume naming, env-file
resolution order, and hosts.conf parsing. These constants are load-bearing;
the shell completions read the same state files, so do not 'fix' them casually.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# --- port hash: 2200 + (sum of char codes mod 100) ---------------------------

# Ground truth: the deterministic port hash (2200 + sum-of-ASCII mod 100).
PORT_CORPUS = {
    "acme": 2206,  # 406 % 100 = 6
    "blog": 2220,  # 420
    "scratch": 2244,  # 744
    "my-box": 2204,  # 604 ('-' is 45 and counts)
    "a": 2297,  # 97 — single char lands near the top of the window
    "devbox123": 2298,  # 798 — digits count via their ASCII codes
    "zz": 2244,  # 244 wraps: collides with 'scratch' by design
    "0": 2248,  # 48
    "a_b-c9": 2291,  # 491 — '_' (95) and '-' (45) both count
}


@pytest.mark.parametrize(("name", "port"), sorted(PORT_CORPUS.items()))
def test_port_for_name_matches_corpus(wiz, name, port):
    assert wiz.port_for_name(name) == port


def test_port_always_inside_window(wiz):
    # Sweep far beyond the concrete corpus: the 2200..2299 window must hold
    # for ANY valid name, not just the hand-computed ones above.
    import itertools

    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    names = [c for c in alphabet]
    names += [a + b for a, b in itertools.islice(itertools.product(alphabet, "az9_-"), 100)]
    names += ["x" * n for n in (3, 7, 17, 63, 255)]
    for name in names:
        assert wiz.validate_name(name) == name  # only valid names matter
        assert 2200 <= wiz.port_for_name(name) <= 2299, name


def test_port_collision_is_possible_and_deterministic(wiz):
    # 'zz' and 'scratch' hash to the same port — a deterministic collision;
    # agent-container must not "helpfully" disambiguate.
    assert wiz.port_for_name("zz") == wiz.port_for_name("scratch") == 2244


# --- container / volume naming ------------------------------------------------


def test_container_and_volume_naming(wiz):
    assert wiz.container_name("acme") == "agent-container-acme"
    assert wiz.volume_name("acme") == "agent-container-acme-workspace"
    assert wiz.container_name("my-box") == "agent-container-my-box"
    assert wiz.volume_name("my-box") == "agent-container-my-box-workspace"
    # Each per-container naming helper has its own explicit contract assertion
    # rather than relying on doctest/argv side-coverage (the canonical order is
    # workspace, claude, codex, pi, shellenv, tmux, ssh).
    assert wiz.claude_volume_name("acme") == "agent-container-acme-claude"
    assert wiz.codex_volume_name("acme") == "agent-container-acme-codex"
    assert wiz.pi_volume_name("acme") == "agent-container-acme-pi"
    assert wiz.shellenv_volume_name("acme") == "agent-container-acme-shellenv"
    assert wiz.tmux_volume_name("acme") == "agent-container-acme-tmux"
    assert wiz.ssh_volume_name("acme") == "agent-container-acme-ssh"


# --- name validation: ^[a-z0-9][a-z0-9_-]*$ ------------------------------------


@pytest.mark.parametrize("name", ["acme", "a", "0", "my-box", "a_b-c9", "9to5", "x" * 64])
def test_validate_name_accepts(wiz, name):
    assert wiz.validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "Bad",  # uppercase anywhere
        "ACME",
        "-leading",  # must start with [a-z0-9]
        "_leading",
        "has space",
        "has.dot",
        "café",  # non-ASCII would break ord()/printf parity
        "name\n",
        "a/b",
    ],
)
def test_validate_name_rejects(wiz, name):
    with pytest.raises(wiz.Fatal, match="invalid <name>"):
        wiz.validate_name(name)


def test_validate_name_rejects_empty(wiz):
    with pytest.raises(wiz.Fatal, match="missing required <name>"):
        wiz.validate_name("")


# --- tmux window-name validation (embedded in the ssh remote command) -----------


@pytest.mark.parametrize("window", ["shell", "edit", "agents", "win.1", "a_b-c9", "0"])
def test_validate_window_accepts(wiz, window):
    assert wiz.validate_window(window) == window


@pytest.mark.parametrize(
    "window",
    [
        "a;b",  # command separator
        "$(x)",  # command substitution
        "a b",  # whitespace (bash would word-split into two args)
        "`id`",  # backtick substitution
        "a|b",
        "a&b",
        "a>b",
        "",  # empty is not a valid window name
        "win\n",
    ],
)
def test_validate_window_rejects_injection(wiz, window):
    # The window name is interpolated into the remote shell string, so anything
    # outside [A-Za-z0-9._-]+ must die before it can reach ssh.
    with pytest.raises(wiz.Fatal, match="invalid tmux window"):
        wiz.validate_window(window)


# --- hosts.conf key normalization ----------------------------------------------


@pytest.mark.parametrize(
    ("name", "key"),
    [("acme", "ACME"), ("my-box", "MY_BOX"), ("a-b-c", "A_B_C"), ("a_b", "A_B"), ("box9", "BOX9")],
)
def test_name_to_key(wiz, name, key):
    assert wiz.name_to_key(name) == key


# --- hosts.conf parsing ---------------------------------------------------------


def test_parse_kv_config_basics(wiz):
    text = "# comment\n\nA=1\nexport B='two'\nC=\"three\"\nD=a=b\n"
    assert wiz.parse_kv_config(text) == {"A": "1", "B": "two", "C": "three", "D": "a=b"}


def test_parse_kv_config_trailing_comments_like_bash(wiz):
    text = 'H=vps.example.com # primary box\nQ="a # b" # c\nR=#lit\n'
    # '#' only opens a comment after whitespace; quoted '#' survives; 'R=#lit'
    # keeps the hash — same as bash `source`.
    assert wiz.parse_kv_config(text) == {"H": "vps.example.com", "Q": "a # b", "R": "#lit"}


def test_parse_kv_config_skips_garbage(wiz):
    text = "no_equals_here\n=valuewithoutkey\n   # indented comment\n\nK=v\n"
    assert wiz.parse_kv_config(text) == {"K": "v"}


def test_parse_kv_config_last_assignment_wins(wiz):
    assert wiz.parse_kv_config("A=1\nA=2\n") == {"A": "2"}


def test_hosts_entry_requires_both_keys(wiz):
    conf_dir = wiz.CONFIG_DIR
    conf_dir.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text("ACME_HOST=vps.example.com\n")
    assert wiz.hosts_entry("acme") is None  # _PORT missing
    wiz.HOSTS_CONF.write_text("MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2204\n")
    assert wiz.hosts_entry("my-box") == ("vps.example.com", "2204")
    assert wiz.hosts_entry("acme") is None


def test_hosts_entry_without_conf_file(wiz):
    assert not wiz.HOSTS_CONF.exists()
    assert wiz.hosts_entry("acme") is None


# --- env-file resolution order ---------------------------------------------------


def test_env_file_candidate_order(wiz, tmp_path):
    """Feature 011 FR-001b: project config dir, then user config; per-environment
    file before the shared default at each level. The bare ./.env is not read."""
    work = tmp_path / "work"
    (work / ".agent-container").mkdir(parents=True)
    assert wiz.env_file_candidates("acme", work) == [
        work / ".agent-container" / "acme.env",
        work / ".agent-container" / ".env",
        wiz.CONFIG_DIR / "acme.env",
        wiz.CONFIG_DIR / ".env",
    ]


def test_resolve_env_file_prefers_project_level(wiz, tmp_path, monkeypatch):
    """Project level wins over user level — the layering operators expect from
    Claude Code and similar tools (Feature 011)."""
    work = tmp_path / "work"
    (work / ".agent-container").mkdir(parents=True)
    monkeypatch.chdir(work)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (work / ".agent-container" / "acme.env").write_text("X=1\n")
    (wiz.CONFIG_DIR / "acme.env").write_text("X=2\n")
    (wiz.CONFIG_DIR / ".env").write_text("X=3\n")
    assert wiz.resolve_env_file("acme") == work / ".agent-container" / "acme.env"


def test_bare_project_root_env_is_not_read(wiz, tmp_path, monkeypatch):
    """FR-001b: a `.env` in the project ROOT belongs to whoever put it there —
    Compose, direnv, a framework. The tool no longer claims it."""
    work = tmp_path / "work"
    (work / ".agent-container").mkdir(parents=True)
    monkeypatch.chdir(work)
    (work / ".env").write_text("X=1\n")
    assert wiz.resolve_env_file("acme") is None


def test_resolve_env_file_then_name_env_then_shared(wiz, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)  # no ./.env here
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.env").write_text("X=2\n")
    (wiz.CONFIG_DIR / ".env").write_text("X=3\n")
    assert wiz.resolve_env_file("acme") == wiz.CONFIG_DIR / "acme.env"
    (wiz.CONFIG_DIR / "acme.env").unlink()
    assert wiz.resolve_env_file("acme") == wiz.CONFIG_DIR / ".env"
    (wiz.CONFIG_DIR / ".env").unlink()
    assert wiz.resolve_env_file("acme") is None


def test_xdg_defaults_fall_back_to_home(load_wiz, tmp_path):
    # With XDG vars unset, paths must match bash's ${XDG_*:-$HOME/...} defaults.
    home = tmp_path / "home"
    mod = load_wiz(home=home, xdg_state=None, xdg_config=None)
    assert mod.STATE_DIR == home / ".local/state" / "agent-container"
    assert mod.CONFIG_DIR == home / ".config" / "agent-container"
    assert mod.HOSTS_CONF == home / ".config" / "agent-container" / "hosts.conf"


def test_xdg_env_vars_override_home(load_wiz, tmp_path):
    state, config = tmp_path / "s", tmp_path / "c"
    mod = load_wiz(xdg_state=state, xdg_config=config)
    assert mod.STATE_DIR == state / "agent-container"
    assert mod.CONFIG_DIR == config / "agent-container"


# --- state file round-trip ---------------------------------------------------------


def test_state_write_read_round_trip(wiz):
    wiz.write_state("local", "acme", 2206)
    f = wiz.state_file_for("local", "acme")
    assert f == wiz.STATE_DIR / "local" / "acme.port"
    assert f.read_text() == "2206\n"  # exact bytes agent-container writes; completions read these
    assert wiz.read_state_port("local", "acme") == "2206"


def test_state_read_missing_and_empty(wiz):
    assert wiz.read_state_port("local", "ghost") is None
    wiz.host_state_dir("local").mkdir(parents=True, exist_ok=True)
    (wiz.host_state_dir("local") / "empty.port").write_text("")
    assert wiz.read_state_port("local", "empty") is None


def test_clear_state(wiz):
    wiz.write_state("local", "acme", 2206)
    wiz.clear_state("local", "acme")
    assert not wiz.state_file_for("local", "acme").exists()
    wiz.clear_state("local", "acme")  # idempotent on missing file


# --- runtime detection (platform-aware default) --------------------------------------


def test_runtime_default_is_docker_on_macos(wiz, fake_bin, monkeypatch):
    # macOS operator runs Lima + docker-cli: with BOTH present, prefer docker.
    monkeypatch.setattr(wiz.sys, "platform", "darwin")
    monkeypatch.setenv("PATH", str(fake_bin("podman", "docker")))
    assert wiz.detect_runtime() == "docker"


def test_runtime_default_is_podman_on_linux(wiz, fake_bin, monkeypatch):
    # Linux VPS runs podman: with BOTH present, prefer podman.
    monkeypatch.setattr(wiz.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(fake_bin("podman", "docker")))
    assert wiz.detect_runtime() == "podman"


def test_runtime_macos_falls_back_to_podman_when_docker_absent(wiz, fake_bin, monkeypatch):
    monkeypatch.setattr(wiz.sys, "platform", "darwin")
    monkeypatch.setenv("PATH", str(fake_bin("podman")))
    assert wiz.detect_runtime() == "podman"


def test_runtime_linux_falls_back_to_docker_when_podman_absent(wiz, fake_bin, monkeypatch):
    monkeypatch.setattr(wiz.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(fake_bin("docker")))
    assert wiz.detect_runtime() == "docker"


def test_runtime_neither_present(wiz, fake_bin, monkeypatch):
    monkeypatch.setattr(wiz.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(fake_bin()))
    with pytest.raises(wiz.Fatal, match="neither 'podman' nor 'docker'"):
        wiz.detect_runtime()


def test_runtime_override_wins_over_platform_default(wiz, fake_bin, monkeypatch):
    # AGENT_CONTAINER_RUNTIME beats the platform preference on both OSes.
    for platform, forced in (("darwin", "podman"), ("linux", "docker")):
        monkeypatch.setattr(wiz.sys, "platform", platform)
        monkeypatch.setenv("PATH", str(fake_bin("podman", "docker")))
        monkeypatch.setenv("AGENT_CONTAINER_RUNTIME", forced)
        assert wiz.detect_runtime() == forced


def test_runtime_override_must_be_on_path(wiz, fake_bin, monkeypatch):
    monkeypatch.setenv("PATH", str(fake_bin("docker")))
    monkeypatch.setenv("AGENT_CONTAINER_RUNTIME", "podman")
    with pytest.raises(wiz.Fatal, match="not on PATH"):
        wiz.detect_runtime()


def test_runtime_override_rejects_unknown_value(wiz, fake_bin, monkeypatch):
    monkeypatch.setenv("PATH", str(fake_bin("podman")))
    monkeypatch.setenv("AGENT_CONTAINER_RUNTIME", "containerd")
    with pytest.raises(wiz.Fatal, match="must be 'docker' or 'podman'"):
        wiz.detect_runtime()


# --- ssh user / host guards -------------------------------------------------------------


def test_resolve_ssh_user_default_and_env(wiz, monkeypatch):
    assert wiz.resolve_ssh_user() == "dev"
    monkeypatch.setenv("AGENT_CONTAINER_USER", "ops")
    assert wiz.resolve_ssh_user() == "ops"
    assert wiz.resolve_ssh_user("admin") == "admin"  # explicit override beats env


def test_resolve_ssh_user_rejects_option_injection(wiz):
    with pytest.raises(wiz.Fatal, match="invalid ssh user"):
        wiz.resolve_ssh_user("-oProxyCommand=evil")


# --- per-host identity + migration (Feature 001) ----------------------------
# Identity VALUES are unchanged; only the state file LOCATION gains a host
# segment. The pre-per-host flat <name>.port files migrate into local/ once.


def test_identity_values_unchanged_by_per_host(wiz):
    # The stable-contract guarantee (Constitution IV): namespacing per host must
    # NOT change the values computed for an existing name.
    assert wiz.container_name("acme") == "agent-container-acme"
    assert wiz.port_for_name("acme") == 2206
    assert wiz.per_container_volumes("acme")[0] == "agent-container-acme-workspace"


def test_per_host_state_paths(wiz):
    p = wiz.state_file_for("hz1", "acme")
    assert p == wiz.host_state_dir("hz1") / "acme.port"
    # Same name on two hosts → distinct state paths, no collision.
    assert wiz.state_file_for("local", "acme") != wiz.state_file_for("hz1", "acme")
    assert wiz.compose_file_path("local", "acme").name == "acme.compose.yaml"


def test_migrate_flat_state_relocates_into_local(wiz):
    wiz.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.STATE_DIR / "acme.port").write_text("2206\n")
    (wiz.STATE_DIR / "acme.host_key").write_bytes(b"KEY")
    (wiz.STATE_DIR / "acme.authorized_keys").write_text("pub")
    wiz.migrate_flat_state()
    local = wiz.host_state_dir("local")
    assert (local / "acme.port").read_text() == "2206\n"
    assert (local / "acme.host_key").read_bytes() == b"KEY"
    assert (local / "acme.authorized_keys").read_text() == "pub"
    # Flat originals are gone (moved, not copied).
    assert not (wiz.STATE_DIR / "acme.port").exists()


def test_migrate_flat_state_is_idempotent_and_nondestructive(wiz):
    wiz.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.STATE_DIR / "acme.port").write_text("2206\n")
    wiz.migrate_flat_state()
    # A second flat file with the same name must NOT clobber the migrated one.
    (wiz.STATE_DIR / "acme.port").write_text("9999\n")
    wiz.migrate_flat_state()
    assert (wiz.host_state_dir("local") / "acme.port").read_text() == "2206\n"


def test_migrate_flat_state_noop_without_state_dir(wiz):
    # Must not raise when STATE_DIR does not exist yet.
    wiz.migrate_flat_state()


# --- Feature 010 FR-002: the supported-agent list is single-sourced ----------
#
# AGENTS in bin/agent-container is CANONICAL. The same set is independently
# encoded in entrypoint.sh (dispatch), the Dockerfile (npm installs), the shell
# completions, and the docs. True single-sourcing across Python + shell +
# Dockerfile would need build-time codegen (a new dependency, a new failure
# mode) for a list that changes about once a year, so this is DETECTION, not
# prevention: drift is a red gate rather than a production surprise.

_ROOT = Path(__file__).resolve().parents[2]

# Dockerfile ships npm PACKAGES, whose names do not match the agent names. This
# mapping is itself a fourth encoding of the list, so an unmapped package is a
# hard failure — a rename must never silently drop an agent from the check.
_NPM_PACKAGE_TO_AGENT = {
    "@anthropic-ai/claude-code": "claude",
    "@openai/codex": "codex",
    "@earendil-works/pi-coding-agent": "pi",
    "opencode-ai": "opencode",
}


def _canonical_agents(wiz) -> set[str]:
    return set(wiz.AGENTS)


def test_entrypoint_dispatch_matches_canonical_agent_list(wiz):
    """FR-002: entrypoint.sh's headless dispatch covers exactly AGENTS.

    Matches `<agent>) cmd=(` and no longer `<agent>) exec `. Feature 016 stopped
    the headless path `exec`ing the agent — an `exec` leaves nothing behind to
    complete the run's record or to trap SIGTERM — so the arms now build an argv
    array that the entrypoint runs as a supervised child. The set the guard reads
    is unchanged; only the line it reads it from moved.
    """
    body = (_ROOT / "image" / "entrypoint.sh").read_text()
    block = body.split("run_headless_agent()", 1)[1].split("\n}", 1)[0]
    arms = set(re.findall(r"^\s*([a-z][a-z0-9-]*)\)\s*cmd=\(", block, re.M))
    assert arms == _canonical_agents(wiz), (
        f"entrypoint.sh disagrees with AGENTS: only in entrypoint={arms - _canonical_agents(wiz)}, "
        f"only in AGENTS={_canonical_agents(wiz) - arms}"
    )


def test_entrypoint_writes_to_the_runs_mount_path(wiz):
    """Feature 016: the entrypoint's default runs directory IS the path the CLI
    mounts the runs volume at.

    Two independent encodings of one path — RUNS_MOUNT_PATH, which builds the
    mount, and the entrypoint's fallback, which writes into it. Drift here is
    silent in the worst available way: the container would write its records to
    an ordinary directory in its own filesystem, backed by no volume, so every
    record would vanish with the container while the run reported success and the
    tool reported nothing pending. Nothing else in the suite compares the two.
    """
    body = (_ROOT / "image" / "entrypoint.sh").read_text()
    expected = f'RUNS_DIR="${{AGENT_CONTAINER_RUNS_DIR:-{wiz.RUNS_MOUNT_PATH}}}"'
    assert expected in body, (
        f"entrypoint.sh does not default its runs dir to RUNS_MOUNT_PATH; expected {expected!r}"
    )


def _entrypoint_outcome_arms() -> set[tuple[str, str]]:
    """The `<kind>:<outcome>` pairs entrypoint.sh will consent to write.

    Read from the function definition, which precedes its only call site, so the
    split lands on the table and not on a caller. An unparsed block yields the
    empty set — which fails the comparison below rather than passing it, so a
    regex that stopped matching cannot turn this check into a no-op.
    """
    body = (_ROOT / "image" / "entrypoint.sh").read_text()
    block = body.split("runs_outcome_is_legal()", 1)[1].split("\n}", 1)[0]
    arms: set[tuple[str, str]] = set()
    for line in block.splitlines():
        m = re.match(r"\s*([a-z:|-]+)\)\s*return 0", line)
        if m:
            for pat in m.group(1).split("|"):
                kind, _, outcome = pat.partition(":")
                arms.add((kind, outcome))
    return arms


def test_entrypoint_outcome_vocabulary_matches_the_canonical_one(wiz):
    """Feature 016 C5/FR-003: the closed outcome vocabulary is encoded twice.

    RUN_OUTCOMES is canonical, and the entrypoint carries its own copy because it
    is where every CONTAINER-written record is produced — an ingested record is
    stamped and stored verbatim, so the CLI's validator never sees one. Drift is
    therefore not cosmetic in either direction: a kind or outcome added to
    RUN_OUTCOMES alone would be refused by the container, silently degrading every
    such record to `outcome: null`, while one added to the entrypoint alone would
    put a word in the store that no reader of the vocabulary expects.

    `never-started` is excluded on purpose, and against the NAMED constant rather
    than the literal: it is the one outcome the TOOL authors (C6), for a container
    that never ran, and a record written from inside one disproves it.
    """
    expected = {
        (kind, outcome)
        for kind, outcomes in wiz.RUN_OUTCOMES.items()
        for outcome in outcomes
        if outcome != wiz.RUN_OUTCOME_NEVER_STARTED
    }
    arms = _entrypoint_outcome_arms()
    assert arms == expected, (
        f"entrypoint.sh disagrees with RUN_OUTCOMES: only in entrypoint={arms - expected}, "
        f"only in RUN_OUTCOMES={expected - arms}"
    )


def test_dockerfile_installs_exactly_the_canonical_agents(wiz):
    """FR-002/FR-003: every agent is baked, and nothing extra is."""
    body = (_ROOT / "image" / "Dockerfile").read_text()
    pkgs = set(re.findall(r"npm i -g (?:--ignore-scripts )?(\S+)", body))
    unmapped = pkgs - set(_NPM_PACKAGE_TO_AGENT)
    assert not unmapped, (
        f"Dockerfile installs npm package(s) with no agent mapping: {unmapped}. "
        "Add them to _NPM_PACKAGE_TO_AGENT (or drop them) — an unmapped package "
        "would silently disappear from this check."
    )
    installed = {_NPM_PACKAGE_TO_AGENT[p] for p in pkgs}
    assert installed == _canonical_agents(wiz), (
        f"Dockerfile disagrees with AGENTS: only in Dockerfile="
        f"{installed - _canonical_agents(wiz)}, only in AGENTS={_canonical_agents(wiz) - installed}"
    )


def test_completions_offer_exactly_the_canonical_agents(wiz):
    """FR-013: the tool and its completions must not disagree.

    Asserts the list is both DECLARED and WIRED. Declaring it is not enough: a
    review of this feature caught a zsh script that declared the list but never
    referenced it from the `up` stanza, so `--agent` completed nothing — and an
    earlier version of this very test passed, because it only looked for the
    declaration. The bash side is additionally exercised by invoking the real
    completion in test_completions.sh; zsh has no such harness, which is exactly
    why the wiring check matters here.
    """
    for fname in ("agent-container.bash", "agent-container.zsh"):
        body = (_ROOT / "completions" / fname).read_text()
        m = re.search(r"_agent_container_agents=[\"']([^\"']+)[\"']", body)
        assert m, f"{fname} does not declare the agent list for --agent completion"
        offered = set(m.group(1).split())
        assert offered == _canonical_agents(wiz), (
            f"{fname} disagrees with AGENTS: only in completions="
            f"{offered - _canonical_agents(wiz)}, only in AGENTS={_canonical_agents(wiz) - offered}"
        )
        # Referenced somewhere OTHER than its own assignment, and reachable from
        # a `--agent` completion arm.
        # Comments do NOT count as uses. Found by the guard-proof suite: this file
        # documents the variable in a comment, so the naive check passed for a
        # script that declared the list and never referenced it — the same
        # shape-not-behaviour bug the guard exists to catch, one level up.
        uses = [
            ln
            for ln in body.splitlines()
            if "_agent_container_agents" in ln
            and not re.match(r"\s*#", ln)
            and not re.match(r"\s*(local\s+)?_agent_container_agents=", ln)
        ]
        assert uses, (
            f"{fname} declares the agent list but never uses it (--agent would complete nothing)"
        )
        assert "--agent" in body, f"{fname} never offers the --agent option at all"


def test_orchestration_templates_mount_the_full_volume_set(wiz):
    """FR-007: 'every place that states the number or names of those volumes'
    includes the hand-maintained templates in orchestration/, which claim volume
    parity with the CLI. They are not generated, so nothing else catches drift —
    an operator following a stale template silently loses opencode's state.
    """
    expected = set(wiz.per_container_volumes("PLACEHOLDER"))
    for fname, pattern in (
        ("compose.yaml", r"agent-container-\$\{AGENT_CONTAINER_NAME:-default\}-([a-z-]+):/"),
        ("agent-container.container", r"Volume=agent-container-\$\{NAME\}-([a-z-]+):/"),
    ):
        body = (_ROOT / "orchestration" / fname).read_text()
        mounted = {f"agent-container-PLACEHOLDER-{m}" for m in re.findall(pattern, body)}
        assert mounted == expected, (
            f"orchestration/{fname} is out of sync with per_container_volumes(): "
            f"missing={sorted(expected - mounted)}, extra={sorted(mounted - expected)}"
        )


def test_docs_and_help_name_exactly_the_canonical_agents(wiz):
    """FR-002 names FOUR consumers — CLI, container, completions, and the
    DOCUMENTATION. SC-003 claims zero discrepancies *verified*, so docs cannot
    be the one consumer nothing checks."""
    agents = _canonical_agents(wiz)

    help_text = (_ROOT / "bin" / "agent-container").read_text()
    m = re.search(r'help="Primary agent to run: ([^."]+)\.?"', help_text)
    assert m, "--agent help string not found"
    assert {a.strip() for a in m.group(1).split("|")} == agents

    doc = (_ROOT / "docs" / "execution.md").read_text()
    m = re.search(r"<!-- agents:begin -->(.*?)<!-- agents:end -->", doc, re.S)
    assert m, "docs/execution.md is missing the agents:begin/end marker block"
    documented = set(re.findall(r"`([a-z][a-z0-9-]*)`", m.group(1)))
    assert documented == agents, (
        f"docs/execution.md disagrees with AGENTS: only in docs={documented - agents}, "
        f"only in AGENTS={agents - documented}"
    )


def test_completions_offer_every_cli_command(wiz):
    """The completions' top-level command lists must match the CLI's registered
    commands.

    Added after a review found `redeploy` missing from both scripts: eight
    commands (redeploy/stop/start/wipe from Feature 002, plan/apply/status/
    destroy from Feature 006) had silently accumulated as drift, because nothing
    compared the two. Same failure mode as the agent list, one level up.
    """
    registered = {c.name or c.callback.__name__ for c in wiz.app.registered_commands}
    # `host` is a Typer sub-app (a group), not a command — it still appears at the
    # top level for the user, so the completions must offer it.
    registered |= {g.name or g.typer_instance.info.name for g in wiz.app.registered_groups}
    registered = {n.replace("_", "-") for n in registered if n}

    bash = (_ROOT / "completions" / "agent-container.bash").read_text()
    m = re.search(r'subcommands="([^"]+)"', bash)
    assert m, "bash completion has no subcommands list"
    offered_bash = {w for w in m.group(1).split() if not w.startswith("-")}

    zsh = (_ROOT / "completions" / "agent-container.zsh").read_text()
    block = zsh.split("cmds=(", 1)[1].split("\n    )", 1)[0]
    offered_zsh = set(re.findall(r"^\s+'([a-z-]+):", block, re.M))

    for label, offered in (("bash", offered_bash), ("zsh", offered_zsh)):
        assert offered == registered, (
            f"{label} completion is out of sync with the CLI: "
            f"missing={sorted(registered - offered)}, unknown={sorted(offered - registered)}"
        )


# --- Feature 011: the identity lock -----------------------------------------
#
# Identity is the mechanism by which the tool finds and owns existing
# deployments (Constitution IV). Feature 011 moves FILES; if it moves an
# IDENTITY, every environment an operator already runs becomes an orphan the
# tool can no longer see. This test is the gate the whole feature is measured
# against — baseline captured in research.md R7a BEFORE any change.

IDENTITY_BASELINE = {
    "acme": ("agent-container-acme", 2206),
    "blog": ("agent-container-blog", 2220),
    "scratch": ("agent-container-scratch", 2244),
    "my-box": ("agent-container-my-box", 2204),
    "a": ("agent-container-a", 2297),
    "zzz-999": ("agent-container-zzz-999", 2282),
}

# Feature 016 APPENDED "runs" (the tenth). Feature 011's guarantee is that no
# existing volume NAME or POSITION changed, not that the set can never grow — so
# the tuple grows at the end and every pre-016 entry stays byte-identical where it
# was. Adding a name here is deliberate work; that is the point of the pin.
VOLUME_SUFFIXES = (
    "workspace",
    "claude",
    "codex",
    "pi",
    "opencode",
    "opencode-data",
    "shellenv",
    "tmux",
    "ssh",
    "runs",
)


@pytest.mark.parametrize(("name", "expected"), sorted(IDENTITY_BASELINE.items()))
def test_identity_is_unchanged_by_feature_011(wiz, name, expected):
    """FR-010 / SC-003: container name and port are byte-identical to the
    pre-011 baseline. A single differing byte fails the feature regardless of
    how tidy the layout became."""
    assert (wiz.container_name(name), wiz.port_for_name(name)) == expected


@pytest.mark.parametrize("name", sorted(IDENTITY_BASELINE))
def test_volume_names_are_unchanged_by_feature_011(wiz, name):
    """FR-010: every volume NAME, in canonical order. The shell-env volume
    is the one to watch — Feature 011 moves its MOUNT POINT, and this asserts
    that its NAME does not follow (research R3)."""
    assert wiz.per_container_volumes(name) == [
        f"agent-container-{name}-{s}" for s in VOLUME_SUFFIXES
    ]


def test_only_the_shellenv_mount_path_may_change(wiz):
    """The deliberate exception. Every mount keeps its volume name; exactly one
    mount PATH is permitted to move (`~/.agent-container` → `~/.agent-env`), and
    nothing else may. Written so a stray path edit elsewhere fails here rather
    than surfacing as a stranded volume at runtime."""
    mounts = dict(m.split(":", 1) for m in wiz.all_volume_mounts("acme"))
    assert sorted(mounts) == sorted(f"agent-container-acme-{s}" for s in VOLUME_SUFFIXES)
    fixed = {
        "workspace": "/workspace",
        "claude": "/home/dev/.claude",
        "codex": "/home/dev/.codex",
        "pi": "/home/dev/.pi",
        "opencode": "/home/dev/.config/opencode",
        "opencode-data": "/home/dev/.local/share/opencode",
        "tmux": "/home/dev/.config/tmux",
        "ssh": "/home/dev/.ssh",
        # Feature 016. Outside /home/dev deliberately: the account of a run must
        # not live where the subject of the account can edit it (research R2).
        "runs": "/var/lib/agent-container/runs",
    }
    for suffix, path in fixed.items():
        assert mounts[f"agent-container-acme-{suffix}"] == path, f"{suffix} mount path moved"
    assert mounts["agent-container-acme-shellenv"] in (
        "/home/dev/.agent-container",  # pre-US3
        "/home/dev/.agent-env",  # post-US3
    )


# --- Feature 011 US1: project config resolution ------------------------------


def test_env_chain_is_symmetric_across_both_levels(wiz, tmp_path, monkeypatch):
    """FR-001b / contract C2. Each level has a per-environment file and a shared
    default, and the bare ./.env is NOT in the chain — a `.env` in a project root
    belongs to whoever put it there (Compose, direnv, a framework)."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    monkeypatch.setattr(wiz, "CONFIG_DIR", tmp_path / "userconf")
    got = [str(p) for p in wiz.env_file_candidates("acme", root)]
    assert got == [
        str(root / ".agent-container" / "acme.env"),
        str(root / ".agent-container" / ".env"),
        str(tmp_path / "userconf" / "acme.env"),
        str(tmp_path / "userconf" / ".env"),
    ]
    assert str(root / ".env") not in got  # FR-001b: not ours to claim


def test_env_chain_falls_back_to_user_level_outside_a_project(wiz, tmp_path, monkeypatch):
    """No project root → only the user-level half. The tool must not invent a
    project config directory for a bare directory."""
    monkeypatch.setattr(wiz, "CONFIG_DIR", tmp_path / "userconf")
    got = [str(p) for p in wiz.env_file_candidates("acme", tmp_path / "nowhere")]
    assert got == [str(tmp_path / "userconf" / "acme.env"), str(tmp_path / "userconf" / ".env")]


def test_project_root_is_found_from_any_subdirectory(wiz, tmp_path):
    """FR-015 / contract C1: discovery walks UP, so the tool behaves identically
    from any subdirectory, and the layout is location-independent."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    nested = root / "src" / "deep" / "nested"
    nested.mkdir(parents=True)
    assert wiz.find_project_root(nested) == root.resolve()
    assert wiz.project_config_dir(nested) == root.resolve() / ".agent-container"
    assert wiz.find_project_root(tmp_path / "elsewhere") is None


def test_no_tool_owned_file_remains_in_a_consolidated_project_root(wiz, tmp_path, monkeypatch):
    """FR-002 / SC-001 — the POSITIVE property (analysis C4).

    The refusal test asserts that known-superseded names are rejected; it would
    still pass if some other tool-owned name were left behind, because it only
    looks for names it already knows. This asserts the complement: for a
    correctly consolidated project, nothing the tool consumes sits in the root.
    """
    root = tmp_path / "proj"
    cfg = root / ".agent-container"
    cfg.mkdir(parents=True)
    for f in ("acme.env", "acme.services.yaml", "environments.yaml"):
        (cfg / f).write_text("x\n")
    (root / "README.md").write_text("mine\n")  # the operator's own file
    monkeypatch.setattr(wiz, "CONFIG_DIR", tmp_path / "userconf")

    consumed = {p.name for p in wiz.env_file_candidates("acme", root)}
    consumed |= {p.name for p in wiz.discover_apikey_files("acme", root).values()}
    stray = [e.name for e in root.iterdir() if e.is_file() and e.name in consumed]
    assert stray == [], f"tool-owned files left in the project root: {stray}"
    assert not list(root.glob("agent-container.*")), "old-layout names still present"


# --- Feature 012: per-agent facts are fixtures, not comments -----------------


def test_builtin_default_fixture_covers_exactly_the_agents(wiz):
    """Every supported agent must have a recorded answer to "does it reach a
    provider with no operator credential?". A fifth agent added to AGENTS without
    probing it FAILS here rather than silently inheriting "no default" — the
    defect Feature 012 exists to surface is precisely an unnoticed default."""
    assert set(wiz.AGENT_BUILTIN_DEFAULT) == set(wiz.AGENTS), (
        f"AGENT_BUILTIN_DEFAULT disagrees with AGENTS: "
        f"missing={sorted(set(wiz.AGENTS) - set(wiz.AGENT_BUILTIN_DEFAULT))} "
        f"extra={sorted(set(wiz.AGENT_BUILTIN_DEFAULT) - set(wiz.AGENTS))}"
    )
    # opencode's value is not a guess: Feature 010's probe ran it with no
    # credential and it answered over the network.
    assert wiz.AGENT_BUILTIN_DEFAULT["opencode"] == "big-pickle"
    for agent, provider in wiz.AGENT_BUILTIN_DEFAULT.items():
        assert provider is None or provider in wiz.PROVIDERS, (
            f"{agent}'s built-in default {provider!r} is not in PROVIDERS, so the "
            f"tool cannot say what it may reach"
        )


def test_honours_proxy_fixture_covers_exactly_the_agents(wiz):
    """FR-008's honest-strength claim rests on this table, and every entry in it
    was established by RUNNING the agent against a black-holed proxy (research
    R1), never read from documentation."""
    assert set(wiz.AGENT_HONOURS_PROXY) == set(wiz.AGENTS), (
        f"AGENT_HONOURS_PROXY disagrees with AGENTS: "
        f"missing={sorted(set(wiz.AGENTS) - set(wiz.AGENT_HONOURS_PROXY))} "
        f"extra={sorted(set(wiz.AGENT_HONOURS_PROXY) - set(wiz.AGENTS))}"
    )


def test_unprobed_agent_defaults_to_not_honouring(wiz):
    """The safe default, and the opposite of what a hand-maintained comment gives.

    An agent absent from the table must read as NOT known to honour the proxy, so
    `strict` refuses it until someone probes it. `.get(agent)` truthiness is the
    contract; a KeyError or a True default would both be wrong.
    """
    assert wiz.AGENT_HONOURS_PROXY.get("some-future-agent") is None
    assert not wiz.AGENT_HONOURS_PROXY.get("some-future-agent", False)


def test_every_provider_maps_to_at_least_one_host(wiz):
    for name, hosts in wiz.PROVIDERS.items():
        assert hosts, f"provider {name!r} maps to no hosts, so declaring it permits nothing"
        assert all(wiz.HOSTNAME_RE.fullmatch(h) for h in hosts), f"{name}: non-hostname in {hosts}"


# --- the threat model tracks the feature (Constitution 2.2.0) ---------------
# Parsed with a regex rather than a parser, deliberately and with the irony noted:
# docs/threat-model.md §5 T12 catalogues regex scanners that missed shapes they
# were not written for. This one reads a MARKDOWN TABLE THIS REPO AUTHORS — not
# adversarial input, and markdown has no stdlib parser. The failure mode differs.


# Resolved through a FUNCTION, not bound at import. A module-level
# `_THREAT_MODEL = _ROOT / …` would capture the real path before any test could
# monkeypatch `_ROOT`, so the guard-can-fail proofs would copy a file into a fake
# root, corrupt it, and then silently assert against the REAL document — passing
# for the wrong reason. That is the exact defect class this file exists to catch.
def _threat_model_path() -> Path:
    return _ROOT / "docs" / "threat-model.md"


_TM_ROW = re.compile(r"^\|\s*(\d{3})[^|]*\|\s*(✅|⬜)\s*\|([^|]*)\|", re.M)


def _tm_rows() -> list[tuple[str, str, str]]:
    return [m.groups() for m in _TM_ROW.finditer(_threat_model_path().read_text(encoding="utf-8"))]


def test_threat_model_names_every_feature(wiz):
    """Constitution 2.2.0: the maintenance table names every feature.

    A MISSING ROW IS THE COMMON FAILURE — a feature lands, nobody re-reads the
    threat model, and the document still reads as current because absence is
    invisible. This turns that into a gate failure.

    CEILING, STATED: this checks that a row EXISTS, never that the analysis behind
    it happened. A green gate here means "the table has rows", not "the threat
    model is current". Reading it as the latter is the failure this guard cannot
    catch.
    """
    text = _threat_model_path().read_text(encoding="utf-8")
    documented = {num for num, _mark, _threats in _tm_rows()}
    if "001–011" in text:  # a single baseline row covers the pre-012 features
        documented |= {f"{n:03d}" for n in range(1, 12)}
    on_disk = {d.name[:3] for d in (_ROOT / "specs").iterdir() if d.is_dir()}
    missing = sorted(on_disk - documented)
    assert not missing, (
        f"docs/threat-model.md has no maintenance row for: {missing}. Add one "
        f"recording which threats the feature mitigates, leaves open, and NEWLY "
        f"INTRODUCES — or the posture silently stops describing the system."
    )


def test_threat_model_reconciled_rows_name_their_threats(wiz):
    """A ✅ with an empty threats cell is a ticked box, not an analysis.

    This is the T12 shape the document itself catalogues — a check that passes
    while the thing it names is broken. Requiring the row to SAY something is the
    cheapest defence against reconciling by checkbox.
    """
    empty = [num for num, mark, threats in _tm_rows() if mark == "✅" and not threats.strip()]
    assert not empty, (
        f"feature(s) {empty} are marked reconciled but name no threats. Write "
        f"'none' explicitly if the feature genuinely touched no boundary — silence "
        f"and 'nothing changed' must not look identical."
    )


# --- Feature 012: the entrypoint's rule shape (adversarial review) ------------


def _entrypoint_accept_rules(wiz):
    """Every `-A OUTPUT ... -j ACCEPT` line in the egress entrypoint."""
    text = (wiz.REPO_ROOT / "image" / "egress" / "entrypoint.sh").read_text(encoding="utf-8")
    return [
        ln.strip()
        for ln in text.splitlines()
        if "-A OUTPUT" in ln and "-j ACCEPT" in ln and not ln.strip().startswith("#")
    ]


def _rule_is_scoped(rule: str) -> bool:
    """A port-matching ACCEPT must also constrain WHO or WHERE, not just which port.

    THREE CORRECTIONS from adversarial review, each of which let the D1 hole be
    reopened with the whole suite green:

    * `-o eth0` was accepted as "scoping". It is the opposite — eth0 is the route to
      everywhere. Only `-o lo` narrows anything, so the interface test is now
      specific rather than "an -o is present".
    * `--dports` and `-m multiport` were invisible, so the same hole written in the
      multiport form passed.
    * `--destination`/`--out-interface` long forms were invisible too.
    """
    if not any(f in rule for f in ("--dport", "--dports")):
        return True  # not a port rule; the other matches govern it
    scoped_by_destination = " -d " in rule or " --destination " in rule
    scoped_by_loopback = " -o lo" in rule or " --out-interface lo" in rule
    scoped_by_owner = "-m owner" in rule
    return scoped_by_destination or scoped_by_loopback or scoped_by_owner


def test_no_accept_rule_matches_on_destination_port_alone(wiz):
    """An ACCEPT matching only `--dport` is an unrestricted egress channel.

    Found by adversarial review: `-p tcp --dport 3128:3129 -j ACCEPT` carried no
    `-d` and no `-o`, so a connection to ANY address on those ports was accepted
    before `-P OUTPUT DROP` could apply. The nat REDIRECT only matches dport 443/80,
    so squid never saw it, nothing was logged, and `enforced: true` still held.

    Asserted structurally rather than by naming the two ports, because the next
    such rule will have a different number.
    """
    for rule in _entrypoint_accept_rules(wiz):
        assert _rule_is_scoped(rule), (
            f"ACCEPT matches on destination port alone, so it admits ANY address: {rule!r}"
        )


def test_generated_port_rules_are_scoped_to_a_host(wiz):
    """The same invariant on the GENERATED side — SC-010 is 'that host and that
    port only', so a generated rule must never widen to a whole port."""
    dests = [("gh", "github.com", 22, "spec"), ("db", "db.example.com", 5432, "spec")]
    for line in wiz.build_netfilter_rules(dests).splitlines():
        if "-j ACCEPT" in line and "--dport" in line:
            assert _rule_is_scoped(line), f"generated rule is unscoped: {line!r}"


def test_the_scoping_guard_can_fail():
    """Proof the check above is not vacuous — an absence assertion passes just as
    happily against a rule set that contains no port rules at all.

    The rejected cases now include the three forms adversarial review found the
    first version blind to: `-o eth0` (which scopes nothing), and the multiport and
    long-option spellings of the same hole.
    """
    # Must be REJECTED — each is an unrestricted egress channel.
    assert not _rule_is_scoped("iptables -A OUTPUT -p tcp --dport 3128:3129 -j ACCEPT")
    assert not _rule_is_scoped("iptables -A OUTPUT -o eth0 -p tcp --dport 3128 -j ACCEPT"), (
        "eth0 is the route to everywhere; it is not scoping"
    )
    assert not _rule_is_scoped(
        "iptables -A OUTPUT -p tcp -m multiport --dports 3128,3129 -j ACCEPT"
    )
    # Must be ACCEPTED — each genuinely narrows the destination.
    assert _rule_is_scoped("iptables -A OUTPUT -d 127.0.0.1 -p tcp --dport 3128 -j ACCEPT")
    assert _rule_is_scoped("iptables -A OUTPUT -o lo -p tcp --dport 53 -j ACCEPT")
    assert _rule_is_scoped("iptables -A OUTPUT --destination 10.0.0.1 -p tcp --dport 22 -j ACCEPT")
    assert _rule_is_scoped("iptables -A OUTPUT -m owner --uid-owner 31 -p tcp --dport 80 -j ACCEPT")


def test_the_forward_proxy_constrains_the_PORT_not_only_the_HOST(wiz):
    """`dstdomain` matches a name and says nothing about the port.

    Measured: before this restriction, `CONNECT <declared-host>:6379` through the
    tool's own forward proxy was ALLOWED and squid dialled out
    (`TCP_TUNNEL/503 … HIER_DIRECT/<ip>` — the 503 was the origin not listening,
    not squid refusing). A PORTLESS entry means "this host over HTTP/HTTPS"
    everywhere else in the feature, so admitting every port contradicted a printed
    guarantee. After: `TCP_DENIED/403`.
    """
    conf = (wiz.REPO_ROOT / "image" / "egress" / "squid.conf").read_text(encoding="utf-8")
    code = [ln.strip() for ln in conf.splitlines() if not ln.strip().startswith("#")]
    joined = "\n".join(code)
    assert "acl SSL_ports port 443" in joined
    assert "http_access deny CONNECT !SSL_ports" in joined
    assert "http_access deny !Safe_ports" in joined
    # ORDER IS THE PROPERTY: squid takes the first match, so the denies must precede
    # the allowlist rule or they never run.
    deny_at = next(i for i, ln in enumerate(code) if "deny CONNECT !SSL_ports" in ln)
    allow_at = next(i for i, ln in enumerate(code) if "http_access allow allowed_http" in ln)
    assert deny_at < allow_at, "the port denies must be evaluated before the host allow"


def test_declared_port_rules_are_installed_after_the_resolver(wiz):
    """iptables resolves `-d <hostname>` AT INSERT TIME, so the fragment must be
    sourced after unbound is up.

    Sourced from inside install_rules it could never work: the DNS rewrite has
    already pointed 127.0.0.11:53 at 127.0.0.1:53 and unbound did not exist yet, so
    every declared `{host, port}` ACCEPT was silently skipped — FR-018 non-functional,
    and `git push` over declared SSH dropped at push time.
    """
    lines = (
        (wiz.REPO_ROOT / "image" / "egress" / "entrypoint.sh")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    def _stmt(needle: str) -> int:
        """Line number of the EXECUTABLE statement, never a comment mentioning it.

        The first draft of this test used `text.index(...)` and matched the prose in
        the wrapper's own comment — a check satisfied by a sentence rather than by
        the code it names, which is precisely the defect class this file exists to
        catch. Found by the gate, kept as a comment so it is not reintroduced.
        """
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if stripped.startswith("#"):
                continue
            if needle in stripped:
                return i
        raise AssertionError(f"no executable statement matching {needle!r}")

    unbound_at = _stmt("unbound -c /etc/unbound/unbound.conf")
    ports_at = _stmt("/etc/egress/ports.rules")
    policy_at = _stmt("iptables -P OUTPUT DROP")
    assert unbound_at < ports_at, "declared port rules are sourced before the resolver exists"
    assert ports_at < policy_at, "declared ports must be admitted before the policy flips to DROP"


def test_iptables_failures_cannot_be_swallowed(wiz):
    """`install_rules || die` suppressed `set -e` for the whole function body, and
    the function's status was that of its last command — which always succeeded."""
    text = (wiz.REPO_ROOT / "image" / "egress" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "command iptables" in text, "the checking wrapper is gone"
    assert "netfilter rule REJECTED" in text, "a failed rule must name itself"
    # CODE ONLY. The comment above the wrapper quotes the old form to explain why it
    # was wrong, and a naive substring check matched that prose — an absence
    # assertion satisfied by the very sentence documenting the fix.
    code = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    assert not any("install_rules || die" in ln for ln in code), (
        "the AND-OR form suppresses set -e for the entire function body"
    )


def test_the_boundary_resolver_binds_loopback_only(wiz):
    """Copilot review, verified with a control: on `interface: 0.0.0.0` the resolver
    also answered on the egress container's PROJECT-NETWORK address, which a sidecar
    declared OUTSIDE the boundary can route to.

    Measured before/after from a container on the same network but NOT sharing the
    namespace: pre-fix the undeclared-to-them name resolved (160.79.104.10); after,
    `Connection refused`. A sidecar that is outside by design must not inherit the
    boundary's allowlisted resolution as well as its free egress.
    """
    conf = (wiz.REPO_ROOT / "image" / "egress" / "unbound.conf").read_text(encoding="utf-8")
    code = [ln.strip() for ln in conf.splitlines() if not ln.strip().startswith("#")]
    assert "interface: 127.0.0.1" in code, "the resolver must not bind a routable address"
    assert not any(ln.startswith("interface: 0.0.0.0") for ln in code)
    assert "access-control: 0.0.0.0/0 allow" not in code, (
        "a blanket allow re-opens what the loopback bind closes if the bind ever widens"
    )
