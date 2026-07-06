"""Pure-logic tests: every value here pins the byte-for-byte on-disk contract
that agent-container defines — the port hash, container/volume naming, env-file
resolution order, and hosts.conf parsing. These constants are load-bearing;
the shell completions read the same state files, so do not 'fix' them casually.
"""

from __future__ import annotations

import pytest

# --- port hash: 2200 + (sum of char codes mod 100) ---------------------------

# Ground truth: the deterministic port hash (2200 + sum-of-ASCII mod 100).
PORT_CORPUS = {
    "acme": 2206,       # 406 % 100 = 6
    "blog": 2220,       # 420
    "scratch": 2244,    # 744
    "my-box": 2204,     # 604 ('-' is 45 and counts)
    "a": 2297,          # 97 — single char lands near the top of the window
    "devbox123": 2298,  # 798 — digits count via their ASCII codes
    "zz": 2244,         # 244 wraps: collides with 'scratch' by design
    "0": 2248,          # 48
    "a_b-c9": 2291,     # 491 — '_' (95) and '-' (45) both count
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
    # workspace, claude, codex, pi, shellenv, tmux).
    assert wiz.claude_volume_name("acme") == "agent-container-acme-claude"
    assert wiz.codex_volume_name("acme") == "agent-container-acme-codex"
    assert wiz.pi_volume_name("acme") == "agent-container-acme-pi"
    assert wiz.shellenv_volume_name("acme") == "agent-container-acme-shellenv"
    assert wiz.tmux_volume_name("acme") == "agent-container-acme-tmux"


# --- name validation: ^[a-z0-9][a-z0-9_-]*$ ------------------------------------


@pytest.mark.parametrize("name", ["acme", "a", "0", "my-box", "a_b-c9", "9to5", "x" * 64])
def test_validate_name_accepts(wiz, name):
    assert wiz.validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "Bad",        # uppercase anywhere
        "ACME",
        "-leading",   # must start with [a-z0-9]
        "_leading",
        "has space",
        "has.dot",
        "café",       # non-ASCII would break ord()/printf parity
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
        "a;b",           # command separator
        "$(x)",          # command substitution
        "a b",           # whitespace (bash would word-split into two args)
        "`id`",          # backtick substitution
        "a|b",
        "a&b",
        "a>b",
        "",              # empty is not a valid window name
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
    cands = wiz.env_file_candidates("acme", tmp_path / "work")
    assert cands == [
        tmp_path / "work" / ".env",
        wiz.CONFIG_DIR / "acme.env",
        wiz.CONFIG_DIR / ".env",
    ]


def test_resolve_env_file_prefers_cwd(wiz, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (work / ".env").write_text("X=1\n")
    (wiz.CONFIG_DIR / "acme.env").write_text("X=2\n")
    (wiz.CONFIG_DIR / ".env").write_text("X=3\n")
    assert wiz.resolve_env_file("acme") == work / ".env"


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
    wiz.write_state("acme", 2206)
    f = wiz.state_file("acme")
    assert f == wiz.STATE_DIR / "acme.port"
    assert f.read_text() == "2206\n"  # exact bytes agent-container writes; completions read these
    assert wiz.read_state_port("acme") == "2206"


def test_state_read_missing_and_empty(wiz):
    assert wiz.read_state_port("ghost") is None
    wiz.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.STATE_DIR / "empty.port").write_text("")
    assert wiz.read_state_port("empty") is None


def test_clear_state(wiz):
    wiz.write_state("acme", 2206)
    wiz.clear_state("acme")
    assert not wiz.state_file("acme").exists()
    wiz.clear_state("acme")  # idempotent on missing file


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
