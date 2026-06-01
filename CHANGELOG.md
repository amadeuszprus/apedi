# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.8] - 2026-06-01

### Changed
- **Startup performance.** Snap install shrinks from ~1.1 GB to ~580 MB
  and cold launches noticeably faster (snap mount + AppArmor profile load
  scale with snap size). Internal changes:
  - WebKit removed: markdown preview now renders via Pango on a
    `GtkLabel` instead of a `WebKit.WebView`. Tables render as a
    monospace block with aligned columns; images become clickable
    `[🖼 file]` placeholders (open in the system viewer). Links,
    headings, lists, blockquotes, inline/block code and horizontal
    rules render the same as before.
  - Go SDK (~210 MB) replaced with just the `gofmt` binary bundled
    from the upstream tarball.
  - LLVM toolchain (~175 MB) excluded from the snap. If `clang-format`
    breaks on your system, please file an issue — this is the riskiest
    cut and can be reverted.
  - System locales pruned to en / en_US / pl (Apedi's own translations
    are unaffected).
- **Lazier imports.** `python-markdown` is no longer pulled in unless
  you actually open a markdown file. `EditorWindow` is imported on
  first window creation, not at app module load time. Terminal panel
  (Vte + shell startup) is deferred to a `GLib.idle_add` after the
  window is shown.
- **Fast `--version`.** The CLI gained `apedi --version` / `apedi -V`,
  which short-circuits before importing GTK so it returns in ~10 ms.

## [0.7.7] - 2026-05-14

### Added
- **Markdown preview.** Opening a `.md` / `.markdown` / `.mdown` / `.mkd` /
  `.mkdn` file (or any buffer detected as markdown by GtkSourceView) splits
  the tab in two: source editor on the left, a live rendered preview on the
  right. The preview re-renders ~250 ms after the last keystroke. Headings,
  lists, fenced code blocks, tables, blockquotes, inline code and links are
  styled to follow the active light/dark theme.
- **Toggle Markdown Preview** action (`Ctrl+Shift+M`, View menu entry).
  Works on any tab regardless of file type — handy for `.txt` files
  containing markdown.
- **Preferences → Editor → Markdown preview (auto-open for .md)** switch.
  Off disables the automatic split when opening a markdown file; the
  manual toggle still works.
- Link clicks inside the preview open external URLs in the system browser,
  `file://` links to existing files open as a new tab in Apedi, and
  in-document anchors jump within the preview.
- Snap bundles `webkitgtk-6.0` so the preview works under strict
  confinement out of the box.

## [0.7.6] - 2026-05-10

### Changed
- Find/Replace in Files window is now modal over the editor and
  no longer resizable. WMs reliably center transient + modal
  windows, and the broken maximize button (which the WM would
  show for resizable windows but couldn't apply to a snap-confined
  transient) is gone. `Esc` closes the dialog.

### Added
- **Pre-fill search from selection.** When text is selected in
  the active tab, triggering Find (`Ctrl+F`), Replace (`Ctrl+R`),
  Find in Files (`Ctrl+Shift+F`), or any sidebar context-menu
  Find/Replace puts the selection straight into the search input
  (single-line selections up to 256 characters; multi-line
  selections are ignored).

## [0.7.5] - 2026-05-10

### Fixed
- *New File…* and *New Folder…* in the sidebar context menu
  crashed with `TypeError: 'tuple' object is not callable`. Every
  action callback in `EditorWindow` declared its variadic argument
  as `*_: object`, which shadowed the gettext alias `_` inside the
  method. As soon as the body called `_("…")` for an i18n string,
  Python looked up the local tuple instead of the function.
  Renamed the parameter to `*_args: object` everywhere — same
  "ignored arg" hint, no shadow.
- Input prompt window (used by *New File* / *New Folder*) now
  declares itself non-resizable and ships a real default height,
  so the WM treats it as a dialog and centers it over the editor
  rather than dropping it at a default top-left position.

