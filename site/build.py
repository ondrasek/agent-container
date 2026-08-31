#!/usr/bin/env python3
"""Build the agent-container website into site/_site/.

The site is a thin rendering layer over the repository's OWN markdown — README,
docs/, samples/, CONTRIBUTING, CHANGELOG, the ADRs. Nothing is transcribed, so
the published pages cannot drift from the repo; editing a doc IS editing the
site. Only the landing page and a handful of task pages under site/content/ are
written for the web.

Run:
    uv run --no-project --with markdown --with pygments site/build.py

Optional environment (the Pages workflow supplies these; all have fallbacks):
    SITE_VERSION      version string shown in the header/footer (e.g. 0.45.0)
    SITE_RELEASE_URL  URL of the corresponding GitHub Release
    SITE_RELEASE_DATE ISO date of that release
    SITE_BUILT        ISO date of this build
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import markdown

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
OUT = SITE / "_site"

GH = "https://github.com/ondrasek/agent-container"
BLOB = f"{GH}/blob/main"
TREE = f"{GH}/tree/main"
PYPI = "https://pypi.org/project/agent-container/"
LINKEDIN = "https://linkedin.com/in/OndrejKrajicek"
TALKS = "https://ondrasek.github.io/talks"

DESCRIPTION = (
    "Always-on containerized development environment for AI coding agents. "
    "Declare an agent, its task, its credentials and its egress boundary as "
    "YAML; converge it onto a VPS over SSH."
)


# --------------------------------------------------------------------------
# page manifest
# --------------------------------------------------------------------------


@dataclass
class Page:
    """One output page.

    url    site-root-relative, always ending in '/' (or '' for the home page)
    src    repo-relative source; None for a page generated in code
    nav    label in the top nav, or None to keep it out of the nav
    toc    render the sidebar table of contents
    """

    url: str
    title: str
    src: str | None = None
    nav: str | None = None
    toc: bool = True
    kind: str = "md"  # md | html | generated
    blurb: str = ""
    subtitle: str = ""
    source_label: str = ""


DOCS = [
    (
        "layout.md",
        "Filesystem layout",
        "Where every file lives: the two config levels, the build context, and why a pre-011 layout is refused rather than migrated.",
    ),
    (
        "orchestration.md",
        "Orchestration",
        "How a deployment becomes a compose project generated and run on the target host.",
    ),
    (
        "execution.md",
        "Execution modes",
        "Interactive versus headless, workspaces, clone-on-start, and what the container's exit code means.",
    ),
    (
        "agent-as-code.md",
        "Agent as code",
        "The `.agent-container/` spec: plan, apply, destroy, and the deterministic identity that defines ownership.",
    ),
    (
        "agent-interface.md",
        "Agent interface",
        "The machine-readable surface an AI agent drives: `context`, `commands`, and the installable skill.",
    ),
    (
        "credentials.md",
        "Credentials",
        "The least-exposure contract: never baked, never on argv, never printed, never on a volume.",
    ),
    (
        "egress.md",
        "Egress control",
        "Packet-level default-deny in a shared netns, the sidecar that holds NET_ADMIN, and why squid splices rather than bumps.",
    ),
    (
        "threat-model.md",
        "Threat model",
        "What this design defends against, what it does not, and the reconciliation every feature owes it.",
    ),
    (
        "shell-integration.md",
        "Shell integration",
        "Print/emit mode: config on stdout, humans on stderr, and the eval contract.",
    ),
    (
        "observability.md",
        "Observability",
        "Two legs, one payload: an unconditional local trail plus a zero-dependency write-time export.",
    ),
    (
        "control-plane.md",
        "Control plane",
        "A second image holding a standing key, so you can drive everything from a phone.",
    ),
    (
        "inventory.md",
        "Inventory",
        "What the tool created, verified by observation — and why unreachable is never reported as stopped.",
    ),
    (
        "doctor.md",
        "Doctor (preflight)",
        "Report whether a deploy would work without performing one.",
    ),
    ("smoke-test.md", "Smoke test", "The manual end-to-end check for a fresh host."),
]

ADRS = [
    ("0001-runtime-and-base-image.md", "ADR 0001 — Runtime and base image"),
    (
        "0002-host-driver-provisioner-and-compose-run.md",
        "ADR 0002 — Host driver, provisioner and compose run",
    ),
]

PAGES: list[Page] = [
    Page("", "agent-container", src="site/content/index.html", nav="Home", toc=False, kind="html"),
    Page(
        "install/",
        "Installation",
        src="site/content/install.md",
        nav="Install",
        subtitle="Get the CLI onto your machine, and a runtime onto your host.",
    ),
    Page(
        "tutorial/",
        "Tutorial",
        src="site/content/tutorial.md",
        nav="Tutorial",
        subtitle="From an empty VPS to an agent you can detach from — in eight steps.",
    ),
    Page(
        "samples/",
        "Samples",
        src="samples/README.md",
        nav="Samples",
        subtitle="Four agent specifications you can apply against a real model.",
        source_label="samples/README.md",
    ),
    Page(
        "docs/",
        "Documentation",
        nav="Docs",
        kind="generated",
        toc=False,
        subtitle="The durable explanation of each subsystem, rendered from the repository.",
    ),
    Page(
        "guide/",
        "Reference guide",
        src="README.md",
        subtitle="The complete README: deployment, the CLI surface, the image, the entrypoint.",
        source_label="README.md",
    ),
    Page(
        "download/",
        "Download",
        src="site/content/download.md",
        nav="Download",
        subtitle="Releases, PyPI, source archives and provenance.",
    ),
    Page(
        "contributing/",
        "Contributing",
        src="CONTRIBUTING.md",
        nav="Contributing",
        subtitle="The ground rules, the quality gate and how a change gets released.",
        source_label="CONTRIBUTING.md",
    ),
    Page(
        "changelog/",
        "Changelog",
        src="CHANGELOG.md",
        subtitle="Generated from Conventional Commits by python-semantic-release.",
        source_label="CHANGELOG.md",
    ),
]

for _fname, _title, _blurb in DOCS:
    PAGES.append(
        Page(
            f"docs/{_fname[:-3]}/",
            _title,
            src=f"docs/{_fname}",
            blurb=_blurb,
            source_label=f"docs/{_fname}",
        )
    )
for _fname, _title in ADRS:
    PAGES.append(
        Page(
            f"docs/decisions/{_fname[:-3]}/",
            _title,
            src=f"docs/decisions/{_fname}",
            source_label=f"docs/decisions/{_fname}",
        )
    )

BY_SRC = {p.src: p for p in PAGES if p.src}


# --------------------------------------------------------------------------
# release metadata
# --------------------------------------------------------------------------


def project_version() -> str:
    """The version in pyproject.toml — the value semantic-release bumps."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def git_date() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "log", "-1", "--format=%cs"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip()
    except OSError, subprocess.SubprocessError:
        return ""


