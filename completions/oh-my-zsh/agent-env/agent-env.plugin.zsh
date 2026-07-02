# oh-my-zsh plugin for the agent-env CLI (bin/agent-env).
#
# Install (symlink — recommended, auto-detects the repo):
#   ln -s "<repo>/completions/oh-my-zsh/agent-env" \
#         "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/agent-env"
#   then add `agent-env` to plugins=(...) in ~/.zshrc.
#
# Install (copy): if you copy this dir instead of symlinking it, the repo can no
#   longer be found from the plugin's location — export AGENT_ENV_REPO=<repo> in
#   ~/.zshrc BEFORE oh-my-zsh is sourced.
#
# What it provides:
#   * PATH wiring so `agent-env` is callable from anywhere.
#   * zsh completions for the CLI (sources the canonical completions/agent-env.zsh
#     — single source of truth; oh-my-zsh has already run compinit by the time it
#     sources plugin files, so its `compdef` call takes effect).
#   * a few convenience aliases.

# Repo root: resolved from this file's real path (`:A` follows the symlink into
# $ZSH_CUSTOM/plugins). Respects a pre-set AGENT_ENV_REPO (needed for copy installs).
: ${AGENT_ENV_REPO:=${0:A:h:h:h:h}}

# --- shell integration: put the tool on PATH ------------------------------
# Prefer the canonical user bin dir, respecting $XDG_BIN_HOME and defaulting to
# ~/.local/bin. If agent-env is installed (symlinked) there, just ensure that
# dir is on PATH; otherwise fall back to the repo's own bin/ so the plugin works
# with no separate install step. (The tool itself already honors
# XDG_STATE_HOME / XDG_CONFIG_HOME for its state and config.)
() {
    local xdg_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
    if [[ -e "$xdg_bin/agent-env" ]]; then
        [[ ":$PATH:" == *":$xdg_bin:"* ]] || export PATH="$xdg_bin:$PATH"
    elif [[ -d "$AGENT_ENV_REPO/bin" ]]; then
        [[ ":$PATH:" == *":$AGENT_ENV_REPO/bin:"* ]] || export PATH="$AGENT_ENV_REPO/bin:$PATH"
    fi
}

# --- completions -----------------------------------------------------------
# Source the canonical dual-mode script; when sourced (not autoloaded) it
# registers via `compdef`, which exists because omz ran compinit first.
if (( $+functions[compdef] )); then
    [[ -r "$AGENT_ENV_REPO/completions/agent-env.zsh" ]] && source "$AGENT_ENV_REPO/completions/agent-env.zsh"
fi

# --- convenience aliases (remove in ~/.zshrc after the plugin if unwanted) --
alias ae='agent-env'
alias aeu='agent-env up'
alias aea='agent-env attach'
alias ael='agent-env list'
