# The egress boundary (Feature 012 Phase B). Syntax-compatible with both
# `docker build` and `podman build` — no BuildKit-specific features.
#
# PHASE B REPLACES PHASE A'S MECHANISM. Phase A pointed the agent at a tinyproxy
# sidecar through HTTPS_PROXY: enforcement that depended on the agent's
# cooperation, and an agent prompted into `unset HTTPS_PROXY` defeated it. This
# image programs the network stack instead, so routing is not the agent's choice.
#
# Built HERE rather than pulled. This container IS the egress control, so sourcing
# it from a third-party registry account would put the security component outside
# the trust boundary. Costs no publishing — the tool already builds on the target
# host.
#
# THE PRIVILEGE LIVES HERE, NOT IN THE AGENT. This container gets NET_ADMIN and
# runs no untrusted code; the agent container joins its network namespace with an
# EMPTY capability set. Constitution II is per-container — the rule is that the
# container running untrusted agent code holds no more privilege than its work
# requires, and under this arrangement it holds none at all. Verified: research
# R15 records CapAdd [] on the agent and [CAP_NET_ADMIN] here.
#
# IT NEVER TERMINATES TLS. squid `peek`s the ClientHello to read the SNI and then
# `splice`s the connection through — it does not `bump`. A bumping proxy would see
# every Authorization header, creating a new plaintext credential location inside
# the component meant to reduce exposure (Constitution III). Verified by R15: the
# certificate the agent sees for a declared host is the REAL server certificate,
# not one this container generated. If that ever shows a locally-issued CN, the
# configuration has silently become `bump` and the boundary has inverted.

FROM alpine:3.21

# squid   — SNI peek-and-splice. Alpine's build carries --with-openssl (R12).
#           tinyproxy cannot serve this at all: a transparently redirected TLS
#           stream is not a CONNECT request and carries no hostname to read.
# unbound — allowlist-only resolution that can answer REFUSED. dnsmasq returns
#           NXDOMAIN for a policy refusal, which both lies ("no such name") and
#           CACHES — so a policy error would present as a DNS bug and outlive the
#           declaration that caused it (R16, FR-020e).
# iptables — the REDIRECT and default-deny rules.
#
# Fuzzy-pinned with apk's `~` syntax. The pins are real, not decorative: an
# unsatisfiable version exits 1 rather than silently installing something else.
RUN apk add --no-cache \
      'squid~6.12' \
      'unbound~1.22' \
      iptables \
      openssl

# The certificate squid presents on the intercept port. It is NEVER shown to a
# client for a spliced (i.e. permitted) connection — those see the real server's
# certificate — so this exists only to satisfy `https_port … ssl-bump`, and
# self-signed is correct. It is emphatically NOT a CA: nothing in the agent
# container is asked to trust it, and no CA certificate is injected anywhere.
RUN openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout /tmp/k.pem -out /tmp/c.pem -subj "/CN=agent-container-egress" 2>/dev/null \
 && cat /tmp/c.pem /tmp/k.pem > /etc/squid/intercept.pem \
 && rm -f /tmp/k.pem /tmp/c.pem \
 && chown squid:squid /etc/squid/intercept.pem \
 && chmod 0400 /etc/squid/intercept.pem \
 && mkdir -p /var/log/squid /run/unbound \
 && chown unbound:unbound /run/unbound \
 && chown -R squid:squid /var/log/squid

# The per-environment allowlist arrives as compose `configs` with `content:` —
# never `file:`, which is materialised as a BIND of a local path and therefore
# cannot reach a remote daemon (R10b, measured). Touched so both daemons start
# even before the tool injects anything.
RUN touch /etc/squid/allowed_sni.acl /etc/unbound/allowed.conf \
 && chown squid:squid /etc/squid/allowed_sni.acl

# 53 is deliberately absent: the resolver binds loopback only, so advertising it
# would document reachability the configuration refuses.
EXPOSE 3128 3129

# NOT rootless, and that is this container's whole purpose. The entrypoint needs
# CAP_NET_ADMIN to program netfilter; squid then drops to `squid` and unbound to
# `unbound` on their own. The agent container — the one running untrusted code —
# stays rootless with an empty capability set.
COPY squid.conf /etc/squid/squid.conf
COPY unbound.conf /etc/unbound/unbound.conf
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