VERSION = os.environ.get("SITE_VERSION") or project_version()
RELEASE_URL = os.environ.get("SITE_RELEASE_URL") or f"{GH}/releases/tag/v{VERSION}"
RELEASE_DATE = os.environ.get("SITE_RELEASE_DATE") or git_date()
BUILT = os.environ.get("SITE_BUILT") or RELEASE_DATE


# --------------------------------------------------------------------------
# link rewriting
# --------------------------------------------------------------------------

ATTR_RE = re.compile(r'\b(href|src)="([^"]*)"')
ABSOLUTE = ("http://", "https://", "mailto:", "data:", "//")


def relative(from_url: str, to_url: str) -> str:
    """Site-root-relative `to_url` expressed relative to the page at `from_url`.

    Keeping every internal link relative means the same output works at the
    project-pages base path, at a user-pages root, and from a `file://` preview
    of _site/ — nothing has to know the deployment prefix.
    """
    depth = len([s for s in from_url.split("/") if s])
    prefix = "../" * depth
    return (prefix + to_url) or "./"


def rewrite_target(raw: str, src_dir: Path, from_url: str) -> str:
    """Map one repo-relative link onto the site, or onto GitHub when unrendered."""
    if not raw or raw.startswith("#") or raw.startswith(ABSOLUTE):
        return raw

    # `site:` is how a page authored under site/content/ links to another PAGE
    # rather than to a repository file. Repo-relative resolution cannot express
    # that — site/content/../docs/layout/ is not a path that exists — and an
    # explicit scheme beats a rule that silently falls through to a GitHub link.
    if raw.startswith("site:"):
        rest = raw[len("site:") :]
        path, _, frag = rest.partition("#")
        return relative(from_url, path) + (f"#{frag}" if frag else "")

    path, _, frag = raw.partition("#")
    frag = f"#{frag}" if frag else ""
    if not path:
        return raw

    try:
        target = (src_dir / path).resolve().relative_to(REPO)
    except ValueError:
        return raw  # escapes the repo — leave it alone
    rel = target.as_posix()

    page = BY_SRC.get(rel)
    if page is not None:
        return relative(from_url, page.url) + frag

    on_disk = REPO / rel
    if on_disk.is_dir():
        return f"{TREE}/{rel}{frag}"
    return f"{BLOB}/{rel}{frag}"


