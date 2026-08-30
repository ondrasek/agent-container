# Claude Code needs no delivered configuration

This directory is intentionally empty of config files.

Claude's credential is wired by the **entrypoint**, not by delivered config. For
an API key it writes an `apiKeyHelper` into `~/.claude/settings.json` that `cat`s
the injected key **at request time**, so the key never touches the `-claude`
volume. For an OAuth token it exports `CLAUDE_CODE_OAUTH_TOKEN` into the agent's
environment.

**Exactly one of the two is wired**, chosen by `claude_auth` in `settings.yaml`
(the sample `run.sh` sets this for you based on which variable you exported).
Claude itself refuses to be told twice — *"Both apiKeyHelper and
ANTHROPIC_API_KEY set · auth may not work as expected"* — so the unchosen
credential is delivered to its volume and deliberately never exported.

You may still drop files here if you want them delivered; the manifest for
`claude` recognises `settings.json`, `CLAUDE.md`, `mcp.json` and `*.mcp.json`.
Anything else is treated as the agent's own runtime state and is not delivered.
