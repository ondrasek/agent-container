#!/bin/sh
# Egress boundary entrypoint (Feature 012 Phase B).
#
# ORDER IS THE SECURITY PROPERTY. Rules are installed BEFORE either daemon
# accepts traffic, and before the agent container can be started against this
# namespace. A window in which the proxy is up and the rules are not is a window
# in which the agent is entirely unconstrained — and it would be invisible,
# because everything would appear to work.
#
# Anything that fails here must kill the container rather than degrade: an egress
# boundary that starts without its rules is worse than one that does not start,
# because the declaration still reads as enforced.
set -eu

log() { printf '[egress] %s\n' "$*" >&2; }
die() { log "FATAL: $*"; exit 1; }

# EVERY RULE IS CHECKED, AND THE CHECK CANNOT BE SUPPRESSED.
#
# `install_rules || die …` did NOT do this. Putting a function on the left of an
# AND-OR list suppresses `set -e` for its ENTIRE body (POSIX), and the function's
# status is that of its LAST command — `iptables -P OUTPUT DROP`, which succeeds
# regardless of every rule before it. So a rule that failed to install was
# invisible and the entrypoint went on to log the boundary as installed.
#
# Shadowing the command instead of adding a helper is deliberate: the generated
# `ports.rules` fragment is SOURCED into this shell and calls `iptables` directly,
# so it inherits the check without the generator and the entrypoint having to
# agree about a helper's name — an agreement that could silently lapse.
iptables() {
    command iptables "$@" || die "netfilter rule REJECTED: iptables $*"
}

SQUID_HTTP_PORT=3128
SQUID_TLS_PORT=3129

# Resolved at RUNTIME, never hard-coded: the uid depends on the base image's
# package layout and would silently drift on a rebuild. If it drifted while
# hard-coded, the exemption below would stop matching and the proxy's own
# upstream connections would be redirected back into itself — an infinite loop
# presenting as "the network is broken".
SQUID_UID="$(id -u squid 2>/dev/null)" || die "no 'squid' user in this image"
UNBOUND_UID="$(id -u unbound 2>/dev/null)" || die "no 'unbound' user in this image"

log "squid uid=${SQUID_UID} unbound uid=${UNBOUND_UID}"

# --- netfilter ---------------------------------------------------------------
# The shape is: redirect what the proxy can inspect, permit what the proxy and
# resolver themselves need, drop everything else.
#
# The daemons are exempted BY UID rather than by destination. Exempting by
# destination would mean writing the allowlist twice, in two syntaxes, and the
# two copies could drift — with the failure mode being over-permission, which is
# silent. `-m owner --uid-owner` cannot drift from the allowlist because it does
# not encode the allowlist at all (research R15).

