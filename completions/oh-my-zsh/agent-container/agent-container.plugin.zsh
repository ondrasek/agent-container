# oh-my-zsh plugin for the agent-container CLI (bin/agent-container).
#
# Install (symlink — recommended, auto-detects the repo):
#   ln -s "<repo>/completions/oh-my-zsh/agent-container" \
#         "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/agent-container"
#   then add `agent-container` to plugins=(...) in ~/.zshrc.
#
# Install (copy): if you copy this dir instead of symlinking it, the repo can no
#   longer be found from the plugin's location — export AGENT_CONTAINER_REPO=<repo> in
#   ~/.zshrc BEFORE oh-my-zsh is sourced.
#
# What it provides:
#   * PATH wiring so `agent-container` is callable from anywhere.
#   * zsh completions for the CLI (sources the canonical completions/agent-container.zsh
#     — single source of truth; oh-my-zsh has already run compinit by the time it
#     sources plugin files, so its `compdef` call takes effect).
#   * a few convenience aliases.

# Repo root: resolved from this file's real path (`:A` follows the symlink into
# $ZSH_CUSTOM/plugins). Respects a pre-set AGENT_CONTAINER_REPO (needed for copy installs).
: ${AGENT_CONTAINER_REPO:=${0:A:h:h:h:h}}

# --- shell integration: put the tool on PATH ------------------------------
# Prefer the canonical user bin dir, respecting $XDG_BIN_HOME and defaulting to
# ~/.local/bin. If agent-container is installed (symlinked) there, just ensure that
# dir is on PATH; otherwise fall back to the repo's own bin/ so the plugin works
# with no separate install step. (The tool itself already honors
# XDG_STATE_HOME / XDG_CONFIG_HOME for its state and config.)
() {
    local xdg_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
    if [[ -e "$xdg_bin/agent-container" ]]; then
        [[ ":$PATH:" == *":$xdg_bin:"* ]] || export PATH="$xdg_bin:$PATH"
    elif [[ -d "$AGENT_CONTAINER_REPO/bin" ]]; then
        [[ ":$PATH:" == *":$AGENT_CONTAINER_REPO/bin:"* ]] || export PATH="$AGENT_CONTAINER_REPO/bin:$PATH"
    fi
}

# --- completions -----------------------------------------------------------
# Source the canonical dual-mode script; when sourced (not autoloaded) it
# registers via `compdef`, which exists because omz ran compinit first.
if (( $+functions[compdef] )); then
    [[ -r "$AGENT_CONTAINER_REPO/completions/agent-container.zsh" ]] && source "$AGENT_CONTAINER_REPO/completions/agent-container.zsh"
fi

# --- convenience aliases (remove in ~/.zshrc after the plugin if unwanted) --
alias ae='agent-container'
alias aeu='agent-container up'
alias aea='agent-container attach'
alias ael='agent-container list'