def rewrite_links(body: str, src_dir: Path, from_url: str) -> str:
    def sub(m: re.Match[str]) -> str:
        attr, value = m.group(1), m.group(2)
        return f'{attr}="{rewrite_target(html.unescape(value), src_dir, from_url)}"'

    return ATTR_RE.sub(sub, body)


TABLE_RE = re.compile(r"<table>.*?</table>", re.DOTALL)


def wrap_tables(body: str) -> str:
    """Give every table its own horizontal scroller so the page body never does."""
    return TABLE_RE.sub(lambda m: f'<div class="table-scroll">{m.group(0)}</div>', body)


# --------------------------------------------------------------------------
# chrome
# --------------------------------------------------------------------------

GH_ICON = (
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 '
    "3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-"
    ".49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 "
    "1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 "
    "0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 "
    "2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 "
    "1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 "
    '2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>'
)

THEME_ICON = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 '
    '1 1-9-9z"/></svg>'
)

THEME_SCRIPT = """
(function () {
  var root = document.documentElement;
  try {
    var saved = localStorage.getItem('ac-theme');
    if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
  } catch (e) { /* private mode, blocked storage — the media query still works */ }
  window.__acToggleTheme = function () {
    var media = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    var now = root.getAttribute('data-theme') || media;
    var next = now === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('ac-theme', next); } catch (e) { /* nothing to do */ }
  };
})();
"""


def nav_html(current: Page) -> str:
    items = []
    for p in PAGES:
        if not p.nav:
            continue
        cls = ' class="active"' if p is current else ""
        items.append(f'<a href="{relative(current.url, p.url)}"{cls}>{p.nav}</a>')
    items.append(f'<a class="gh" href="{GH}" rel="noopener">{GH_ICON}GitHub</a>')
    return "\n        ".join(items)


def footer_html(current: Page) -> str:
    def link(url: str, label: str) -> str:
        return f'<li><a href="{relative(current.url, url)}">{label}</a></li>'

    def ext(url: str, label: str) -> str:
        return f'<li><a href="{url}" rel="noopener">{label}</a></li>'

    docs_links = "\n            ".join(link(f"docs/{f[:-3]}/", t) for f, t, _ in DOCS[:6])
    return f"""
      <div class="footer-grid">
        <div>
          <h4>Start here</h4>
          <ul>
            {link("install/", "Installation")}
            {link("tutorial/", "Tutorial")}
            {link("samples/", "Samples")}
            {link("download/", "Download")}
          </ul>
        </div>
        <div>
          <h4>Documentation</h4>
          <ul>
            {docs_links}
            {link("docs/", "All documents")}
          </ul>
        </div>
        <div>
          <h4>Project</h4>
          <ul>
            {link("guide/", "Reference guide")}
            {link("contributing/", "Contributing")}
            {link("changelog/", "Changelog")}
            {ext(f"{GH}/issues", "Issues")}
            {ext(f"{BLOB}/LICENSE", "MIT License")}
          </ul>
        </div>
        <div>
          <h4>Author</h4>
          <ul>
            {ext(LINKEDIN, "LinkedIn — Ondrej Krajicek")}
            {ext(TALKS, "Talks")}
            {ext("https://github.com/ondrasek", "GitHub — @ondrasek")}
            {ext(PYPI, "PyPI — agent-container")}
          </ul>
        </div>
      </div>
      <div class="colophon">
        <span>&copy; 2026 Ondrej Krajicek — released under the
          <a href="{BLOB}/LICENSE" rel="noopener">MIT License</a>.</span>
        <span class="spacer">Version {VERSION}{f" &middot; built {BUILT}" if BUILT else ""}</span>
        <button class="theme-toggle" type="button" onclick="window.__acToggleTheme()"
                aria-label="Toggle light and dark theme" title="Toggle theme">{THEME_ICON}</button>
      </div>"""