install_rules() {
    # Redirect the agent's HTTP/HTTPS at squid. `! --uid-owner squid` keeps
    # squid's own upstream connections out of the redirect, or they loop back in.
    iptables -t nat -A OUTPUT -p tcp --dport 443 \
        -m owner ! --uid-owner "$SQUID_UID" -j REDIRECT --to-port "$SQUID_TLS_PORT"
    iptables -t nat -A OUTPUT -p tcp --dport 80 \
        -m owner ! --uid-owner "$SQUID_UID" -j REDIRECT --to-port "$SQUID_HTTP_PORT"

    # FR-020a needs NO DNS RULE AT ALL, and that is the finding rather than an
    # omission (research R18, measured). The default-deny policy below already
    # makes every resolver except ours UNREACHABLE — an agent querying 8.8.8.8
    # cannot open the connection, so there is nothing to redirect. A REDIRECT
    # would merely *answer* such an agent; the DROP means it cannot ask.
    #
    # Four NAT approaches were tried and all failed here (REDIRECT needs
    # route_localnet with /proc/sys read-only; DNAT gets no reply and breaks
    # direct queries). Do not re-add one: it would be a moving part that buys
    # nothing, and its absence is deliberate.

    # DOCKER'S EMBEDDED RESOLVER IS A HOLE IN THE LOOPBACK ACCEPT (research R19).
    # On every user-defined network — which is what compose creates — the daemon
    # answers at 127.0.0.11 and forwards the query OUTSIDE this namespace, where
    # none of these rules apply. It is reached over LOOPBACK, so a blanket
    # `-o lo -j ACCEPT` leaves the DNS allowlist inert in exactly the deployment
    # shape that matters.
    #
    # It cannot be closed by rewriting /etc/resolv.conf: that file is a
    # daemon-owned bind mount and the agent runs as `dev`, so nothing in the
    # agent container may write it — and even if it could, a rewrite is only
    # ADVISORY. A hostile agent ignores resolv.conf and asks 127.0.0.11 itself.
    # So the packet is rewritten instead, and the agent's own configuration is
    # never trusted.
    #
    # INSERTED AT THE HEAD, not appended: the daemon has already installed its
    # own DNAT here (127.0.0.11:53 -> 127.0.0.11:<ephemeral>) and iptables takes
    # the first match. Measured — appended, these rules are dead and undeclared
    # names resolve. The tell is the rcode: unbound REFUSES, the daemon's
    # resolver returns NXDOMAIN, so an NXDOMAIN for an undeclared name means
    # these rules are in the wrong position rather than that the policy is off.
    #
    # BY PORT, NOT BY DESTINATION ADDRESS. This matched `-d 127.0.0.11` — DOCKER's
    # embedded resolver and nothing else's. Podman puts aardvark-dns on the network
    # GATEWAY, so under podman the rule never matched, every lookup fell through to
    # the default-deny policy below, and NOTHING resolved, declared or not. It
    # failed CLOSED, so it was never a hole; it made egress-enabled environments
    # unusable on the runtime ADR 0001 makes the default.
    #
    # REDIRECT, not DNAT: REDIRECT reroutes to loopback, which is what makes the
    # rewritten packet deliverable. Paired with route_localnet=1, set by the
    # runtime at creation because /proc/sys is read-only here under rootless podman.
    #
    # `! --uid-owner "$UNBOUND_UID"` is load-bearing, not tidiness: unbound forwards
    # DECLARED names upstream over port 53 itself, so without the exemption its own
    # queries would be rewritten back to it and loop. Same idiom as the squid
    # redirects above, for the same reason.
    iptables -t nat -I OUTPUT 1 -p udp --dport 53 \
        -m owner ! --uid-owner "$UNBOUND_UID" -j REDIRECT --to-port 53
    iptables -t nat -I OUTPUT 2 -p tcp --dport 53 \
        -m owner ! --uid-owner "$UNBOUND_UID" -j REDIRECT --to-port 53

    # AND THE QUERY MUST ARRIVE LOOKING LOCAL. REDIRECT rewrites the DESTINATION
    # and leaves the source alone, so a query from the agent reaches unbound with
    # the namespace's bridge address as its source — and unbound is
    # `interface: 127.0.0.1` with `access-control: 127.0.0.0/8 allow`, so it
    # REFUSES it. Measured: rcode 5 for a DECLARED name, which reads exactly like
    # a policy refusal and is not one. Without this SNAT the allowlist appears to
    # deny everything, and the tell is that it denies declared names too.
    iptables -t nat -A POSTROUTING -d 127.0.0.1 -p udp --dport 53 -j SNAT --to-source 127.0.0.1
    iptables -t nat -A POSTROUTING -d 127.0.0.1 -p tcp --dport 53 -j SNAT --to-source 127.0.0.1

    # AND THE EPHEMERAL PORT BEHIND IT. The DNAT above matches dport 53 only,
    # while the daemon's resolver also listens on a high port that its own rule
    # forwards to — asking that port directly walks straight past the rewrite
    # (measured: it answered). This DROP catches it, and cannot catch the
    # rewritten traffic, because by the time the filter table runs the
    # destination is already 127.0.0.1.
    #
    # Harmless under podman, which puts aardvark-dns on the gateway address
    # rather than on loopback — there the default-deny policy already covers it.
    iptables -A OUTPUT -d 127.0.0.11 -j DROP
    iptables -A OUTPUT -o lo -j ACCEPT
    # BY DESTINATION AS WELL AS BY INTERFACE. A REDIRECTed packet does not match
    # `-o lo` here — measured: the policy DROP counter climbed while the `-o lo`
    # rule stayed put, so the rewritten query died one hop short of the resolver
    # that would have answered it. Not a widening: `-o lo` already permits exactly
    # this traffic, and the only things on 127.0.0.1 are unbound and squid, which
    # ARE the boundary.
    iptables -A OUTPUT -d 127.0.0.1 -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -m owner --uid-owner "$SQUID_UID" -j ACCEPT
    iptables -A OUTPUT -m owner --uid-owner "$UNBOUND_UID" -j ACCEPT
    # SCOPED TO LOOPBACK DELIBERATELY. Unscoped this matches on destination PORT
    # alone, so it ACCEPTs a connection to ANY address in the world on 3128/3129 —
    # and the nat REDIRECT only matches dport 443/80, so such a connection is never
    # handed to squid. It reached this rule and was accepted before `-P OUTPUT DROP`
    # could apply: an unlogged, unrestricted TCP channel out of the boundary
    # (`nc <any-ip> 3128`), needing no DNS, while the tool still reported
    # `enforced: true`. `build_netfilter_rules` never emits an unscoped port ACCEPT
    # for exactly this reason — SC-010 is "that host and that port only".
    iptables -A OUTPUT -d 127.0.0.1 -p tcp --dport "${SQUID_HTTP_PORT}:${SQUID_TLS_PORT}" -j ACCEPT

}

