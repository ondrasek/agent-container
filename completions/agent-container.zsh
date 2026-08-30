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

# Feature 016: targets for `runs list|show`, read from the DURABLE store
# ${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/runs/<host>/<env>/<id>.json.
# A separate source from the state files on purpose — a record outlives its
# environment, so completing from state would hide exactly the environments this
# feature exists to answer for.
#
# Which of the two to offer is decided from $words and NOT from $line: this runs
# inside a NESTED _arguments, where $line describes that nested context rather
# than the command line the operator actually typed.
__agent_container_runs_targets() {
    local runs_dir="${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/runs" f
    local -aU names
    if (( ${words[(I)show]} )); then
        for f in "$runs_dir"/*/*/*.json(N); do names+=("${f:t:r}"); done
    else
        for f in "$runs_dir"/*/*(N/); do names+=("${f:t}"); done
    fi
    compadd -a names
}

# Feature 012 FR-010: targets for `egress`, from the SIBLING store
# ${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/egress/<host>/<env>/.
# The state files are offered as well, and that is the point of this command: an
# environment whose boundary has refused nothing has no directory here, and it is
# exactly the one an operator names to be told that silence means nothing was
# refused.
__agent_container_egress_targets() {
    local egress_dir="${XDG_DATA_HOME:-$HOME/.local/share}/agent-container/egress" f
    local -aU names
    for f in "$egress_dir"/*/*(N/); do names+=("${f:t}"); done
    __agent_container_gather_local
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
        'keys:The keys an environment admits — grant, show, list'
        'creds:The credentials an environment holds — list, revoke'
        'down:Stop and remove a container'
        'purge:Stop, remove, and delete all per-container volumes'
        'wipe:Remove the container, its volumes, and the locally-built image'
        'ls:List containers (plus stale state files)'
        'list:List containers (hidden alias for ls, kept so scripts keep working)'
        'attach:Attach via ssh + tmux (local state or hosts.conf)'
        'logs:Tail container logs'
        'runs:Durable run records (list, show) — survives teardown'
        'egress:Durable record of undeclared egress — survives teardown'
        'inventory:Durable record of every environment created — survives its host'
        'doctor:Would a deploy work? Read-only preflight report'
        'revoke:Withdraw a control plane key from every host that trusts it'
        'telemetry:The observability trail (collect, retry) — two legs, one payload'
                'ssh-key:The agent'"'"'s own SSH key pair (show, rotate) — private half never leaves'
        'panic:KILL SWITCH — stop everything, everywhere, and report what it could not reach'
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
        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
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
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--context[Docker build context (repo checkout)]:directory:_files -/' \
                        '1:tag:'
                    ;;
                up|redeploy)
                    # --no-repo is redeploy-only: it drops the INHERITED clone URL,
                    # and `up` has nothing to inherit from.
                    local -a _ac_repo_opts
                    _ac_repo_opts=('--repo[Clone-on-start URL]:url:')
                    [[ "${words[2]}" == "redeploy" ]] && _ac_repo_opts+=(
                        '--no-repo[Drop the inherited clone-on-start URL]'
                    )
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        "--agent[Primary agent to run]:agent:(${_agent_container_agents})" \
                        '--mode[Execution mode]:mode:(interactive headless)' \
                        '--workspace[Workspace backing]:workspace:(persistent bind ephemeral)' \
                        '--host[Deploy to this registered host]:host:' \
                        '*--mount[Bind-mount a host dir read-write]:directory:_files -/' \
                        '--env-file[Bypass env-file resolution; path must exist]:file:_files' \
                        '*--authorized-key[Inject an SSH public key (repeatable)]:file:_files' \
                        "${_ac_repo_opts[@]}" \
                        '*:container:__agent_container_names'
                    ;;
                host)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:subcommand:(add ls)' \
                        '--driver[Runtime driver: docker or podman]:driver:(docker podman)' \
                        '--docker-context[Existing docker context]:context:' \
                        '--connection[Podman system connection]:connection:' \
                        '--address[Attach address override]:address:' \
                        '--default[Make this the default deploy target]' \
                        '--json[Emit machine-readable JSON]'
                    ;;
                creds)
                    # A GROUP (ls/rm), mirroring `keys` and `ssh-key`.
                    _arguments '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:command:(ls remove rm)' \
                        '--host[Host the environment runs on]:host:' \
                        '--all[Revoke every credential]' \
                        '(-y --yes)'{-y,--yes}'[Skip the confirmation]' \
                        '--json[Emit machine-readable JSON]' \
                        '*:container:__agent_container_names_local'
                    return 0
                    ;;
                keys)
                    # A GROUP since Feature 020 (add/show/ls), mirroring ssh-key.
                    _arguments '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:command:(add show ls remove rm)' \
                        '*--authorized-key[Grant a public key, until the next recreate]:file:_files' \
                        '--host[Host the environment runs on]:host:' \
                        '--json[Emit machine-readable JSON]' \
                        '*:container:__agent_container_names_local'
                    return 0
                    ;;
                down)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--host[Host the container runs on]:host:' \
                        '--purge[Also delete all per-container volumes]' \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__agent_container_names_local'
                    ;;
                purge)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '*:container:__agent_container_names_local'
                    ;;
                list)
                    _arguments '--json[Emit machine-readable JSON]'
                    ;;
                attach)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--local[Force local target (state file)]' \
                        '--remote[Force remote target (hosts.conf)]' \
                        '--user[SSH user (default: AGENT_CONTAINER_USER or dev)]:user:' \
                        '--host[Override the resolved host]:host:_hosts' \
                        '(--window -w)'{--window,-w}'[Select tmux window NAME before attaching]:window:' \
                        '*:container:__agent_container_names'
                    ;;
                logs)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--no-follow[Print logs without following]' \
                        '--egress[Read the egress boundary log, where refusals are recorded]' \
                        '--json[Machine-readable envelope]' \
                        '*:container:__agent_container_names_local'
                    ;;
                doctor)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--host[Override the host to check]:host:' \
                        '--json[Machine-readable report]' \
                        '*:container:__agent_container_names'
                    ;;
                revoke)
                    _arguments '(-y --yes)'{-y,--yes}'[Skip confirmation]' \
                        '--json[Machine-readable envelope]' \
                        '*:container:__agent_container_names'
                    ;;
                telemetry)
                    _arguments '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:command:(collect retry reconcile)' \
                        '*--host[Host to act on]:host:' \
                        '*--name[Environment to act on]:container:__agent_container_names' \
                        '--since[Window lower bound]:since:' \
                        '--until[Window upper bound]:until:' \
                        '--collector-ids[File of run ids the collector holds]:file:_files' \
                        '--json[Machine-readable envelope]'
                    ;;
                ssh-key)
                    _arguments '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:command:(show rotate)' \
                        '--json[Emit machine-readable JSON]' \
                        '(-y --yes)'{-y,--yes}'[Skip the rotate confirmation]'
                    return 0
                    ;;
                panic)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '*--host[Limit to these hosts]:host:' \
                        '*--name[Limit to these environments]:name:' \
                        '--destroy[Remove containers AND volumes]' \
                        '--preview[Show what would be affected; change nothing]' \
                        '--host-timeout[Per-host budget in seconds]:seconds:' \
                        '(-y --yes)'{-y,--yes}'[Skip the --destroy confirmation]' \
                        '--json[Emit machine-readable JSON]'
                    return 0
                    ;;
                inventory)
                    _arguments '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:command:(ls list)' '--json[Emit machine-readable JSON]'
                    return 0
                    ;;
                runs)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '1:subcommand:(ls show list)' \
                        '--host[Host whose records to read]:host:' \
                        '--changed[Only runs whose recorded paths cover PATH (list)]:path:' \
                        '--json[Emit machine-readable JSON]' \
                        '*:record:__agent_container_runs_targets'
                    ;;
                egress)
                    _arguments \
                        '(-v --verbose)'{-v,--verbose}'[Verbose diagnostics on stderr]' \
                        '--host[Host whose records to read]:host:' \
                        '--json[Emit machine-readable JSON]' \
                        '*:environment:__agent_container_egress_targets'
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
