# The inventory — what this tool ever created

`list` asks each host's daemon and is right about **what is running now**. Nothing could answer *"is
there a container on a host I removed from the registry?"* or *"something is billing me — did this tool
make it?"*

The inventory is that memory. It **remembers, compares and reports**. It deletes nothing — acting on
the result is the kill switch's job (Feature 015).

```bash
agent-container inventory list           # everything ever created, newest first
agent-container inventory reconcile      # record vs. reality
agent-container inventory list --json    # for an agent
```

## It begins at install, and is not backfilled

**Environments created before you installed this version have no entry, and never will.** That is not
a gap to fix — it is what "we recorded what we created" honestly means.

Two consequences worth knowing before they look like bugs:

- An **empty inventory** means *nothing recorded yet*, not *nothing exists*. The listing says so in
  words rather than printing an empty screen.
- A pre-existing container reconciles as **`unrecorded`**. That is the accurate answer, not a
  false negative.

**Backfilling from `<state>/<host>/*.port` was considered and rejected.** Those files are a census of
ports *allocated and not released*, so reconstructed entries would describe environments that may be
long gone, with an outcome nothing can determine. In a store the kill switch will read, a fabricated
entry is worse than an absent one.

## An entry is one deployment

| Field | |
|---|---|
| `entry_id` | generated per deployment — **the key**. Name and host are attributes |
| `name`, `host` | as they were at creation; the host reference is kept after that host leaves the registry |
| `host_provisioned` | whether the tool created the host, or merely had it registered |
| `created_at`, `outcome`, `outcome_at` | when, what became of it, and when that changed |
| `notes` | tool-generated diagnostics |

**A reused name yields another entry, never a replacement.** Create `acme`, remove it, create `acme`
again, and you have two entries — the first still recording that it was removed. If a recreation
overwrote history, the feature would erase exactly what it exists to keep.

**There is no free-text field.** Every value is tool-generated, so unlike a run record — which carries
the task text you typed — there is nowhere for a credential to arrive. That is a structural guarantee
rather than a promise, and a test keeps the field set closed.

## Four stored outcomes, and one that is never stored

| Stored | Means |
|---|---|
| `active` | expected to exist |
| `removed` | torn down **while its host remained** |
| `vanished` | found absent, with no action of ours |
| `host-gone` | its host went away and took it |

`removed` vs `host-gone` records **what disappeared, not who caused it** — which is why deprovisioning
a host is not a fifth value.

**`unknown` is not in that table, and cannot be.** It is what *reconciliation* returns for a host it
could not reach, and storing it would make the record permanently lie about a host that later comes
back. The tool refuses to write it.

## Reconciliation is fail-closed

| Result | Condition |
|---|---|
| `agreeing` | recorded active, and present |
| `missing` | recorded active, **host reachable**, container absent → recorded `vanished` |
| `unrecorded` | a container matching the tool's naming, with no entry |
| `unknown` | **the host could not be reached** |

An unreachable host is **never** reported `missing`. Invisible is indistinguishable from gone, and
guessing would send you hunting for a container sitting safely on a host you cannot currently reach.

**`unrecorded` is an observation, not a claim.** The tool recognises its own containers by a naming
convention — one you can imitate — so a match is evidence of a *name* and nothing more. The wording
never says the container is ours, and a test asserts that.

`list` prints a one-line hint when the record and reality disagree, because a discrepancy you must
already suspect in order to look for is one nobody finds.

## Retention: count only, never age

Kept **indefinitely**, with a backstop cap of **5000 entries** and **no time criterion at any level**.

This is deliberately the opposite of run-record retention, which prunes by age *and* count. A run's
value decays once its commits are ordinary history. An inventory entry's value is highest when it is
oldest — the forgotten environment on a host you stopped thinking about is the entire point. Pruning
by age would delete the feature's value first.

Pruning says so when it happens; it is never silent.

## Where it lives, and why it is shaped differently

```text
$XDG_DATA_HOME/agent-container/inventory/<entry-id>.json
```

Durable data, beside `runs/` and `egress/` — but **flat**, where those are `<host>/<environment>/`. An
entry must outlive its host's removal, and a per-host directory is deleted with the host, destroying
exactly the entries that requirement exists to keep. See [layout.md](layout.md).

## If the store is missing

Nothing changes. Every read tolerates it, no command's exit status depends on it, and a write failure
warns without failing your deploy — an environment that is running and working should not be torn down
over a bookkeeping error. But it does *warn*: an unrecorded environment is the blind spot this feature
exists to remove.
