# Phase 1 Data Model: Public-key collection

Two entities and one derived value. Nothing is stored that is not already a file an
operator can read.

---

## 1. Key collection (persistent, operator-authored)

**Location** — Feature 011's two levels, same filename at both:

| Level | Path |
|---|---|
| Project | `<project root>/.agent-container/authorized_keys` |
| User | `~/.config/agent-container/authorized_keys` |

**Format**: an OpenSSH `authorized_keys` file. Lines; `#` comments and blank lines
ignored. No new format, so no parser (R2).

**Resolution**: **project replaces user entirely** (R3). Not per-key — the
collection is one value. `settings_candidates()` already establishes the
project-then-user candidate order; the collection mirrors it with the first
existing file winning outright.

**Three states, all distinct** (Constitution VIII):

| State | Meaning | Behaviour |
|---|---|---|
| Absent | Undeclared | No auto-injection. Today's behaviour, unchanged (FR-009). |
| Present, no entries | **Declared empty** | Admits nobody. Honoured, **and warned about** (R6). |
| Present, N entries | Declared | Those N keys are the collection. |

Absent ≠ declared-empty. The tool must never report one as the other.

---

## 2. Collection entry

| Field | Source | Notes |
|---|---|---|
| `line` | verbatim from the file | what is written into the container |
| `type` | first field | `ssh-ed25519`, `ssh-rsa`, `ecdsa-*`, `sk-*` |
| `comment` | trailing field, if any | the operator's device label — `iPhone`, `iPad` |
| `fingerprint` | `ssh-keygen -l` | how a key is NAMED to the operator (never the full blob) |

**Validation** (R5), before any runtime call:

| Condition | Outcome |
|---|---|
| Parses as a public key | accepted |
| Does not parse | **refuse the deploy**, naming the file and line number |
| Is a **private** key | **refuse**, saying explicitly that it is private and must not be here |
| Duplicate of another entry | de-duplicated silently; not an error |

Refusal happens while nothing has been created. A malformed collection must never
produce a started container that admits nobody.

---

## 3. Admit set (derived, per deploy)

```
admit set = resolved collection  ∪  --authorized-key values
```

Ordered, de-duplicated, never merged across config levels. `--authorized-key`
remains **additive** (FR-008) — it widens, it does not replace, and the resulting
set is stated so neither source appears to have won silently.

**Reported before deploy** as a fingerprint list with comments, so the operator sees
which devices are about to be admitted (FR-007).

---

## 4. The managed block (in-container state)

Written to `~/.ssh/authorized_keys` on the persisted `ssh` volume:

```
# BEGIN agent-container managed keys
<one line per admit-set entry>
# END agent-container managed keys
```

**Replaced wholesale on every boot.** Content outside the markers is preserved
byte-for-byte.

| Transition | Result |
|---|---|
| Key added to collection, recreate | appears in the block |
| Key removed from collection, recreate | **gone from the block** — access ends (FR-006) |
| Collection becomes absent | block is emptied, not left stale |
| Hand-added key outside the block | survives every boot |
| Malformed pre-existing file (one marker, no pair) | refuse to rewrite; report it rather than guess a boundary |

**This block is rewritten; `~/.ssh/config`'s identically-styled block is
write-once.** Both sites must state which they are — same sentinel idiom, opposite
update rule, and a reader who assumes the wrong one either loses an agent's settings
or cannot revoke.

The union in the current entrypoint (`cat` persisted + injected + env, `awk`
de-dupe, write back) is what this replaces. That union is why removal cannot
currently revoke.
