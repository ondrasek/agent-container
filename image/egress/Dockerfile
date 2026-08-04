# The egress proxy (Feature 012). Syntax-compatible with both `docker build` and
# `podman build` — no BuildKit-specific features, matching the agent image.
#
# Built HERE rather than pulled. This container IS the egress control, so sourcing
# it from a third-party registry account would put the security component outside
# the trust boundary; Alpine's package repo is the same class of dependency as the
# agent image's Debian base. Costs no publishing — the tool already builds on the
# target host. See specs/012-egress-provider-control/research.md R10, which records
# that the smallest prebuilt candidate SEGFAULTS on its first refusal.
#
# What this proxy does NOT do, deliberately: it never terminates TLS. It allowlists
# on the CONNECT target, which is visible BEFORE the TLS session exists. A
# decrypting proxy would see every Authorization header, creating a new plaintext
# credential location inside the component meant to reduce exposure (Constitution
# III). That is why no CA certificate is generated, installed, or injected here.

FROM alpine:3.21

# Pinned: the filter semantics below (FilterType, FilterDefaultDeny) are version
# -specific, and an unpinned rebuild could change them under us.
RUN apk add --no-cache 'tinyproxy~=1.11'

# The static half of the configuration is BAKED. Only the allowlist varies per
# environment, and it arrives as a compose `config` at /etc/tinyproxy/filter —
# never a host bind, which fails over a remote or Lima daemon (research R10b).
#
# FilterDefaultDeny Yes inverts the filter's meaning: the file becomes an
# ALLOWLIST, so an EMPTY file denies everything. That is the air-gapped state
# (`providers: []`), and it is asserted by a test rather than assumed — an
# empty-means-allow-all inversion would be catastrophic and silent.
#
# FilterType is used rather than the deprecated FilterExtended (which warns on
# every load in 1.11.x). FilterCaseSensitive is omitted: it is a documented no-op.
#
# `ere` is load-bearing, not a preference. Accepted values are bre|ere|fnmatch, and
# the generated wildcard pattern `^([A-Za-z0-9_-]+\.)*example\.com$` relies on ERE
# grouping and `+`. Under `bre` those are LITERAL characters, so the pattern would
# match nothing and the host would be silently denied — fail-closed, but broken in
# a way that looks like a policy decision rather than a bug.
RUN printf '%s\n' \
    'Port 8888' \
    'Listen 0.0.0.0' \
    'Timeout 600' \
    'LogLevel Info' \
    'MaxClients 100' \
    'Allow 0.0.0.0/0' \
    'ConnectPort 443' \
    'Filter "/etc/tinyproxy/filter"' \
    'FilterDefaultDeny Yes' \
    'FilterType ere' \
    > /etc/tinyproxy/tinyproxy.conf \
 && touch /etc/tinyproxy/filter \
 && chown -R nobody:nobody /etc/tinyproxy

# Rootless, like the agent container (Constitution II). 65534 = nobody.
USER 65534:65534

EXPOSE 8888

# -d keeps it in the foreground so compose owns the lifecycle.
ENTRYPOINT ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