## [0.7.4] - 2026-05-10

### Fixed
- Sidebar right-click menu items (New File, New Folder, Find,
  Replace, Replace with) did nothing when activated. The popover
  was a `Gtk.PopoverMenu` driven by `Gio.Menu` + `win.*` actions;
  GTK4's action muxer didn't resolve those actions reliably for a
  popover parented inside a `Gtk.ListView` factory cell. The
  popover is now a plain `Gtk.Popover` with buttons that call
  through directly. Keyboard shortcuts (Ctrl+Alt+N etc.) keep
  using the actions and continue to work.

## [0.7.3] - 2026-05-09

### Added
- **Sidebar collapse button** in the header bar (next to the
  hamburger menu) — same action as `F9` / View → Toggle Sidebar.
- **Multiple terminals.** The terminal panel now hosts a notebook
  of terminal tabs. New "+" button in the panel header (and
  `Ctrl+Shift+\``) opens another shell; each tab has its own close
  button and middle-click closes it. Tabs are reorderable and a
  tab is removed automatically when its shell exits.
- **Sidebar right-click context menu** with five entries:
  *New File…*, *New Folder…*, *Find in File/Folder…*,
  *Replace in File/Folder…*, and *Replace with…* — all scoped to
  the clicked path. Long-press works the same on touch.
- **Replace in Files** mode for the search dialog. Adds a
  "Replace with" input and a *Replace All* button (with a
  confirmation prompt) that rewrites matches on disk.
- **New keyboard shortcuts**:
  - `Ctrl+Shift+\`` — new terminal
  - `Ctrl+Alt+N` — new file in selected folder
  - `Ctrl+Alt+Shift+N` — new folder in selected folder
  - `Ctrl+Alt+F` — find scoped to selected sidebar node
  - `Ctrl+Alt+H` — replace scoped to selected sidebar node

## [0.7.2] - 2026-05-07

### Fixed
- What's New dialog now actually renders the CHANGELOG sections.
  The renderer was missing handlers for `**bold**` spans, `##`
  second-level headings, and Markdown bullet lists — sections
  came through with raw `*`, `-` and `**` characters. Lists now
  render with a real `•` glyph and indentation; bold and inline
  `code` are styled.

## [0.7.1] - 2026-05-07

### Changed
- Header bar reshuffled. Hamburger menu sits at the far left, the
  toolbar buttons (new tab / open / save / format) follow, and a ☕
  button at the far right opens buycoffee.to/aprus.
- Compact sidebar is now the default density. Toggle in
  Preferences → Sidebar if you prefer the comfortable spacing.

### Added
- **Keyboard Shortcuts window** (`Ctrl+?` / `F1` / Help → Keyboard
  Shortcuts) — `Gtk.ShortcutsWindow` listing every binding grouped
  by File / Navigation / Edit & search / View.

### Fixed
- Quick Open and Find in Files now fall back to the parent
  directories of the open tabs when no project is loaded — they
  used to print "needs an open project" and refuse to open.
- Terminal correctly picks up the user's `zsh`. The candidate order
  was wrong: apt's zsh installs to `$SNAP/bin/zsh`, not
  `$SNAP/usr/bin/zsh`, so the previous resolver fell through to
  bash. Resolver now also reads `/etc/passwd` if `$SHELL` is empty
  (this happens for some desktop launches).

## [0.7.0] - 2026-05-07

### Added
- **Buy me a coffee** link in the app menu and as a credit row in the
  About dialog — `https://buycoffee.to/aprus`. The action launches the
  link via `Gtk.UriLauncher` (or `Gio.AppInfo` as a fallback).
- **Quick Open** (`Ctrl+P`) — fuzzy file picker across every open
  project. Skips heavy folders and gitignored entries by the same
  rules the sidebar uses. Up/Down + Enter, single-click, or Escape
  to cancel.
