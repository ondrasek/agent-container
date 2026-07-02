# oh-my-zsh plugin for the remote-persistent-devenv CLIs (devenv, devenv-wiz).
#
# Install (symlink — recommended, auto-detects the repo):
#   ln -s "<repo>/completions/oh-my-zsh/devenv" \
#         "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/devenv"
#   then add `devenv` to plugins=(...) in ~/.zshrc.
#
# Install (copy): if you copy this dir instead of symlinking it, the repo can no
#   longer be found from the plugin's location — export DEVENV_REPO=<repo> in
#   ~/.zshrc BEFORE oh-my-zsh is sourced.
#
# What it provides:
#   * PATH wiring so `devenv` / `devenv-wiz` are callable from anywhere.
#   * zsh completions for both CLIs (sources the canonical completions/*.zsh —
#     single source of truth; oh-my-zsh has already run compinit by the time it
#     sources plugin files, so their `compdef` calls take effect).
#   * a few convenience aliases.

# Repo root: resolved from this file's real path (`:A` follows the symlink into
# $ZSH_CUSTOM/plugins). Respects a pre-set DEVENV_REPO (needed for copy installs).
: ${DEVENV_REPO:=${0:A:h:h:h:h}}

# --- shell integration: put the tools on PATH ------------------------------
# Prefer the canonical user bin dir, respecting $XDG_BIN_HOME and defaulting to
# ~/.local/bin. If devenv/devenv-wiz are installed (symlinked) there, just ensure
# that dir is on PATH; otherwise fall back to the repo's own bin/ so the plugin
# works with no separate install step. (The tools themselves already honor
# XDG_STATE_HOME / XDG_CONFIG_HOME for their state and config.)
() {
    local xdg_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
    if [[ -e "$xdg_bin/devenv-wiz" || -e "$xdg_bin/devenv" ]]; then
        [[ ":$PATH:" == *":$xdg_bin:"* ]] || export PATH="$xdg_bin:$PATH"
    elif [[ -d "$DEVENV_REPO/bin" ]]; then
        [[ ":$PATH:" == *":$DEVENV_REPO/bin:"* ]] || export PATH="$DEVENV_REPO/bin:$PATH"
    fi
}

# --- completions -----------------------------------------------------------
# Source the canonical dual-mode scripts; when sourced (not autoloaded) they
# register via `compdef`, which exists because omz ran compinit first.
if (( $+functions[compdef] )); then
    [[ -r "$DEVENV_REPO/completions/devenv.zsh" ]]     && source "$DEVENV_REPO/completions/devenv.zsh"
    [[ -r "$DEVENV_REPO/completions/devenv-wiz.zsh" ]] && source "$DEVENV_REPO/completions/devenv-wiz.zsh"
fi

# --- convenience aliases (remove in ~/.zshrc after the plugin if unwanted) --
alias dv='devenv'
alias dvw='devenv-wiz'
alias dva='devenv-wiz attach'
alias dvl='devenv-wiz list'
alias dvu='devenv-wiz up'
