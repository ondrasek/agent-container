# Quickstart: Public-key collection

Validation scenarios. Each maps to a success criterion; each is runnable.

Prerequisites: a working `agent-container up` on this host, and `ssh-keygen`.

---

## S1 — Register three devices once, deploy with no flags (SC-001)

```sh
mkdir -p ~/.config/agent-container
for d in iPhone iPad Macbook; do
  ssh-keygen -t ed25519 -N '' -C "$d" -f "$CLAUDE_JOB_DIR/tmp/$d" >/dev/null
  cat "$CLAUDE_JOB_DIR/tmp/$d.pub" >> ~/.config/agent-container/authorized_keys
done

agent-container up demo            # NO --authorized-key
```

**Expect**: the pre-deploy output lists three fingerprints with the comments
`iPhone`, `iPad`, `Macbook`, and names `~/.config/agent-container/authorized_keys`
as the source. Then each of the three keys logs in:

```sh
for d in iPhone iPad Macbook; do
  ssh -i "$CLAUDE_JOB_DIR/tmp/$d" -o IdentitiesOnly=yes \
      -o IdentityAgent=none -p "$(agent-container port demo)" dev@localhost true \
    && echo "$d OK"
done
```

Three OKs. Zero flags on the deploy.

---

## S2 — A project narrows the set (SC-002)

```sh
mkdir -p .agent-container
cat "$CLAUDE_JOB_DIR/tmp/Macbook.pub" > .agent-container/authorized_keys
agent-container up scoped
```

**Expect**: the statement lists **one** fingerprint (`Macbook`) and names the
project file. `iPhone` and `iPad` are absent — the project replaced the user
collection, it did not add to it. Confirm by attempting `iPhone`: refused.

---

## S3 — Removal actually revokes (SC-003) — the decisive scenario

```sh
grep -v iPad ~/.config/agent-container/authorized_keys > "$CLAUDE_JOB_DIR/tmp/ak"
cp "$CLAUDE_JOB_DIR/tmp/ak" ~/.config/agent-container/authorized_keys

agent-container down demo && agent-container up demo

ssh -i "$CLAUDE_JOB_DIR/tmp/iPad" -o IdentitiesOnly=yes -o IdentityAgent=none \
    -o BatchMode=yes -p "$(agent-container port demo)" dev@localhost true
```

**Expect**: **non-zero** — permission denied. And the other two still work.

This is the scenario the current union-based entrypoint fails: the key persists on
the `ssh` volume and would still admit. If this passes, the managed region works;
if it passes only because the volume was destroyed, the test is invalid — the
volume must survive the cycle. Verify it did:

```sh
agent-container exec demo -- ls -l ~/.ssh/authorized_keys   # pre-existing mtime lineage
```

---

## S4 — A hand-added key survives (SC-010, C26)

```sh
agent-container exec demo -- sh -c \
  'printf "%s\n" "$(cat /dev/stdin)" >> ~/.ssh/authorized_keys' \
  < "$CLAUDE_JOB_DIR/tmp/iPad.pub"

agent-container down demo && agent-container up demo
agent-container exec demo -- grep -c iPad ~/.ssh/authorized_keys
```

**Expect**: `1`. The line sits outside the managed region and is untouched, even
though `iPad` is no longer in the collection. Managed and hand-authored coexist.

---

## S5 — Malformed and private entries refuse early (SC-004, SC-005)

```sh
echo "ssh-ed25519 NOT-BASE64 broken" >> ~/.config/agent-container/authorized_keys
agent-container up refused; echo "exit=$?"
```

**Expect**: non-zero, message names the file **and the line number**, and **no
container exists** (`agent-container list` does not show `refused`).

```sh
sed -i.bak '$d' ~/.config/agent-container/authorized_keys
cat "$CLAUDE_JOB_DIR/tmp/iPhone" >> ~/.config/agent-container/authorized_keys  # PRIVATE
agent-container up refused; echo "exit=$?"
```

**Expect**: non-zero, and the message says the entry is a **private** key. Confirm
nothing leaked:

```sh
grep -rl "BEGIN OPENSSH PRIVATE KEY" "$(agent-container state-dir)" ; echo "found=$?"
```

**Expect**: no match.

---

## S6 — Declared-empty vs undeclared (SC-007, SC-011, C3/C4)

```sh
: > ~/.config/agent-container/authorized_keys      # declared EMPTY
agent-container up empty
```

**Expect**: deploy succeeds, **warns** that the collection is empty and admits
nobody, and names the file.

```sh
rm ~/.config/agent-container/authorized_keys       # UNDECLARED
agent-container up plain --authorized-key "$CLAUDE_JOB_DIR/tmp/iPhone.pub"
```

**Expect**: no warning, no mention of a collection, and behaviour identical to
before this feature existed. The two runs must be distinguishable in output — that
distinction is the Constitution VIII requirement.

---

## S7 — It reaches a REMOTE host (C20) — settles the R4 contradiction

