#compdef devenv-wiz
# zsh completion for `devenv-wiz` (bin/devenv-wiz).
#
# Install (autoload):  copy/symlink this file as `_devenv-wiz` into a dir on
#                      $fpath (e.g. ~/.zfunc), then `autoload -U compinit && compinit`.
# Install (source):    source /path/to/completions/devenv-wiz.zsh from ~/.zshrc
#                      AFTER `compinit` has run.
#
# Completion keys off the command NAME, so `devenv-wiz` must be on PATH
# (symlink bin/devenv-wiz into ~/.local/bin).
#
# Container names are gathered directly in-shell — devenv-wiz/uv is NEVER spun
# up on TAB. Candidate set = de-duplicated union of:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/devenv/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and never executed/sourced.

__devenv_wiz_names() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/devenv"
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/devenv"
    local hosts="${config_dir}/hosts.conf"
    local -aU names
    local f line key
    for f in "$state_dir"/*.port(N); do
        names+=("${f:t:r}")
    done
    if [[ -f "$hosts" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line#"${line%%[![:space:]]*}"}"
            [[ -z "$line" || "$line" == '#'* ]] && continue
            line="${line#export }"
            line="${line#"${line%%[![:space:]]*}"}"
            key="${line%%=*}"
            key="${key%"${key##*[![:space:]]}"}"
            [[ "$key" == *_HOST ]] || continue
            key="${key%_HOST}"
            key="${key//_/-}"
            key="${(L)key}"
            names+=("$key")
        done < "$hosts"
    fi
    compadd -a names
}

_devenv-wiz() {
    local context state state_descr line
    typeset -A opt_args
    local -a cmds
    cmds=(
        'build:Build the image at the repo root'
        'up:Start a container (detached)'
        'down:Stop and remove a container'
        'purge:Stop, remove, and delete all per-container volumes'
        'list:List containers (plus stale state files)'
        'attach:Attach via ssh + tmux (local state or hosts.conf)'
        'logs:Tail container logs'
        'menu:Interactive wizard'
        'completions:Print a checked-in completion script'
    )

    _arguments -C \
        '(- *)--self-test[Run doctests + interop corpus checks]' \
        '(- *)--help[Show help]' \
        '1:command:->command' \
        '*::arg:->args' && return 0

    case $state in
        command)
            _describe -t commands 'devenv-wiz command' cmds
            ;;
        args)
            case $line[1] in
                up)
                    _arguments \
                        '*--mount[Bind-mount a host dir read-write]:directory:_files -/' \
                        '*:container:__devenv_wiz_names'
                    ;;
                down)
                    _arguments \
                        '--purge[Also delete all per-container volumes]' \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__devenv_wiz_names'
                    ;;
                purge)
                    _arguments \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__devenv_wiz_names'
                    ;;
                list)
                    _arguments '--json[Emit machine-readable JSON]'
                    ;;
                attach)
                    _arguments \
                        '--local[Force local target (state file)]' \
                        '--remote[Force remote target (hosts.conf)]' \
                        '--user[SSH user (default: DEVENV_USER or dev)]:user:' \
                        '--host[Override the resolved host]:host:_hosts' \
                        '*:container:__devenv_wiz_names'
                    ;;
                logs)
                    _arguments \
                        '--no-follow[Print logs without following]' \
                        '*:container:__devenv_wiz_names'
                    ;;
                completions)
                    _arguments '1:shell:(bash zsh)'
                    ;;
            esac
            ;;
    esac
}

# Dual-mode: works whether autoloaded from $fpath as `_devenv-wiz` or sourced.
if [[ "$funcstack[1]" == "_devenv-wiz" ]]; then
    _devenv-wiz "$@"
else
    (( $+functions[compdef] )) && compdef _devenv-wiz devenv-wiz
fi
