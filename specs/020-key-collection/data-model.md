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

## 4. The managed region (in-container state)

Written to `~/.ssh/authorized_keys` on the persisted `ssh` volume:

```
# BEGIN agent-container managed keys — replaced on every boot; edit outside this region
<one line per admit-set entry>
# END agent-container managed keys
```

**Replaced wholesale on every boot.** Content outside the markers is preserved
byte-for-byte.

| Transition | Result |
|---|---|
| Key added to collection, recreate | appears in the region |
| Key removed from collection, recreate | **gone from the region** — access ends (FR-006) |
| Collection becomes absent | region is emptied, not left stale |
| Hand-added key outside the region | survives every boot |
| Malformed pre-existing file (one marker, no pair) | refuse to rewrite; report it rather than guess a boundary |

**This region is rewritten; `~/.ssh/config`'s identically-styled block is
write-once.** Both sites must state which they are — same sentinel idiom, opposite
update rule, and a reader who assumes the wrong one either loses an agent's settings
or cannot revoke.

The union in the current entrypoint (`cat` persisted + injected + env, `awk`
de-dupe, write back) is what this replaces. That union is why removal cannot
currently revoke.


---

## 5. Created-with admit set (derived, per deployment)

**Location**: the generated compose file, `host_state_dir(<host>)/<name>.compose.yaml`.

FR-013 and FR-014 both compare the current collection against *the set the deployment
was created with*, so that set must be readable after the deploy. It already is, and
**no new state is introduced**:

- Once the `ssh_authorized_keys` config uses **`content:`** (R4), the admit set is
  stored **inline in the compose file** rather than referenced by path. Reading it back
  is parsing a file the tool already wrote and already owns.
- That file is already the deployment's **existence record** — `do_start` refuses with
  *"no deployment named …"* when it is missing. So a deleted compose file produces the
  failure it produces today, and FR-013 adds no new failure mode on top of it.

**This makes the `content:` decision load-bearing twice.** It was chosen in R4 because a
`file:` config may not cross a remote context; it is *also* what puts the created-with
set where FR-013 and FR-014 can read it. Under `file:` the compose file would hold only
a path — pointing at a staged file that the next deploy overwrites, so "what was this
created with" would answer "whatever it was last staged with", which is the current
resolution, not the historical one. **A comparison against that is a comparison against
itself** — the same defect SC-006 was rewritten to avoid.

| Read | Source | When unavailable |
|---|---|---|
| **projected** | resolve the collection now | collection absent ⇒ undeclared, not empty |
| **created-with** | parse `<name>.compose.yaml` | absent ⇒ there is no deployment; report that, not agreement |
| **observed** | read the region inside the environment | unreachable or stopped ⇒ **`undetermined`** |

Three reads, three distinct absence answers. Collapsing any pair of them is what
Constitution VIII forbids.


---

## 6. Superseded: where credentials live (2026-08-24)

§3's admit set and §4's managed region are unchanged. What changed is material this
document never covered, and the omission would now read as a claim:

**Credentials are not part of the compose model.** They are pushed into the running
container over SSH (Constitution IX) and stored on **one volume per credential**,
`agent-container-<name>-cred-<kind>-<slug>`, mounted at
`/run/agent-container-secrets/<kind>/<name>` with the value in `value` at 0400,
owned by `dev`.

| State | Meaning |
|---|---|
| declared + held | normal |
| held, not declared | removed on the next deploy (reconciliation) |
| declared, not held | not yet delivered |

The volume name is the lifecycle handle. `creds rm` deletes the value inside the
running container AND drops the volume; the first is what `docker volume rm` cannot do
while the volume is in use.

These volumes are deliberately **not** in `per_container_volumes` — that list is the
fixed identity contract and these are dynamic, so they are addressed by prefix.
