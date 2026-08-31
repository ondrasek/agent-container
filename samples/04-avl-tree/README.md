# 04 — the agent writes working software

```bash
$EDITOR .agent-container/environments.yaml     # set repo: to your own
export ANTHROPIC_API_KEY=sk-ant-... SAMPLE_GH_TOKEN=ghp_...
agent-container plan && agent-container apply
```

**The hardest sample.** A small model will often fail it, and that is
information rather than a defect.

## What it asks for

An AVL tree written from scratch, a `unittest` suite, and an interactive TUI —
with an explicit API contract in the task so the result can be checked
mechanically rather than admired.

## Verify by RUNNING it, not by reading it

Executing code an LLM just wrote is exactly what this tool exists to avoid doing
on a host, so run it in a throwaway container with no network:

```bash
git clone --branch sample04-avl <your repo> /tmp/avl && cd /tmp/avl/avl/sample04
cat > verify.py <<'PY'
import math
from avl import AVLTree
N = 300
t = AVLTree()
for v in range(1, N + 1):          # ASCENDING: the degenerate case for a plain BST
    t.insert(v)
assert t.in_order() == list(range(1, N + 1))
assert all(t.contains(v) for v in range(1, N + 1))
assert t.height() <= 1.44 * math.log2(N + 2), f"height {t.height()} — not balanced"
print("VERIFY-OK")
PY
docker run --rm --network none -v "$PWD:/w:ro" -w /w python:3.13-slim \
  sh -c 'python -m unittest discover -p "test_*.py" && python verify.py && printf "i 5\ni 3\np\nq\n" | python tui.py'
```

## The check that actually bites

The height bound. A tree that never rebalances degrades to a linked list on
sorted input — and it would still pass every "is the output sorted?" test, since
`in_order()` returns the right list and `contains()` finds everything, while
being **the exact data structure the task said not to write**. The bound is what
separates an AVL tree from a sorted linked list.

Also worth checking that `avl.py` does not simply `import avltree`. Match the
**import statement**, not the substring: an earlier version of this check
searched for `avltree` anywhere in the file and failed both agents for naming
their own class `AVLTree`.
