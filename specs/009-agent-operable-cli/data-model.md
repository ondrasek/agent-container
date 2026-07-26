# Data Model: Agent-Operable CLI (Phase 1)

All types are in-memory/serialized only — this feature adds **no persistent tool state**. The
one artifact written outside the tool is the skill definition (owned by the operator's agent
configuration, not by the tool's state directory).

## Envelope

Every `--json` payload, success or failure. Emitted by one helper (research R1).

| Field | Type | Notes |
|-------|------|-------|
| `schema` | string | `agent-container/v1` — the inspectable contract version (FR-006) |
| `ok` | bool | success/failure, so an agent can branch without relying only on exit status |
| `data` | object | present when `ok` is true — the command's payload |
| `error` | FailureDescriptor | present when `ok` is false |

**Rules**: exactly one of `data`/`error` is present. The envelope goes to **stdout**; human
prose continues to **stderr** (FR-019). Exit status is non-zero whenever `ok` is false.

## FailureDescriptor

The structured form of a failure (FR-003/004/005). Carried by `Fatal`, rendered by `cli()`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | string | **stable** identifier for the failure class, independent of wording. Defaults to `unspecified` for call sites not yet annotated (research R4) |
| `entity` | string \| null | what it was about — environment, host, credential, port (FR-004) |
| `message` | string | the existing human wording, unchanged (FR-019) |
| `remedy` | string \| null | the next command/action that would resolve it (FR-005) |

**Rules**: `code` is drawn from a documented set; adding a code is additive, **renaming one is
a breaking change** and must bump `schema`. `message` is never the parsing surface — `code` is.

## AgentContext

The `context` payload — a serialization of Feature 007's `EnvSnapshot` plus project and
credential locators (research R5).

| Field | Type | Notes |
|-------|------|-------|
| `target` | object | active host + container identity being described |
| `stages` | list | ordered setup stages, each `{key, status, detail}` with status `satisfied`/`unsatisfied`/`unusable` — **`unusable` ≠ `absent`** |
| `hosts` | list | known hosts and reachability; an unreachable host is *described*, not an error (FR-010) |
| `environments` | list | known environments and their state |
| `conventions` | object | what applies in this directory — governing `.agent-container/` project (if any), applicable env file **path** |
| `credentials` | list | **locators only**: source kind + reference (variable name, file path, manager item). **Never a value** (FR-011) |
| `problems` | list | detected broken states, each named |
| `next_step` | object | the suggested next action + reason + equivalent command, from `recommend_next_step()` |

**Validation rules**:
- Valid and complete in **every** state, including an empty world (FR-010) — an unconfigured
  machine yields empty collections, not an error.
- **No secret value may appear in any field** (FR-011, Constitution III) — the credentials
  list carries references, never resolved values.
- Probing is bounded to the active target (inherited from Feature 007), so the payload's cost
  does not scale with the number of registered hosts.

## SkillArtifact

What `skill install` writes — an **Agent Skills** standard-conformant folder (FR-012a).

```
<agent-config>/skills/agent-container/
└── SKILL.md          # required: YAML frontmatter + instructions
```

| Frontmatter field | Notes |
|-------------------|-------|
| `name` | required by the standard |
| `description` | required by the standard — what the agent matches against |
| *(tool marker)* | generator identity + **checksum of the generated body** — the drift detector (research R7); a namespaced extra key, permitted by the standard |

**Content rule (FR-012c)**: the body MUST instruct the agent to pass `--json` on every
invocation, and **every command example it contains MUST include the flag**. Testable by
asserting no example line invokes the tool without `--json`.

## SkillTarget

A supported agent's configuration location (FR-017). All four consume the *same* standard
format, so a target is **only a discovery path** — adding an agent adds a row, not content.

| Field | Notes |
|-------|-------|
| `agent` | one of the four supported names |
| `project_path` | where the skill goes in a project (default scope, FR-012b) |
| `user_path` | where it goes under `--user` |
| `present` | whether that agent's configuration exists here — drives the refusal in FR-018 |

## State transitions (skill install/update/remove)

```
          absent ──install──▶ installed(current)
                                  │  │
              install (no-op) ◀───┘  └──▶ installed(stale)  ──update──▶ installed(current)
                                                  │
   operator edits the file  ─────────────────────▶ modified
                                                  │
                              update ──▶ REFUSE (report difference, require explicit intent)
                                                  │
  installed(any) ──remove──▶ absent  (deletes only what the tool wrote; no residue)
```
