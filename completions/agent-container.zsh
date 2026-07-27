#compdef agent-container
# zsh completion for `agent-container` (bin/agent-container).
#
# Install (autoload):  copy/symlink this file as `_agent-container` into a dir on
#                      $fpath (e.g. ~/.zfunc), then `autoload -U compinit && compinit`.
# Install (source):    source /path/to/completions/agent-container.zsh from ~/.zshrc
#                      AFTER `compinit` has run.
#
# Completion keys off the command NAME, so `agent-container` must be on PATH
# (symlink bin/agent-container into ~/.local/bin).
#
# Container names are gathered directly in-shell — agent-container/uv is NEVER spun
# up on TAB. Candidate names come from:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and never executed/sourced. Names go through `compadd -a`
# (array add), so an embedded `$(...)` in a hostile name is never expanded.

# Gather state-file names into the caller's `names` array.
__agent_container_gather_local() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-container" f
    # Per-host state (<state>/<host>/<name>.port) plus any legacy flat files.
    for f in "$state_dir"/*.port(N) "$state_dir"/*/*.port(N); do
        names+=("${f:t:r}")
    done
}

# Gather hosts.conf-derived names into the caller's `names` array.
__agent_container_gather_hosts() {
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/agent-container"
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
__agent_container_names_local() {
    local -aU names
    __agent_container_gather_local
    compadd -a names
}

# Union (local + remote): used by up/attach.
__agent_container_names() {
    local -aU names
    __agent_container_gather_local
    __agent_container_gather_hosts
    compadd -a names
}

_agent-container() {
    local context state state_descr line
    typeset -A opt_args
    # Feature 010 FR-013 / FR-002: the supported-agent list, ONE assignment so the
    # hermetic agreement test can parse it and fail if it drifts from AGENTS in
    # bin/agent-container (the canonical source). Local by preference, not by
    # necessity — a file-level global also works (verified).
    #
    # Expand it as ${_agent_container_agents}, NEVER ${=...}. The split flag turns
    # this ONE _arguments spec into four malformed words, and `--agent` then
    # silently completes nothing while `--mode` (a literal list) still works. The
    # declaration and the reference both look correct, so neither a grep-based
    # test nor reading the diff catches it — only executing the completion does,
    # which is what the zsh pty test in bin/tests/test_completions.sh exists for.
    local _agent_container_agents="claude codex pi opencode"
    local -a cmds
    cmds=(
        'build:Build the image at the repo root'
        'host:Manage deployment hosts (add, ls)'
        'up:Start a container (detached)'
        'redeploy:Rebuild the image on the host and recreate (volumes preserved)'
        'stop:Stop a container, keeping it and its volumes'
        'start:Start a previously stopped container'
        'keys:Inject SSH host key / authorized keys into a running container'
        'down:Stop and remove a container'
        'purge:Stop, remove, and delete all per-container volumes'
        'wipe:Remove the container, its volumes, and the locally-built image'
        'list:List containers (plus stale state files)'
        'attach:Attach via ssh + tmux (local state or hosts.conf)'
        'logs:Tail container logs'
        'plan:Show the plan for the declarative spec (no mutation)'
        'apply:Converge the declarative spec'
        'status:Report declarative spec drift'
        'destroy:Remove resources owned by the declarative spec'
        'menu:Interactive wizard'
        'context:Print agent-friendly context about this environment'
        'skill:Create, update, or remove the agent skill definition'
        'commands:Print the machine-readable command tree'
        'completions:Print a checked-in completion script'
    )

    _arguments -C \
        '(- *)--self-test[Run doctests + interop corpus checks]' \
        '(- *)--help[Show help]' \
        '1:command:->command' \
        '*::arg:->args' && return 0

    case $state in
        command)
            _describe -t commands 'agent-container command' cmds
            ;;
        args)
            case $line[1] in
                build)
                    _arguments \
                        '--context[Docker build context (repo checkout)]:directory:_files -/' \
                        '1:tag:'
                    ;;
                up|redeploy)
                    _arguments \
                        "--agent[Primary agent to run]:agent:(${_agent_container_agents})" \
                        '--mode[Execution mode]:mode:(interactive headless)' \
                        '--workspace[Workspace backing]:workspace:(persistent bind ephemeral)' \
                        '--host[Deploy to this registered host]:host:' \
                        '*--mount[Bind-mount a host dir read-write]:directory:_files -/' \
                        '--env-file[Bypass env-file resolution; path must exist]:file:_files' \
                        '--host-key[Inject an ed25519 private host key]:file:_files' \
                        '*--authorized-key[Inject an SSH public key (repeatable)]:file:_files' \
                        '*:container:__agent_container_names'
                    ;;
                host)
                    _arguments \
                        '1:subcommand:(add ls)' \
                        '--driver[Runtime driver: docker or podman]:driver:(docker podman)' \
                        '--docker-context[Existing docker context]:context:' \
                        '--connection[Podman system connection]:connection:' \
                        '--address[Attach address override]:address:' \
                        '--default[Make this the default deploy target]' \
                        '--json[Emit machine-readable JSON]'
                    ;;
                keys)
                    _arguments \
                        '--host-key[Inject an ed25519 private host key]:file:_files' \
                        '*--authorized-key[Inject an SSH public key (repeatable)]:file:_files' \
                        '*:container:__agent_container_names_local'
                    ;;
                down)
                    _arguments \
                        '--host[Host the container runs on]:host:' \
                        '--purge[Also delete all per-container volumes]' \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__agent_container_names_local'
                    ;;
                purge)
                    _arguments \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__agent_container_names_local'
                    ;;
                list)
                    _arguments '--json[Emit machine-readable JSON]'
                    ;;
                attach)
                    _arguments \
                        '--local[Force local target (state file)]' \
                        '--remote[Force remote target (hosts.conf)]' \
                        '--user[SSH user (default: AGENT_CONTAINER_USER or dev)]:user:' \
                        '--host[Override the resolved host]:host:_hosts' \
                        '(--window -w)'{--window,-w}'[Select tmux window NAME before attaching]:window:' \
                        '*:container:__agent_container_names'
                    ;;
                logs)
                    _arguments \
                        '--no-follow[Print logs without following]' \
                        '*:container:__agent_container_names_local'
                    ;;
                completions)
                    _arguments '1:shell:(bash zsh)'
                    ;;
            esac
            ;;
    esac
}

# Dual-mode: works whether autoloaded from $fpath as `_agent-container` or sourced.
if [[ "$funcstack[1]" == "_agent-container" ]]; then
    _agent-container "$@"
else
    (( $+functions[compdef] )) && compdef _agent-container agent-container
fi
