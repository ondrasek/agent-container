#!/usr/bin/env python3
"""Check the built site: internal links resolve, anchors exist, nothing is stray.

Run after site/build.py:
    uv run --no-project --python 3.14 site/check.py

Exit 0 when clean, 1 otherwise. Kept dependency-free so it can run anywhere the
build ran, and pointed only at LOCAL targets — an external link checker would
make the build depend on somebody else's uptime.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "_site"

ATTR = re.compile(r'\b(?:href|src)="([^"]*)"')
ID = re.compile(r'\bid="([^"]+)"')
ABSOLUTE = ("http://", "https://", "mailto:", "data:", "//")


def main() -> int:
    if not OUT.is_dir():
        print(f"error: {OUT} does not exist — run site/build.py first", file=sys.stderr)
        return 1

    pages = sorted(OUT.rglob("*.html"))
    anchors: dict[Path, set[str]] = {p: set(ID.findall(p.read_text("utf-8"))) for p in pages}
    problems: list[str] = []
    internal = external = 0

    for page in pages:
        text = page.read_text("utf-8")
        for raw in ATTR.findall(text):
            raw = html.unescape(raw)
            if not raw or raw.startswith(ABSOLUTE):
                external += 1
                continue
            if raw.startswith("site:"):
                problems.append(f"{page.relative_to(OUT)}: unrewritten site: link {raw!r}")
                continue
            if "{{" in raw:
                problems.append(f"{page.relative_to(OUT)}: unsubstituted placeholder {raw!r}")
                continue

            path, _, frag = raw.partition("#")
            internal += 1
            if not path:
                if frag and frag not in anchors[page]:
                    problems.append(f"{page.relative_to(OUT)}: dead anchor #{frag}")
                continue

            target = (page.parent / path).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                problems.append(f"{page.relative_to(OUT)}: dead link {raw!r}")
                continue
            if frag and target.suffix == ".html":
                if frag not in anchors.get(target, set()):
                    rel = target.relative_to(OUT)
                    problems.append(f"{page.relative_to(OUT)}: dead anchor {raw!r} -> {rel}")

    # A page whose body never rendered is worse than a dead link: it looks fine.
    for page in pages:
        if len(page.read_text("utf-8")) < 2000:
            problems.append(
                f"{page.relative_to(OUT)}: suspiciously small ({page.stat().st_size} bytes)"
            )

    for p in problems:
        print(f"  {p}")
    print(
        f"\n{len(pages)} pages · {internal} internal links checked · "
        f"{external} external skipped · {len(problems)} problem(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
