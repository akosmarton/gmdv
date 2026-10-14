# gmdv

A small GTK 4 markdown viewer that renders files in a GitHub-like styled view.

## Run

```sh
python3 gmdv.py [FILE.md]
```

## Install

User-local (no root needed):

```sh
make install
```

System-wide:

```sh
sudo make install PREFIX=/usr/local
```

This registers gmdv as the default application for `text/markdown`, so `.md`
files open with it from the file manager. Remove with `make uninstall`
(and `sudo make uninstall PREFIX=/usr/local`).

## Features

- Rendered markdown view (headings, tables, fenced code blocks, blockquotes).
- Open a file via the header-bar button, drag-and-drop onto the window, or the CLI argument.
- Clicking a link to a local file renders that file in place (title bar and auto-reload follow it).
- Back/forward navigation across visited files, with header-bar buttons and
  `Ctrl+Left` / `Ctrl+Right` (also `Alt+b` / `Alt+f`).
- Header-bar toggle between the normal reading column (a fixed 900px, centred)
  and full-window width.
- Auto-reloads when the opened file changes on disk.
- Follows the system dark/light color scheme.
- Registered as the default handler for markdown files after `make install`,
  and a second opened file loads in the running window.

## Requirements

- GTK 4 with PyGObject (`python3-gobject`)
- libadwaita (`Adw` 1)
- WebKitGTK 6.0 (`WebKit` 6.0) bindings
- `python-markdown` (`pip install markdown`)

## License

MIT — see [LICENSE](LICENSE).
