# Contract: Agent Interface

What an AI agent may rely on. Symbols live in `bin/agent-container`; the surface is a
command-line invocation (no API, no daemon).

## 1. Output envelope

Every command invoked with `--json` emits **one** JSON object on **stdout**:

```json
{ "schema": "agent-container/v1", "ok": true,  "data":  { … } }
{ "schema": "agent-container/v1", "ok": false, "error": { "code": "…", "entity": "…", "message": "…", "remedy": "…" } }
```

**Guarantees**

- `schema` is present on **every** payload and is the version an agent checks (FR-006).
- Exactly one of `data` / `error`; `ok` agrees with the exit status (non-zero ⇔ `ok: false`).
- **stdout carries only the envelope** — no colour, progress, spinners or tables (FR-002).
  Human/diagnostic text goes to **stderr** and is unchanged for interactive use (FR-019).
- **No secret value appears in any payload** (FR-011, Constitution III).

**Compatibility rules**

| Change | Allowed without a version bump? |
|--------|-------------------------------|
| Adding a field | ✅ yes |
| Adding a new `code` value | ✅ yes |
| Renaming/removing a field | ❌ no — bump `schema` |
| Changing a `code`'s meaning | ❌ no — bump `schema` |

## 2. Failure contract

```
code      stable identifier for the failure class — THE parsing surface
entity    what it concerned (environment / host / credential / port), or null
message   human wording, unchanged from interactive use — NOT for parsing
remedy    the next command or action that resolves it, or null
```

- An agent branches on **`code`**, never on `message`.
- `unspecified` is a valid, documented code for call sites not yet annotated — an agent must
  handle it (research R4).
- The failure is emitted **before any change is made** wherever the tool's existing fail-fast
  discipline applies.

## 3. Interaction guarantees

- **Never blocks on a prompt** when stdin/stdout is not an interactive terminal: the tool
  refuses and names the authorizing flag (FR-007), generalizing today's `down`/`wipe`/
  `host rm --destroy` behavior.
- **Eval surfaces are unchanged and excluded**: `host env` and `attach --print`/`--ssh-config`
  keep the Feature 005 contract — an error yields **empty stdout** and a non-zero exit — and
  do **not** accept `--json` (research R3).
- **Machine-readable help** enumerates commands, arguments and effects, derived from the real
  command tree so it cannot drift (FR-008, research R8).

## 4. `context`

One call returning the tool's view of the world. **Always succeeds** in describing state: an
empty world yields empty collections and an unreachable host is a described state, not an
error (FR-010).

Payload: `target`, `stages` (tri-state, `unusable` ≠ `absent`), `hosts`, `environments`,
`conventions` (governing project, applicable env-file **path**), `credentials`
(**locators only**), `problems`, `next_step`. See [data-model.md](../data-model.md).

Probing is **bounded to the active target** — the payload's cost does not grow with the
number of registered hosts.

## 5. `skill`

```
agent-container skill install [--agent <name>] [--user]   # default scope: project
agent-container skill update  [--agent <name>] [--user]
agent-container skill remove  [--agent <name>] [--user]
```

- Writes an **Agent Skills**-conformant folder: `skills/agent-container/SKILL.md` with
  `name` + `description` frontmatter (FR-012a). All four agents consume the same format —
  a target is only a **discovery path** (FR-017).
- **Default scope is the project**; `--user` opts in to the home configuration (FR-012b). The
  chosen scope is stated in what the command reports (FR-016).
- **Idempotent**: reinstalling an unmodified current definition changes nothing and says so
  (FR-013).
- **Never clobbers**: a hand-edited definition is detected via the frontmatter checksum and
  **refused** with the difference reported, pending explicit intent (FR-014).
- **No residue**: `remove` deletes only what the tool wrote (FR-015).
- **Refuses clearly** when the target agent's configuration is absent/unsupported, naming
  what was looked for and where (FR-018).
- The installed body **instructs the agent to pass `--json` on every invocation, and every
  example in it carries the flag** (FR-012c) — this is what makes the per-invocation choice
  in FR-001 workable.

## 6. What is NOT promised

- No stability for **human** (non-`--json`) output — it is for people and may change freely.
- No network API, daemon, or RPC surface.
- No autonomous action: the tool reports state and suggests a next step; it does not act
  unattended.
