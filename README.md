# gmdv

A small GTK 4 markdown viewer that renders files in a GitHub-like styled view.

## Run

```sh
python3 gmdv.py [FILE.md]
```

## Features

- Rendered markdown view (headings, tables, fenced code blocks, blockquotes).
- Open a file via the header-bar button, drag-and-drop onto the window, or the CLI argument.
- Clicking a link to a local file renders that file in place (title bar and auto-reload follow it).
- Auto-reloads when the opened file changes on disk.
- Follows the system dark/light color scheme.

## Requirements

- GTK 4 with PyGObject (`python3-gobject`)
- libadwaita (`Adw` 1)
- WebKitGTK 6.0 (`WebKit` 6.0) bindings
- `python-markdown` (`pip install markdown`)
