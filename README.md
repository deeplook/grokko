# Grokko

[![CI](https://github.com/deeplook/grokko/actions/workflows/ci.yml/badge.svg)](https://github.com/deeplook/grokko/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/grokko.svg)](https://pypi.org/project/grokko/)
[![Python](https://img.shields.io/pypi/pyversions/grokko.svg)](https://pypi.org/project/grokko/)
[![Downloads](https://img.shields.io/pypi/dm/grokko.svg)](https://pepy.tech/project/grokko)
[![License](https://img.shields.io/pypi/l/grokko.svg)](https://pypi.org/project/grokko/)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=flat&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/deeplook)

CLI for capturing Grok session cookies, triggering account exports, polling email
for export links, downloading the ZIP, and inspecting export contents.

## Install

Requires Python `3.10+` and [uv](https://docs.astral.sh/uv/).

The easiest way is to install directly from PyPI:

```bash
uv tool install grokko
grokko setup
```

`grokko setup` installs the Playwright browser dependencies, skipping the
download if a compatible version is already present.

To install from source instead:

```bash
git clone https://github.com/deeplook/grokko
cd grokko
uv tool install .
grokko setup
```

To install into a local virtual environment:

```bash
git clone https://github.com/deeplook/grokko
cd grokko
uv venv ./myenv
uv pip install --python ./myenv .
./myenv/bin/grokko setup
```

## Plugins

`grokko` can load optional command plugins from installed packages via the
`grokko.plugins` entry-point group. Plugins are discovered automatically at
startup — no configuration needed beyond installation.

### Installing plugins

If you installed `grokko` as a uv tool, add a plugin with `--with`
(works for both a fresh install and an existing one):

```bash
uv tool install --reinstall grokko --with grokko-plugin
```

For a local plugin directory, pass the path instead of a package name:

```bash
uv tool install --reinstall grokko --with ../grokko-plugin
```

Or use the Makefile shorthand from the `grokko` source directory:

```bash
make install-tool PLUGINS="grokko-plugin"
```

If you installed `grokko` as a regular package (e.g. `uv pip install grokko`
or `pip install grokko`), install the plugin into the same environment:

```bash
pip install grokko-plugin
```

### Writing plugins

In a plugin package, expose either a Typer app or a single command callback:

```toml
[project.entry-points."grokko.plugins"]
reports = "my_package.cli:app"
details = "my_package.extra:inspect_extra"
```

If `app` is a `typer.Typer()` instance, `grokko reports ...` becomes a command
group. If `inspect_extra` is a callable command, `grokko details` becomes a
single command.

## Quick Examples

Capture cookies from your local Chrome profile:

```bash
grokko session capture
```

Trigger an export, poll IMAP for the export email, and download the ZIP:

```bash
IMAP_USER=you@example.com IMAP_PASSWORD=app-password grokko export run
```

Show the latest chat transcript:

```bash
grokko chat --messages
```

Show a range of chat summaries by recency index:

```bash
grokko chat -n 3:10
```

The `START:STOP` form is half-open, so `3:10` means indices `3` through `9`.

Download all attachments from a conversation (uploaded files and generated images):

```bash
grokko chat --id <conversation-id> --attachments
```

Files are saved to `~/.grokko/attachments/<id>/` by default. Override with `--attachments-dir`:

```bash
grokko chat --id <conversation-id> --attachments --attachments-dir ./my-dir
```

Combine with `--messages` to download attachments and print the transcript in one go:

```bash
grokko chat --id <conversation-id> --attachments --messages
```

Search conversation titles and messages, printing matching URLs:

```bash
grokko search "python decorators"
```

Inspect the most recently downloaded ZIP:

```bash
grokko export inspect
```

Extract a Grok export ZIP to Obsidian Markdown notes:

```bash
grokko extract export.zip ./notes
```

Export only starred conversations:

```bash
grokko extract export.zip ./notes --starred
```

Export with attachments:

```bash
grokko extract export.zip ./notes --attachments all
```

See an overview of all CLI commands:

```bash
grokko overview
```

The CLI stores its working files in `~/.grokko` by default. Override that with
`GROKKO_STORAGE_DIR=/path/to/dir` if needed.

## Environment

Required for `grokko export run`:

```bash
IMAP_USER=you@example.com
IMAP_PASSWORD=app-password
```

Optional:

```bash
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
GROK_EXPORT_SUBJECT="Your data export is ready"
GROK_EXPORT_SENDER=
GROK_EXPORT_URL_PATTERN='https://accounts\.x\.ai/download/\?file_reference=[\w/-]+\.zip'
GROK_EXPORT_MAILBOX=INBOX
GROK_EXPORT_POLL_INTERVAL=30
GROK_EXPORT_POLL_TIMEOUT=600
GROKKO_STORAGE_DIR=~/.grokko
```

## Development

```bash
make test
make lint
make format
```

Install and run the pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## License

MIT