- **Find in Files** (`Ctrl+Shift+F`) — workspace-wide text search
  with regex and case-sensitivity toggles. Walks every open project,
  skips ignored entries, files larger than 2 MB and binary blobs.
  Each hit is one row; clicking it opens the file at the matching
  line.
- **About dialog** under the menu and the `app.about` action — name,
  version, license, link to the source repo.
- **Crash recovery.** Edited buffers are mirrored to
  `~/.cache/apedi/drafts/` (or `$SNAP_USER_COMMON/drafts/` inside the
  snap) on every keystroke. On startup, if any draft differs from
  the on-disk file, it is restored as a modified tab.
- **External-change watcher.** A `Gio.FileMonitor` per open buffer
  detects out-of-process edits. If the buffer is clean, Apedi
  silently reloads; if dirty, the status bar warns instead of
  losing work.
- **Snippets** — a small bundled set (`def`, `cls`, `dc`, `ifmain`,
  `cl`, `fn`, `html5`, `pkgmain`, `for`) loaded by GtkSourceView's
  `SnippetManager`. Type the trigger and press Tab.

### Changed
- Snap metadata expanded for the Ubuntu App Center listing — fuller
  description, `categories: [development, utilities]`,
  `developer_name`, `<categories>`/`<screenshots>` in the AppStream
  metainfo, and a back-dated `<releases>` history.
- README rewritten with the keyboard cheat-sheet and the development
  / build / test workflow.

## [0.6.0] - 2026-05-06

### Added
- **Multiple open projects.** The sidebar can hold any number of
  projects at once; each one is its own expandable section in the
  tree. Opening a file outside every existing project adds its git
  root (or parent directory) as a new project, instead of replacing
  the current one. Switching tabs reveals the file in whichever
  project it belongs to.
- The plus button in the sidebar header (next to the "Projects"
  title) opens another project. The window-close icon next to a
  project name removes that project from the sidebar.
- Settings now persist `projects` (list of paths). Old single
  `last_project` configs are migrated automatically on first load.

## [0.5.2] - 2026-05-06

### Added
- When a file is opened from outside the current project (or with no
  project loaded), the sidebar now switches to that file's nearest
  git root, walking up to 20 levels for a `.git` directory. If
  none is found, the file's parent directory becomes the project
  root. The sidebar auto-shows itself, the new root is persisted to
  settings, and the file is revealed in the tree.

## [0.5.1] - 2026-05-06

### Changed
- Massively expanded the `.desktop` file's `MimeType` list. The
  short v0.1 list (`text/plain` plus a handful of langs) meant Apedi
  did not show up in the file manager's "Open with" menu for things
  like TOML, SQL, Makefile, Dockerfile, CMake, Lua, Kotlin, Swift,
  Dart, Perl, R, INI/properties, CSV, diffs, or the `application/
  x-zerosize` mime type that GNOME assigns to empty files.

## [0.5.0] - 2026-05-06

### Added
- **Tabbed Preferences.** The single-grid form was getting unwieldy.
  Settings are now grouped into Appearance / Editor / Files / Sidebar
  / System pages.
- **Internationalization.** Apedi can now run in Polish. The user
  visible strings (menu items, dialog titles, page headers, sidebar
  placeholders) go through `gettext`. The language picker on the
  System page lets you choose `System default`, `English`, or
  `Polski`. Bundled `.mo` files for `pl` are compiled at snap build
  time from `data/po/pl.po`. Restart required after switching.
- **Autosave** with three modes: `Off` (default), `After delay`
  (writes the buffer N ms after the last keystroke), and
  `On focus loss` (writes when the window stops being the active
  window). Only saves buffers that already have a file path —
  Untitled tabs are left alone. The delay is configurable in
  Preferences (250 ms – 60 s).