SHELL = """<!doctype html>
<html lang="en" prefix="og: https://ogp.me/ns#">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="author" content="Ondrej Krajicek">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="agent-container">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://ondrasek.github.io/agent-container/{url}">
<link rel="icon" href="{root}assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{root}assets/style.css">
<script>{theme_script}</script>
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{root}">
      <span class="mark">&gt;_</span>agent-container
    </a>
    <nav class="main" aria-label="Main">
        {nav}
    </nav>
  </div>
</header>
{content}
<footer class="site-footer">
  <div class="wrap">{footer}
  </div>
</footer>
</body>
</html>
"""


def render_shell(page: Page, content: str) -> str:
    description = page.blurb or page.subtitle or DESCRIPTION
    title = "agent-container" if not page.url else f"{page.title} — agent-container"
    return SHELL.format(
        title=html.escape(title),
        description=html.escape(description, quote=True),
        url=page.url,
        root=relative(page.url, ""),
        theme_script=THEME_SCRIPT,
        nav=nav_html(page),
        footer=footer_html(page),
        content=content,
    )


def article(page: Page, body: str, toc: str) -> str:
    """A prose page: optional sticky TOC, a title block, the rendered body."""
    source = ""
    if page.source_label:
        source = (
            f'<p style="color:var(--text-mute);font-size:.85rem;margin:-0.5rem 0 1.5rem">'
            f'Rendered from <a href="{BLOB}/{page.source_label}" rel="noopener">'
            f"<code>{page.source_label}</code></a> in the repository.</p>"
        )
    sub = (
        f'<p class="lede" style="font-size:1.05rem;margin:-0.6rem 0 1.6rem">'
        f"{html.escape(page.subtitle)}</p>"
        if page.subtitle
        else ""
    )
    aside = ""
    cls = "page no-toc"
    if page.toc and toc.strip() and toc.count("<li>") > 2:
        aside = f'<aside class="toc"><div class="toc-title">On this page</div>{toc}</aside>'
        cls = "page"
    return f"""<div class="{cls}">
  <main class="prose" id="content">
    <h1>{html.escape(page.title)}</h1>
    {sub}{source}
    {body}
  </main>
  {aside}
</div>"""


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------


def slugify_github(value: str, separator: str) -> str:
    """Slugify headings the way GitHub does, not the way Python-Markdown does.

    The repository's markdown is written against GitHub's renderer and links
    between documents by anchor. The two algorithms agree until a heading
    contains punctuation that becomes a gap: GitHub drops the em dash and keeps
    BOTH surrounding spaces as separators ("a -- b"), while Python-Markdown
    collapses runs to one. Cross-document anchors silently died on exactly those
    headings, which are the memorable ones.
    """
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"\s", separator, value.strip())


def make_md() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=[
            "extra",  # tables, fenced code, attr_list, def_list, footnotes
            "codehilite",
            "toc",
            "sane_lists",
            "admonition",
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "guess_lang": False,  # an ASCII diagram must stay an ASCII diagram
                "linenums": False,
            },
            "toc": {"permalink": "#", "toc_depth": "2-3", "slugify": slugify_github},
        },
    )


H1_RE = re.compile(r"^\s*#\s+.*?$", re.MULTILINE)


def strip_leading_h1(text: str) -> str:
    """The shell already prints the page title; drop the source's own first H1."""
    m = H1_RE.search(text)
    if m and text[: m.start()].strip() == "":
        return text[m.end() :].lstrip("\n")
    return text


def substitute(text: str) -> str:
    """Release facts the site quotes, injected at build time rather than typed."""
    return text.replace("{{VERSION}}", VERSION).replace("{{RELEASE_URL}}", RELEASE_URL)


SAMPLE_TITLES = {
    "01-workspace-write": "A headless agent, a task, one credential",
    "02-egress-boundary": "The same, from behind a declared egress boundary",
    "03-clone-commit-push": "Clone on start, three commits, a forge token",
    "04-avl-tree": "Real software, tests and a TUI — the hard one",
}


def samples_appendix() -> str:
    """Show each sample's actual spec, rather than only linking to it.

    The samples README explains that the YAML *is* the sample; a page that then
    makes you leave to read it has undercut its own point.
    """
    parts = ["\n## The specifications in full\n"]
    for name, title in SAMPLE_TITLES.items():
        spec = REPO / "samples" / name / ".agent-container" / "environments.yaml"
        if not spec.exists():
            continue
        parts.append(f"\n### `{name}` — {title}\n")
        parts.append(
            f"[Browse this sample on GitHub]({TREE}/samples/{name}) · "
            f"apply it with `cd samples/{name} && agent-container plan`\n"
        )
        parts.append("\n```yaml\n" + spec.read_text(encoding="utf-8").rstrip() + "\n```\n")
    return "".join(parts)


