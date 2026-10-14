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
- In-page search: `Ctrl+F` or the header magnifier — case-insensitive, wraps
  around, with a match counter.
- Outline sidebar: the header toggle or `F9` lists the document's headings;
  click one to scroll to it, and drag the divider to widen or narrow the
  sidebar.
- Auto-reloads when the opened file changes on disk.
- Uses the system GTK/Adwaita theme colors, following the light/dark scheme.
- Registered as the default handler for markdown files after `make install`; each
  opened file gets its own window (multiple instances are allowed).

## Requirements

| Component | Minimum gmdv needs | Verified against | Install |
| --- | --- | --- | --- |
| GTK 4 | 4.10 (`Gtk.FileDialog`) | 4.22.5 | `gtk4` |
| PyGObject | any release that loads the typelibs | 3.56.3 | `python3-gobject` |
| libadwaita (`Adw` 1) | 1.4 (`Adw.OverlaySplitView`) | 1.9.4 | `libadwaita` |
| WebKitGTK (`WebKit` 6.0) | 2.40, the first release of the 6.0 API | 2.54.1 | `webkitgtk6.0` |
| python-markdown | 3.0 | 3.10.3 | `python3-markdown`, or `pip install -r requirements.txt` |

gmdv pins the API generation of the GUI stack at import time
(`gi.require_version`: Gtk 4.0, Adw 1, WebKit 6.0) — more is not possible for a
distribution package, since PyGObject is published on PyPI as a source tarball
only. The releases inside that generation are checked at startup instead: gmdv
exits with a report when GTK, libadwaita, WebKitGTK or python-markdown is older
than the minimum above, and prints every loaded version, rather than crashing on
a missing API or rendering with an untested markdown release. The markdown
renderer is additionally pinned in `requirements.txt` to the version above.

## License

MIT — see [LICENSE](LICENSE).
