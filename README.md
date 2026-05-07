# Apedi

A fast, simple text editor with syntax highlighting, code formatting,
project tree, integrated terminal, and a clean modern GTK 4 interface.

## Features

- Multi-tab, multi-window editor built on GTK 4 + GtkSourceView 5
- Syntax highlighting for ~150 languages
- One-shortcut code formatting (`Ctrl+Shift+I`) — bundled `black`,
  `prettier`, `gofmt`, `rustfmt`, `clang-format`, `shfmt`
- Multi-project sidebar with `.gitignore` awareness, per-extension
  icons + colors, single-click open, auto-reveal of the active tab
- Quick Open (`Ctrl+P`) — fuzzy file picker across all open projects
- Find in Files (`Ctrl+Shift+F`) — workspace-wide text search
- Go to Symbol in file (`Ctrl+M`) — Python / JS / TS / Rust / Go /
  Java / C / C++ / Ruby / shell
- Integrated terminal (`Ctrl+\``) — VTE with bundled `bash` and `zsh`
- Auto-detect dark / light theme from the desktop preference, or pick
  one from Preferences
- Search, replace (`Ctrl+R`), goto line (`Ctrl+G`)
- Recent files menu, drag & drop
- Optional autosave (after delay or on focus loss)
- Crash recovery — drafts persist to `~/.cache/apedi/drafts/`
- File watcher — external changes trigger a reload (or warn if dirty)
- Localized UI (English, Polski; `gettext`-based, more translations
  welcome)
- Snippets (`def`, `cls`, `ifmain`, `console.log`, `html5`, `pkgmain`, …)
- Tabbed Preferences (Appearance / Editor / Files / Sidebar / System)
- What's New dialog on first launch of a new version

## Install

From the Ubuntu App Center or the Snap Store:

```
snap install apedi
```

Or sideload a local build:

```
sudo snap install --dangerous ./apedi_*.snap
```

## Keyboard cheat-sheet

| Shortcut             | Action                          |
| -------------------- | ------------------------------- |
| `Ctrl+T`             | New tab                         |
| `Ctrl+N`             | New window                      |
| `Ctrl+O`             | Open file                       |
| `Ctrl+Shift+O`       | Open / add project              |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As             |
| `Ctrl+W`             | Close tab (also middle-click)   |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab    |
| `Ctrl+F`             | Find                            |
| `Ctrl+R`             | Replace                         |
| `Ctrl+G`             | Goto line                       |
| `Ctrl+M`             | Goto symbol in file             |
| `Ctrl+P`             | Quick Open file                 |
| `Ctrl+Shift+F`       | Find in Files                   |
| `Ctrl+Shift+I`       | Format current file             |
| `Ctrl+,`             | Preferences                     |
| `Ctrl+Shift+D`       | Cycle theme (auto / light / dark) |
| `F9`                 | Toggle sidebar                  |
| `` Ctrl+` ``         | Toggle terminal                 |
| `Ctrl+Q`             | Quit                            |

## Develop

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-gtksource-5 \
    gir1.2-vte-3.91 \
    black clang-format shfmt golang-go rustfmt prettier
pip install -e .
python -m apedi
```

## Build snap

LXD must be initialized; iptables rules may need to allow the LXD
bridge if Docker is also installed.

```
snapcraft
```

## Run tests

```
pip install -e ".[test]"
pytest -q
```

## License

MIT — see `LICENSE`.
