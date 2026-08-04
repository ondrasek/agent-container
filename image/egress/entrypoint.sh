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

    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -m owner --uid-owner "$SQUID_UID" -j ACCEPT
    iptables -A OUTPUT -m owner --uid-owner "$UNBOUND_UID" -j ACCEPT
    iptables -A OUTPUT -p tcp --dport "${SQUID_HTTP_PORT}:${SQUID_TLS_PORT}" -j ACCEPT

    # Declared non-HTTP destinations (FR-018): `{host, port}` entries become
    # explicit ACCEPTs. Injected as a shell fragment because the set is
    # per-environment; absent when nothing non-HTTP is declared.
    if [ -s /etc/egress/ports.rules ]; then
        log "applying declared port rules"
        # shellcheck disable=SC1091  # generated, injected via compose configs
        . /etc/egress/ports.rules
    fi

    # FR-017. Everything not permitted above is denied — including protocols and
    # ports nobody thought of, which is the point. A default-ACCEPT policy with
    # 80/443 redirected would let an agent reach anything it liked on port 8080,
    # and the declaration would still read as constraining.
    iptables -P OUTPUT DROP
}

install_rules || die "could not install netfilter rules (is NET_ADMIN granted?)"
log "netfilter installed; OUTPUT policy=DROP"

# --- resolver ----------------------------------------------------------------
# Started before squid because squid resolves upstream names through it.
unbound -c /etc/unbound/unbound.conf &
UNBOUND_PID=$!
sleep 1
kill -0 "$UNBOUND_PID" 2>/dev/null || die "unbound exited immediately — check /etc/unbound/allowed.conf"
log "unbound up (pid ${UNBOUND_PID})"

# --- proxy -------------------------------------------------------------------
# exec: squid becomes PID 1 so compose owns the lifecycle and a crash takes the
# container down rather than leaving a boundary that is no longer enforcing.
log "starting squid"
exec squid -N -f /etc/squid/squid.conf