install_rules
log "netfilter installed (policy still ACCEPT — declared ports pending)"

# --- resolver ----------------------------------------------------------------
# Started before squid because squid resolves upstream names through it, AND
# before the declared-port rules below because THOSE NEED IT TOO.
unbound -c /etc/unbound/unbound.conf &
UNBOUND_PID=$!
sleep 1
kill -0 "$UNBOUND_PID" 2>/dev/null || die "unbound exited immediately — check /etc/unbound/allowed.conf"
log "unbound up (pid ${UNBOUND_PID})"

# DECLARED PORT RULES GO IN *AFTER* THE RESOLVER, and the ordering is the fix.
#
# `iptables -d github.com` resolves the operand AT INSERT TIME. Sourced from
# inside install_rules this could never work: the DNS rewrite above has already
# pointed 127.0.0.11:53 at 127.0.0.1:53 — root is not exempt, so this shell's own
# lookups are rewritten too — and unbound did not exist yet. getaddrinfo failed,
# the ACCEPT was skipped, and with the old swallowed-failure handling the boundary
# still logged as installed. FR-018 was therefore non-functional on Docker, and
# `git push` over a declared SSH remote was packet-dropped AT PUSH TIME, after the
# work existed: Hard Constraint #1 breaking in the exact ordering it forbids.
#
# Safe to run with the policy still ACCEPT: nothing untrusted is in this namespace
# yet. The agent container cannot start until the healthcheck passes, and that
# needs squid, which starts below — after the policy flips.
if [ -s /etc/egress/ports.rules ]; then
    log "applying declared port rules"
    # Counted BEFORE, so what the fragment actually installed can be printed
    # afterwards without guessing which rules were its own.
    rules_before=$(command iptables -S OUTPUT | wc -l)
    # shellcheck disable=SC1091  # generated, injected via compose configs
    . /etc/egress/ports.rules

    # THE PIN IS PART OF THE RECORD, because it is NOT what the declaration says
    # (T147, measured in research R24). `iptables -d <name>` resolves the operand
    # here, once, and stores one rule PER ADDRESS in that one answer — the kernel
    # never sees the name. A declared endpoint whose addresses rotate therefore
    # stops being reachable while the declaration still reads as permitting it,
    # and because the readiness gate passes, it presents as a healthy deployment
    # whose connections fail later. Measured, not theorised: `github.com` was
    # pinned to 140.82.121.4 and the SAME resolver handed the agent 140.82.121.3
    # ~2 minutes later, so `ssh -T git@github.com` timed out — Hard Constraint #1
    # (commit AND push) failing at push time, after the work exists.
    #
    # This cannot be fixed by logging, so what is fixed is the SILENCE: the
    # addresses go to the operator's channel with the consequence spelled out, so
    # a later timeout is diagnosable from `agent-container logs <name> --egress`
    # instead of looking like a broken network.
    command iptables -S OUTPUT | tail -n "+$((rules_before + 1))" |
        while read -r rule; do log "pinned NOW, by address: ${rule}"; done
    log "declared {host, port} entries are pinned to the addresses above, resolved"
    log "  once, just now. If a destination's addresses rotate — every CDN-fronted"
    log "  host does, github.com included — it becomes UNREACHABLE while the"
    log "  declaration still permits it, and the failure surfaces at connect time"
    log "  (git push, a database connection) rather than at deploy. A destination"
    log "  declared WITHOUT a port is matched by NAME at the proxy and does not pin."
