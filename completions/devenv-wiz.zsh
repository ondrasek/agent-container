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
# up on TAB. Candidate names come from:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/devenv/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and never executed/sourced. Names go through `compadd -a`
# (array add), so an embedded `$(...)` in a hostile name is never expanded.

# Gather state-file names into the caller's `names` array.
__devenv_wiz_gather_local() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/devenv" f
    for f in "$state_dir"/*.port(N); do
        names+=("${f:t:r}")
    done
}

# Gather hosts.conf-derived names into the caller's `names` array.
__devenv_wiz_gather_hosts() {
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/devenv"
    local hosts="${config_dir}/hosts.conf" line key
    [[ -f "$hosts" ]] || return
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
        names+=("${(L)key}")
    done < "$hosts"
}

# State-only names (local containers): safe source for down/logs/purge.
__devenv_wiz_names_local() {
    local -aU names
    __devenv_wiz_gather_local
    compadd -a names
}

# Union (local + remote): used by up/attach.
__devenv_wiz_names() {
    local -aU names
    __devenv_wiz_gather_local
    __devenv_wiz_gather_hosts
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
                        '--env-file[Bypass env-file resolution; path must exist]:file:_files' \
                        '*:container:__devenv_wiz_names'
                    ;;
                down)
                    _arguments \
                        '--purge[Also delete all per-container volumes]' \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__devenv_wiz_names_local'
                    ;;
                purge)
                    _arguments \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__devenv_wiz_names_local'
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
                        '*:container:__devenv_wiz_names_local'
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
