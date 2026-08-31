# Download

The current release is **v{{VERSION}}**. Every release is published three ways
from the same commit: to PyPI, as a GitHub Release with source archives, and as a
git tag.

<div class="release">
  <span class="ver">v{{VERSION}}</span>
  <span class="meta">latest release</span>
  <span class="spacer"></span>
  <a class="btn btn-primary" href="{{RELEASE_URL}}" rel="noopener">Release notes</a>
</div>

## Install it (recommended)

You almost certainly want the packaged CLI rather than an archive:

```bash
uv tool install agent-container      # or: pipx install agent-container
agent-container --version
```

- **PyPI project:** [pypi.org/project/agent-container](https://pypi.org/project/agent-container/)
- Full instructions, including the host side: [Installation](site:install/)

## Source code

| What | Where |
|---|---|
| **Clone** | `git clone https://github.com/ondrasek/agent-container.git` |
| **This release, tagged** | [`v{{VERSION}}`]({{RELEASE_URL}}) |
| **Tarball** | [`agent-container-{{VERSION}}.tar.gz`](https://github.com/ondrasek/agent-container/archive/refs/tags/v{{VERSION}}.tar.gz) |
| **Zip** | [`agent-container-{{VERSION}}.zip`](https://github.com/ondrasek/agent-container/archive/refs/tags/v{{VERSION}}.zip) |
| **All releases** | [github.com/ondrasek/agent-container/releases](https://github.com/ondrasek/agent-container/releases) |
| **Browse the tree** | [github.com/ondrasek/agent-container](https://github.com/ondrasek/agent-container) |

Pin a specific version instead of `main`:

```bash
git clone --branch v{{VERSION}} --depth 1 https://github.com/ondrasek/agent-container.git
```

<div class="callout" markdown="1">
<span class="label">You need a checkout on the host</span>

A PyPI install is a complete **client**. But `build` needs a checkout as the
container build context, and `up` needs the image `localhost/agent-container:latest`
to exist locally — no prebuilt image is published to any registry. So the machine
that actually runs containers needs the source, one way or another.
</div>

## Just the CLI, no install

`bin/agent-container` is a single self-contained [PEP 723](https://peps.python.org/pep-0723/)
script. Given [uv](https://docs.astral.sh/uv/), it needs nothing else:

```bash
curl -O https://raw.githubusercontent.com/ondrasek/agent-container/v{{VERSION}}/bin/agent-container
chmod +x agent-container
uv run --script ./agent-container --help
```

The `--script` form makes uv read the dependency metadata embedded in the file
and build an ephemeral environment for it.

## Provenance

Releases are built and published by GitHub Actions from the tagged commit, with
no human in the loop and no stored PyPI token:

- **PyPI uploads use OIDC Trusted Publishing**, bound to this repository and to
  the `publish.yml` workflow specifically.
- **Distributions carry [PEP 740](https://peps.python.org/pep-0740/) attestations**,
  generated at publish time and verifiable on PyPI.
- **The version is not chosen by hand.** python-semantic-release derives it from
  the Conventional Commits since the previous release, then bumps
  `pyproject.toml`, writes the changelog, tags, and creates the GitHub Release.
- **Nothing ships red.** The release workflow fires only after the full CI
  pipeline — quality gate, pinned-interpreter pytest, build, and the
  real-container acceptance suite — has passed on `main`.

## How releases reach this website

This site is rebuilt automatically by the `pages` workflow whenever a release is
published, and whenever `main` changes. It is generated from the repository's own
markdown, so the published documentation is always the documentation of the
current release. The version above is read from the tag at build time.

## Version history

The [changelog](site:changelog/) is generated from the commit history. Pre-1.0,
note one thing about how versions move:

| Commit type | Bump |
|---|---|
| `feat` | minor |
| `fix` | patch |
| breaking change | **minor** — while pre-1.0 |

A breaking change is therefore **not** visible in the version number. It is
recorded in the commit body and surfaced in the changelog, which is why the
contribution rules insist on it.

## License

Released under the [MIT License](https://github.com/ondrasek/agent-container/blob/main/LICENSE).