def render_markdown(page: Page) -> str:
    assert page.src is not None
    src_path = REPO / page.src
    text = substitute(strip_leading_h1(src_path.read_text(encoding="utf-8")))
    if page.url == "samples/":
        text += samples_appendix()
    md = make_md()
    body = md.convert(text)
    body = rewrite_links(body, src_path.parent, page.url)
    body = wrap_tables(body)
    toc = rewrite_links(getattr(md, "toc", ""), src_path.parent, page.url)
    return article(page, body, toc)


def render_html_page(page: Page) -> str:
    assert page.src is not None
    return substitute((REPO / page.src).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# generated: the documentation index
# --------------------------------------------------------------------------


def render_docs_index(page: Page) -> str:
    cards = "\n      ".join(
        f'<a href="{relative(page.url, f"docs/{f[:-3]}/")}">'
        f'<span class="n">{html.escape(t)}</span>'
        f'<span class="d">{html.escape(b)}</span></a>'
        for f, t, b in DOCS
    )
    adrs = "\n      ".join(
        f'<a href="{relative(page.url, f"docs/decisions/{f[:-3]}/")}">'
        f'<span class="n">{html.escape(t)}</span>'
        f'<span class="d">An architecture decision record: the context, the '
        f"options and what was chosen.</span></a>"
        for f, t in ADRS
    )
    specs = "\n      ".join(
        f'<a href="{TREE}/specs/{d.name}" rel="noopener">'
        f'<span class="n">{html.escape(d.name)}</span>'
        f'<span class="d">Feature specification, requirements and checklists.</span></a>'
        for d in sorted((REPO / "specs").iterdir())
        if d.is_dir()
    )
    body = f"""<h2 id="subsystems">Subsystems</h2>
    <p>One document per subsystem. Each is the durable explanation — the feature
    specifications under <code>specs/</code> hold the requirements that produced it.</p>
    <div class="doclist">
      {cards}
    </div>

    <h2 id="decisions">Architecture decisions</h2>
    <div class="doclist">
      {adrs}
    </div>

    <h2 id="contract">The design contract</h2>
    <p><a href="{BLOB}/CLAUDE.md" rel="noopener"><code>CLAUDE.md</code></a> is the
    load-bearing contract: the invariants a change must not break. It is
    deliberately short. Everything longer lives in the documents above.</p>
    <p>The <a href="{relative(page.url, "guide/")}">reference guide</a> is the
    repository README in full — deployment, the whole CLI surface, the image
    layering, the entrypoint and the release process.</p>

    <h2 id="specs">Feature specifications</h2>
    <p>Every feature carries a numbered specification directory with its
    requirements, its checklists and its threat-model reconciliation. These stay
    on GitHub rather than being republished here.</p>
    <div class="doclist">
      {specs}
    </div>"""
    return article(page, body, "")


# --------------------------------------------------------------------------
# favicon
# --------------------------------------------------------------------------

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0f766e"/>
  <path d="M8 11l5 5-5 5" fill="none" stroke="#e6f2f0" stroke-width="2.6"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M16.5 21.5h7.5" fill="none" stroke="#5eead4" stroke-width="2.6"
        stroke-linecap="round"/>
</svg>
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def write(rel_url: str, content: str) -> Path:
    dest = OUT / rel_url / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    missing = [p.src for p in PAGES if p.src and not (REPO / p.src).exists()]
    if missing:
        print("error: missing source files:", ", ".join(missing), file=sys.stderr)
        return 1

    for page in PAGES:
        if page.kind == "html":
            content = render_shell(page, render_html_page(page))
        elif page.kind == "generated":
            content = render_shell(page, render_docs_index(page))
        else:
            content = render_shell(page, render_markdown(page))
        write(page.url, content)

    assets = OUT / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copy2(SITE / "assets" / "style.css", assets / "style.css")
    (assets / "favicon.svg").write_text(FAVICON, encoding="utf-8")

    # Jekyll would otherwise eat directories whose names begin with an underscore.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://ondrasek.github.io/agent-container/sitemap.xml\n",
        encoding="utf-8",
    )
    urls = "\n".join(
        f"  <url><loc>https://ondrasek.github.io/agent-container/{p.url}</loc></url>" for p in PAGES
    )
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
        encoding="utf-8",
    )

    print(f"built {len(PAGES)} pages into {OUT.relative_to(REPO)} (version {VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
