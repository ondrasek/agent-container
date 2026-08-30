"""Property check for an agent-written AVL tree — RUN it, do not read it.

Imported next to the agent's `avl.py`. The height bound is the part that matters:
the inserts are ascending, which is the degenerate case for a plain binary search
tree, so an implementation that never rebalances degrades to a linked list and
fails here while still passing "is it sorted" checks.

Run this inside a throwaway container with no network. Executing code an LLM
wrote is exactly what the container exists to contain.
"""

import math

from avl import AVLTree

N = 300
t = AVLTree()
for v in range(1, N + 1):  # SORTED: the degenerate case for a plain BST
    t.insert(v)

assert t.in_order() == list(range(1, N + 1)), "in_order() is not sorted after inserts"
assert all(t.contains(v) for v in range(1, N + 1)), "contains() missed an inserted value"
bound = 1.44 * math.log2(N + 2)
assert t.height() <= bound, f"height {t.height()} exceeds the AVL bound {bound:.1f} — not balanced"

for v in range(1, N // 2 + 1):
    t.delete(v)
left = list(range(N // 2 + 1, N + 1))
assert t.in_order() == left, "in_order() wrong after deletes"
assert not any(t.contains(v) for v in range(1, N // 2 + 1)), "a deleted value is still present"
bound = 1.44 * math.log2(len(left) + 2)
assert t.height() <= bound, f"height {t.height()} exceeds the AVL bound after deletes"

print("VERIFY-OK")