fi

# FR-017. Everything not permitted above is denied — including protocols and
# ports nobody thought of, which is the point. A default-ACCEPT policy with
# 80/443 redirected would let an agent reach anything it liked on port 8080,
# and the declaration would still read as constraining.
iptables -P OUTPUT DROP
log "netfilter complete; OUTPUT policy=DROP"

# This container's own resolution rides the SAME rewrite: squid's /etc/resolv.conf
# still says 127.0.0.11 and lands on unbound, so squid can resolve declared names
# and only declared names. No second mechanism, and nothing to keep in sync.

# --- the record --------------------------------------------------------------
# A REFUSED CONNECTION IS ONLY A RECORD IF THE OPERATOR CAN READ IT (FR-020d,
# T150). squid's access log is written to `stdio:/dev/stdout` so it lands in the
# container's log and `agent-container logs <name> --egress` shows it — the same
# channel T130 had to fix for unbound, whose refusals were being handed to a
# syslog this image does not run.
#
# BUT squid CANNOT OPEN THAT PATH BY ITSELF. /dev/stdout is /proc/self/fd/1, the
# runtime's log pipe, created root-owned and mode 0600; squid REOPENS its logs by
# path after dropping to the `squid` user, and that open fails with EACCES.
# Measured: `FATAL: Cannot open '/dev/stdout' for writing`, written to cache.log —
# inside the container, where nothing reads it — leaving a container that exited 1
# with a COMPLETELY EMPTY log. The fix for an unreadable record failing invisibly
# is the exact defect it was fixing.
#
# chown rather than `chmod 0666`, and the difference is real: writing to an
# ALREADY-OPEN descriptor needs no permission, only reopening the path does. So
# unbound keeps its inherited stderr and needs nothing, and squid is the only user
# that gains anything. Measured both ways (unbound still cannot reopen it).
chown squid /dev/stdout /dev/stderr || die "cannot hand squid the container's log stream"

# AND IT IS CHECKED, because the failure mode is silence. Without this the
# boundary comes up, squid dies on its first log open, compose reports only
# `unhealthy`, and the reason is in a file inside a container that is already
# gone. Runs as `squid` because root's answer would be yes regardless — the guard
# has to ask the user that will actually do the open.
su -s /bin/sh squid -c '[ -w /dev/stdout ] && [ -w /dev/stderr ]' ||
    die "squid cannot write the container's log stream — a refused connection would go unrecorded (FR-020d)"

# --- proxy -------------------------------------------------------------------
# exec: squid becomes PID 1 so compose owns the lifecycle and a crash takes the
# container down rather than leaving a boundary that is no longer enforcing.
log "starting squid"
exec squid -N -f /etc/squid/squid.conf
