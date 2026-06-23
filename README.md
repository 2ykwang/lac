![lac](docs/assets/banner.png)

# lac

[![PyPI](https://img.shields.io/pypi/v/lac-py.svg)](https://pypi.org/project/lac-py/)
[![Python](https://img.shields.io/pypi/pyversions/lac-py.svg)](https://pypi.org/project/lac-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/2ykwang/lac/actions/workflows/ci.yml/badge.svg)](https://github.com/2ykwang/lac/actions/workflows/ci.yml)

A CLI for managing AI agent config files (CLAUDE.md, AGENTS.md, .cursorrules, .mcp.json, …) without committing them to the repo.

```
  ~/repo/CLAUDE.md  ──→  ~/.local/share/lac/<repo>/CLAUDE.md
       (symlink)              (the actual file)
```

Files live outside the repo, are symlinked in, and excluded from git via `.git/info/exclude`. That directory is itself a git repo, so the same configs can be reused on another machine.

## Use cases

- AI configs that differ from team defaults.
- Personal tweaks that don't belong in shared history.
- Same configs across multiple machines.

## Install

```bash
# Homebrew
brew install 2ykwang/2ykwang/lac-py

# pipx
pipx install lac-py

lac --version
```

## Quick Start

In any git repo:

```bash
cd ~/projects/my-project

lac register
# ✓ registered

lac link --all
# ✓ CLAUDE.md linked
# ✓ AGENTS.md linked
# ✓ .claude linked
# ✓ .agents linked
# ✓ .cursorrules linked
# ✓ .mcp.json linked
```

Edit any of these files in your repo as usual — they're symlinks, so changes go to the stored copy too. To stop using lac in this repo, run `lac unregister`.

## How it works

Three pieces:

- **Symlinks** — each linked file in the repo is a symlink to its copy in lac's storage directory.
- **Git exclusion** — every linked filename is appended to `.git/info/exclude` between `# === lac:start ===` and `# === lac:end ===` markers. Git ignores them without touching `.gitignore`.
- **Repo identity** — each repo is matched by its git remote URL when available, otherwise by absolute path. The same repo on two machines maps to the same storage subdirectory.

### Default files

- CLAUDE.md
- AGENTS.md
- .claude/
- .agents/
- .cursorrules
- .mcp.json

Add others with `lac link <filename>`.

## Sync across machines

The storage directory (printed by `lac home`) is itself a git repo:

```bash
# on machine A — initial push
cd "$(lac home)"
git remote add origin <your-private-remote-url>
git add . && git commit -m "initial" && git push -u origin main

# on machine B — clone BEFORE any lac command runs on this machine
# (lac auto-creates the storage directory on first command, which would block git clone)
git clone <your-private-remote-url> ~/.local/share/lac
# or, if $LAC_HOME is set:
git clone <your-private-remote-url> "$LAC_HOME"

cd ~/projects/repo
lac register
lac link --all

# afterwards, on any machine: pull updates (fast-forward only, never pushes)
lac sync
```

## Commands

### Basic

| Command | What it does |
|---|---|
| `lac register` | Register the current repo with lac. |
| `lac link` | Interactive checkbox — pick which files to link. |
| `lac link --all` | Link all default files at once. |
| `lac link <file>` | Link a single file by name. |
| `lac status` | Show registration state of the current repo. |
| `lac unregister` | Restore files in the repo and back up this repo's storage subdirectory. |

### Diagnostic & management

| Command | What it does |
|---|---|
| `lac doctor` | Check for broken symlinks, orphaned entries, missing targets. |
| `lac list` | List all registered repos. |
| `lac home` | Print the storage directory. |
| `lac path [file]` | Print this repo's storage path (or a file inside it). |
| `lac rename <name>` | Rename this repo's storage subdirectory. |
| `lac sync` | Fast-forward the storage directory from its remote (pull-only; never pushes). |

## Limits

- macOS and Linux only. Windows is not supported.
- Python ≥3.11.
- Single-user. Sharing the storage directory between people isn't supported.
- Pull updates with `lac sync`; pushing is manual (`git push`) by design.

## License

MIT
