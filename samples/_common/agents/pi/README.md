# `pi` needs delivered configuration; `claude` does not

These two files ride the **canonical-config convention** — `<name>.config/pi/…`
in the config directory, mirrored onto `~/.pi/agent/…` in the container.

- **`models.json`** declares the provider. `pi` has no built-in Ollama provider,
  so without this file there is no Ollama to select. `apiKey` is the literal
  string `$OLLAMA_API_KEY` — pi's own interpolation syntax — so the key stays in
  the delivered-credential path and **never lands in a config file**.
- **`settings.json`** sets `defaultProvider` **and** `defaultModel`. A headless
  run is `pi -p <task>` with no `--model`, and the model id alone is ambiguous
  because a built-in provider ships the same one.

Two failure modes worth knowing, both silent:

- **`cost` must carry all four fields.** pi schema-validates the provider and
  drops the whole thing when one is missing — without a word. The model name then
  matches a built-in provider instead, and the failure surfaces as "no API key",
  which sends you to look at the credential that was working all along.
- **The directory is `~/.pi/agent`, not `~/.pi`.** A file placed one level up is
  ignored. The agent starts, reports nothing wrong, and uses none of your config.

**Claude Code needs no delivered config at all** — see `../claude/README.md`.