- Toggle in Preferences — **Show in file manager 'Open with' menu**.
  Apedi has always shipped a desktop entry with a wide MimeType list,
  so it should appear in Nautilus / Dolphin / Thunar's right-click
  "Open with" menu by default. Disabling the switch writes a
  `NoDisplay=true` override to `~/.local/share/applications/`,
  hiding Apedi from launchers and "Open with" lists. Re-enabling
  removes the override.

## [0.4.0] - 2026-05-06

### Added
- **Gitignore-aware sidebar.** Files and folders matched by the
  project's `.gitignore`, by user-defined patterns, or by the built-in
  heavy-folder list (`node_modules`, `__pycache__`, `target`, `dist`,
  `build`, `.venv`, `.tox`, `.idea`, …) are dimmed in the tree. The
  built-in heavy folders are never auto-expanded; click them once to
  open. The hidden `.git` directory is omitted entirely.
- **Custom ignore patterns** in Preferences (comma-separated, gitignore
  syntax). They live alongside the project's own `.gitignore`.
- **Compact sidebar** mode in Preferences — tighter row spacing and
  slightly smaller font for projects with many files.
- **Go to Symbol** (`Ctrl+M`). Pops a searchable list of classes,
  functions, methods, traits/structs/enums in the current file.
  Python uses the standard `ast` parser; JavaScript / TypeScript /
  Rust / Go / Java / C / C++ / Ruby / shell use language-specific
  regex extractors. Up/Down to move, Enter / single-click to jump.

### Deferred
- `Ctrl+hover` cross-file go-to-definition needs either an LSP client
  or a ctags-based workspace index. Punted to 0.5.0 — it is a separate
  larger project (LSP transport, document-symbol caching, hover
  protocol, click target rendering).

## [0.3.2] - 2026-05-05

### Added
- Middle-click on a tab closes it, no need to aim for the close icon.
- Single click in the project sidebar opens a file (or expands a
  folder) — no more double-click.
- The sidebar follows the active tab: switching to a tab whose file
  lives inside the open project expands the parent folders, scrolls
  the file into view, and selects its row.
- Files in the sidebar now use freedesktop content-type icons (per
  extension, picked from the GNOME icon theme) and are colored by
  language family — Python blue, JavaScript yellow, Rust orange, Go
  cyan, Markdown grey, JSON/YAML/TOML green, etc.

### Changed
- Terminal now bundles `bash` and `zsh` from `core24` and prefers the
  user's `$SHELL` (resolved by basename inside the snap mount). Strict
  confinement blocks exec of host binaries like `/usr/bin/zsh`, so it
  has to be packaged in.

## [0.3.1] - 2026-05-05

### Added
- **Integrated terminal** (`Ctrl+`` ` ``). VTE-based terminal panel
  docks below the editor. Toggle from View → Toggle Terminal or
  the keyboard shortcut. Spawns the user's `$SHELL` (falls back to
  `/bin/bash` then `/bin/sh`). The terminal starts in the open
  project's directory, if any.

### Fixed
- The What's New dialog never appeared because `do_activate` is not
  called when `Gio.Application` runs through `do_command_line`
  (which is what `apedi <file>` triggers). The hook now also fires
  from the command-line entry path.
- Errors raised in `_maybe_show_whats_new` were swallowed silently by
  GLib's idle queue. Wrapped in a `log.exception` so the next failure
  surfaces in the logs.

## [0.3.0] - 2026-05-05

### Added
- **What's New** dialog. Pops up automatically the first time a new
  version of Apedi runs and shows the matching CHANGELOG section.
  Renders bullets, `### headings`, and `inline code` with light
  formatting.
- **Open Project** (`Ctrl+Shift+O`) — pick a folder and a project
  sidebar appears with the directory tree. Clicking a file opens it
  in a new tab. Folders expand inline. The last opened project is
  remembered between sessions.
- **Project sidebar** can be toggled with `F9` or via View → Toggle
  Sidebar. There's also a switch in Preferences to keep it on by
  default. The sidebar is hidden until you Open Project the first
  time.