```sh
agent-container up remote-demo --host <remote>
agent-container exec remote-demo --host <remote> -- \
  sed -n '/BEGIN agent-container managed keys/,/END/p' ~/.ssh/authorized_keys
```

**Expect**: the admit set, non-empty. An empty region here means the injection did
not cross the context — which is exactly what one of the two docstrings in R4
predicts. Run this against a genuinely remote daemon (a local podman socket does
not exercise it), and record the result in `research.md`: one docstring is wrong
and must be corrected either way.


---

## S8 — Stopped is not empty (SC-013, C31)

```sh
agent-container up demo
agent-container keys show demo            # running
agent-container stop demo
agent-container keys show demo            # stopped
```

**Expect from the first**: projected and observed both printed, and **agreeing** (SC-006).
Check the agreement the way the contract demands — against the environment, not the input
file:

```sh
agent-container exec demo -- sed -n \
  '/BEGIN agent-container managed keys/,/END/p' ~/.ssh/authorized_keys \
  | ssh-keygen -l -f /dev/stdin
```

The fingerprints must match what `keys show` printed. Comparing against
`~/.config/agent-container/authorized_keys` instead would compare a projection with
itself, which is what SC-006 was rewritten to forbid.

**Expect from the second**: observed as
**`undetermined`** — *not* an empty set, and not the projection quietly standing in for
it. Then the genuinely-empty case, for contrast:

```sh
: > ~/.config/agent-container/authorized_keys      # declared empty
agent-container down demo && agent-container up demo
agent-container keys show demo
```

**Expect**: observed is **empty** — a running environment whose region really does admit
nobody. The two outputs must be visibly different. "Nobody is authorised" and "we did not
look" are different claims, and an operator deciding whether they are locked out needs to
know which one they are reading.

---

## S9 — One unreachable environment does not sink the listing (SC-014, C32)

```sh
agent-container up a; agent-container up b; agent-container up c
agent-container stop b
agent-container keys ls; echo "exit=$?"
```

**Expect**: **three rows**. `a` and `c` show observed sets; `b` shows `undetermined`. The
listing does not abort at `b`, and the exit status does not report plain success — it must
not claim to have examined `b`. A query that stopped at the first unreachable environment
would leave an operator believing the remaining ones were fine because they were never
mentioned.


---

## S10 — A resume tells you the collection moved on (SC-008, C23)

```sh
agent-container up demo
grep -v iPad ~/.config/agent-container/authorized_keys > "$CLAUDE_JOB_DIR/tmp/ak"
cp "$CLAUDE_JOB_DIR/tmp/ak" ~/.config/agent-container/authorized_keys

agent-container stop demo
agent-container start demo
```

**Expect**: `start` **warns** that the collection has changed, names `iPad` as the
difference, and points to `redeploy`. It must **not** silently re-apply — that would turn a
resume into a deploy.

Then confirm the warning was telling the truth:

```sh
ssh -i "$CLAUDE_JOB_DIR/tmp/iPad" -o IdentitiesOnly=yes -o IdentityAgent=none \
    -p "$(agent-container port demo)" dev@localhost true && echo "still admitted"
```

**Expect**: `still admitted`. That is correct behaviour, and it is exactly why the warning
has to exist — the container rewrote its own region on boot, so the stale set *looks*
freshly authoritative.

---

## S11 — A `keys add` grant does not outlive a recreate (SC-009, C25)

```sh
ssh-keygen -t ed25519 -N '' -C colleague -f "$CLAUDE_JOB_DIR/tmp/colleague" >/dev/null
agent-container keys add demo --authorized-key "$CLAUDE_JOB_DIR/tmp/colleague.pub"
ssh -i "$CLAUDE_JOB_DIR/tmp/colleague" -o IdentitiesOnly=yes -o IdentityAgent=none \
    -p "$(agent-container port demo)" dev@localhost true && echo "granted"
```

**Expect**: `granted`, and the command said the grant lasts until the next recreate.

```sh
agent-container down demo && agent-container up demo
ssh -i "$CLAUDE_JOB_DIR/tmp/colleague" -o IdentitiesOnly=yes -o IdentityAgent=none \
    -o BatchMode=yes -p "$(agent-container port demo)" dev@localhost true
```

**Expect**: **non-zero**. The grant is gone. Run S4 in the same session to confirm the other
half — the tool removes what it wrote and nothing else.

---

## S12 — An environment named `show` is not stranded (SC-012, C29)

```sh
agent-container up show
agent-container keys show show
agent-container keys add show --authorized-key "$CLAUDE_JOB_DIR/tmp/iPhone.pub"
```

**Expect**: all three work. `keys show show` queries the environment named `show`; it is not
parsed as a repeated subcommand and does not error. This looks like a joke test and is not:
`show`, `ls` and `add` all satisfy `validate_name`, and a bare-positional command layout
would have made this environment permanently unreachable through the group.
