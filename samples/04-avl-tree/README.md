# 04 — the agent writes working software

```bash
export SAMPLE_REPO=https://github.com/<you>/<scratch-repo>
export SAMPLE_GH_TOKEN=ghp_...
./run.sh claude     # or: ./run.sh pi
```

**The hardest sample.** A small model will often fail it, and that is information
rather than a defect.

## What it proves

The agent writes an **AVL tree from scratch**, its own `unittest` suite, and an
interactive TUI — then all three are **verified by running them**, not by reading
them.

## The check that actually bites

```python
for v in range(1, 301):  # ASCENDING — the degenerate case for a plain BST
    t.insert(v)
assert t.height() <= 1.44 * math.log2(302)
```

A tree that never rebalances degrades to a linked list on sorted input. It would
still pass every "is the output sorted?" test — `in_order()` returns the right
list, `contains()` finds everything — while being **the exact data structure the
task said not to write**. The height bound is what separates an AVL tree from a
sorted linked list, so it is the assertion that matters.

The sample also refuses an `avl.py` that *imports* a third-party tree. The check
matches **import statements**, deliberately: an earlier version searched for the
substring `avltree` anywhere in the file and failed both agents for naming their
own class `AVLTree`.

## Running the agent's code is itself a hazard

Executing code an LLM just wrote is precisely what this whole tool exists to
avoid doing on a host. So verification runs in a **throwaway container with
`--network none`**, mounting the code read-only. The container is the blast
radius.

Three things must pass: the agent's own tests, the balance property, and the TUI
responding to piped input.

## Files

| File | Purpose |
|---|---|
| `task.txt` | The three-part task with an explicit API contract |
| `verify.py` | The property check, imported next to the agent's `avl.py` |
| `run.sh` | Deploys, fetches the pushed branch, runs everything in a sealed container |

## Afterwards

The cloned result is left at `$AGENT_CONTAINER_ROOT/verify/avl/<agent>-<token>/`
so you can read the code, or play with the TUI:

```bash
python tui.py
i 5
i 3
p
q
```