### Changed
- Replace shortcut moved from `Ctrl+H` to `Ctrl+R`. The replace toolbar
  remains in the same search bar (it just stays hidden until you ask
  for replace).

## [0.2.3] - 2026-05-05

### Fixed
- Preferences dialog crashed at construction because `_grid` was
  assigned after `_add_row()` was first called. The dialog never made
  it past `__init__` and the menu item appeared inert.

### Added
- Theme can be set to `auto`, `light`, or `dark`. `auto` (default)
  consults `xdg-desktop-portal`'s `org.freedesktop.appearance`/
  `color-scheme` setting, so apedi follows the GNOME / KDE / portal
  preference out of the box.
- `Ctrl+Shift+D` cycles `auto → light → dark → auto`.

### Changed
- `Settings.dark_ui` is now a string (`auto`/`light`/`dark`). Old
  configs with the boolean field are migrated on first load.

## [0.2.2] - 2026-05-05

### Fixed
- Reverted the GTK4/Pango/Cairo/HarfBuzz prime exclusions from 0.2.1.
  Removing those caused `gnome-46-2404`'s `libharfbuzz-subset.so.0` to
  fail at runtime (`undefined symbol: hb_free`), which crashed the app
  before the first window. Only the four libraries the linter has
  consistently flagged unused (`libcolordprivate`, `libdconf`,
  `libicuio`, `libicutest`) stay excluded.

## [0.2.1] - 2026-05-05

### Performance
- Lazy-imported `apedi.formatters` and `apedi.preferences` — neither
  is needed before the user invokes Format / Preferences.

### Broken
- Snap prime exclusions were too aggressive and broke the
  `libharfbuzz-subset` ABI provided by the gnome platform extension.
  Fixed in 0.2.2.

## [0.2.0] - 2026-05-05

### Added
- Preferences dialog (`Ctrl+,`) — color scheme, font, tab width, indent
  with spaces, line wrap, line numbers, auto-indent, trim-trailing-whitespace,
  and dark window chrome. Changes apply live to all open windows.
- Dark mode toggle (`Ctrl+Shift+D`) — switches between an `Adwaita` /
  `Adwaita-dark` style scheme and flips `gtk-application-prefer-dark-theme`.
- Open Recent submenu under File, kept in sync across windows.

### Changed
- `black` is now bundled via pip in the snap. The apt-installed
  `/usr/bin/black` script could not locate its module under the
  gnome-platform Python.
- `formatters-prettier` snap part is plain `nil` plugin downloading the
  Node.js tarball directly. The npm plugin's default action requires a
  `package.json` in the source root, which Apedi has not.

### Fixed
- `Save As` no longer rewrites `tab.buffer.path` before confirming the
  on-disk write succeeded.
- Buffer language change now triggers the status-bar update via the
  standard `notify::language` GObject signal (previously a non-existent
  `language-changed` signal name was used and caused the editor to abort
  on the first tab open).
- Snap can now register its DBus session name `pl.aprus.apedi` via an
  explicit `dbus` slot. Without it, `Gio.Application` failed to start
  under AppArmor confinement.

### Snapcraft
- Pinned the LXD base instance's apt sources to `mirror.netcologne.de` to
  work around a flaky route from this network to `archive.ubuntu.com`.

## [0.1.0] - 2026-05-04

### Added
- Initial release. GTK 4 / GtkSourceView 5 editor with multi-tab,
  multi-window, syntax highlighting for ~150 languages, search/replace,
  goto-line, drag-and-drop, recent files persistence.
- Code formatting via bundled `black`, `prettier`, `gofmt`, `rustfmt`,
  `clang-format`, `shfmt`. Triggered by `Ctrl+Shift+I`.
- Snap packaging targeting Ubuntu 24.04 (`core24`, strict confinement,
  gnome extension).
