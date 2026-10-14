# AGENTS.md

gmdv — a single-file GTK 4 markdown viewer (Python + PyGObject). `gmdv.py` is the
whole application; `README.md` is user-facing documentation.

## Environment

- Linux, GTK 4 + PyGObject, libadwaita (`Adw` 1), WebKitGTK 6.0, `python-markdown`.
- The target host has **no `gtk4` pkg-config / dev headers**: C, Meson or Rust builds
  are not possible here. Keep the Python-only stack; do not add a build step.
- Confirm bindings before assuming an API exists, e.g.
  `python3 -c "import gi; gi.require_version('WebKit','6.0'); from gi.repository import WebKit"`.

## Run

```sh
python3 gmdv.py [FILE.md]
```

## Layout

- Pure layer, module level, no GUI imports used — keep it headless-testable:
  `read_source`, `render_markdown`, `build_page`, `error_page`, `PALETTE`, `START_PAGE`.
- `GmdvApp(Adw.Application)`: window assembly in `do_activate` (idempotent — presents
  the existing window if one is up); render pipeline in
  `load_file`/`refresh`; file watching in `load_file`/`on_file_changed`; theme in
  `on_dark_changed`/`set_bg`; file dialog in `on_open_clicked`/`on_open_finish`;
  drag-and-drop in `on_drop`; link navigation in `on_decide_policy`; back/forward in
  `go_back`/`go_forward`/`update_nav_buttons`; width mode in
  `on_width_toggled`/`apply_width`; file arguments via
  `Gio.ApplicationFlags.HANDLES_OPEN` in `__init__` and `do_open`; argv in `main`.

## Invariants and gotchas

- The page is shown with `WebKit.WebView.load_html(html, uri)`. Pass the **file's own URI**
  (`document_uri()`), never its directory: relative images then resolve next to the file
  **and** in-page `#fragment` links resolve to the document. A directory base turns anchor
  clicks into navigations to the directory.
- `load_html` raises a `decide-policy` NAVIGATION_ACTION with `NavigationType.OTHER`;
  user link clicks arrive as `LINK_CLICKED`. Intercept only `LINK_CLICKED` `file://`
  navigations, call `decision.ignore()` and `load_file(path)` — without this, a link to
  another markdown file is displayed as raw text and the title/monitor stay stale.
  Intercepting every `file://` navigation also breaks `load_html` itself.
- Back/forward uses the app's own stack (`self.history` + `self.history_index`), **never**
  the WebView's history: every `load_html` adds a WebKit history entry, so WebKit's list
  would desync from the title bar and the file monitor. `load_file(path, push=True)`
  records an entry (dropping any forward entries), history moves load with `push=False`.
  Only push when the path actually changes, so re-clicking the same link does not grow the
  stack. `update_nav_buttons` derives both buttons' sensitivity from the index, and the
  actions `app.back`/`app.forward` carry the accelerators.
- The page column is sized to the default window: `WINDOW_WIDTH` (900) feeds both
  `set_default_size` and the `.page` rule (`box-sizing:border-box; max-width:{WINDOW_WIDTH}px`),
  so a fresh window is filled exactly — page 900px, left offset 0, no side margins, no
  horizontal scrolling (measured `docScrollWidth == innerWidth == 900`). `border-box` keeps
  the 24px padding inside those 900px, leaving an 852px text column (~107 characters per
  line, measured 99-111). A wider window does not stretch the text: the column stays 900px
  and centres.
- Do not express this in `ch`: `ch` is the width of `0` (10.09px at the 16px font) while
  prose averages ~8.08px per character, so `100ch` rendered 105-125 characters per line
  depending on window width. Measure, never guess: count characters per rendered line with
  the Range API, grouping characters by line top. Re-measure this way after changing the
  font stack, font size, padding or window size.
- Width mode lives in `self.full_width` and shows up as the `page` / `page full` class from
  `build_page`, so every render path agrees: file loads, error pages, theme changes, link
  navigation and back/forward. Pressing the header toggle only flips that class in the live
  document (`apply_width`, no re-render) so the scroll position survives; the next render
  picks the state up from `self.full_width`. Note the two modes are indistinguishable in
  the default 900px window — both fill it (measured: window 1500 → normal 900px column
  centred with 300px margins, full 1500px edge to edge, no horizontal scrolling in either).
- One `Gio.FileMonitor` per loaded file (cancel the previous one in `load_file`). Monitor
  events re-render directly, with no debounce; transient double renders on atomic saves
  are accepted. Deleted files render an error page.
- Theme follows `Adw.StyleManager.get_dark()`. Tests can drive it with
  `set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)` / `FORCE_DARK`.
- WebKit 6.0 snapshots resolve to a `Gdk.Texture` (`texture.save_to_png(path)`), not a
  cairo surface.
- `read_source` decodes with `errors="replace"`: bad bytes must never raise.
- UI strings are English. No syntax highlighting and no `nl2br`; extensions are exactly
  `tables`, `fenced_code`, `sane_lists`.
- The app holds the `io.github.akosmarton.Gmdv` bus name (`HANDLES_OPEN`). A second launch
  (CLI, file manager, `xdg-open`) must not parse argv itself but forward files through
  `run(sys.argv)` + `do_open`, which reuses `load_file`; the `path != self.path` check in
  `load_file` keeps the history from growing on repeat opens. On a **cold** start with a
  file argument, this GLib calls `do_open` *instead of* `do_activate` (neither is called
  first), so `do_open` must build the window itself — hence `do_activate` is idempotent
  (present and return if the window exists) and `do_open` falls back to
  `initial_path` + `do_activate()` when no window is up yet.

- Installed desktop entry: `make install` rewrites the repo copy's bare
  `Exec=gmdv %f` to the absolute `$(DESTBIN)/gmdv %f`. GIO does not load — and so
  GNOME Shell's app grid does not list, and cannot launch — a desktop entry whose
  `Exec` command is absent from `PATH`; a graphical session's `PATH` (measured:
  `/usr/lib64/ccache:/usr/local/bin:/usr/bin`) need not contain `~/.local/bin`.
  The repo `data/*.desktop` stays portable; only the installed copy is pinned.

## Verification

There is no test suite; verify with throwaway scripts and delete them afterwards.

1. Headless pure layer: `import gmdv` and assert on `render_markdown`, `build_page`
   (palette colors, `box-sizing:border-box` + `max-width:900px`), `error_page`
   (escaping of `<script>`), `read_source`
   (invalid UTF-8 replaced, no exception).
2. Runtime DOM probe (needs a display): build the app (`GmdvApp(path)`,
   `register(None)`, `activate()`), wait for the load, then
   `webview.evaluate_javascript(script, -1, None, None, None, cb)` and parse
   `evaluate_javascript_finish(...).to_string()` to assert rendered DOM, theme colors,
   monitor reload, deletion handling and link clicks.
3. Visual proof of the page: `webview.get_snapshot(WebKit.SnapshotRegion.FULL_DOCUMENT,
   WebKit.SnapshotOptions.NONE, None, cb)` then save the texture as PNG and look at it.
4. Visual proof of the whole window (header bar included, no X tooling needed):
   `Gtk.WidgetPaintable.new(window)` → `Gtk.Snapshot` → `Gsk.CairoRenderer.new().render_texture`
   → `texture.save_to_png`. ImageMagick's `import` fails on this host ("missing an image
   filename"), so do not rely on it.
5. UI state that is not pixel-visible (e.g. button sensitivity, accelerators) is asserted
   directly: `button.get_sensitive()`, `app.get_accels_for_action("app.back")`, and
   `app.activate_action("back", None)`; there is no key-injection tool (xdotool etc.) here,
   so accelerators themselves are verified as registrations, not as delivered keypresses.
6. Window smoke: `timeout 8 python3 gmdv.py /tmp/demo.md; echo $?` → expect `124`
   (window stayed up) with empty stderr.
7. Install / file association: `desktop-file-validate data/io.github.akosmarton.Gmdv.desktop`
   (exit 0, no output); `make install` → `~/.local/bin/gmdv` executable, desktop entry
   and icon under `~/.local/share`; `gio mime text/markdown` and
   `xdg-mime query default text/markdown` both report `io.github.akosmarton.Gmdv.desktop`.
8. Cross-process forwarding (the real "opens with gmdv" path): a primary holds the bus
   name showing file A, then `gio open fileB.md` must make the installed
   `~/.local/bin/gmdv` forward file B to the primary (webview renders B, title is B).
   Kill stray gmdv processes before each launch so the bus name is free.

## Rules

- Never commit, push, or open pull requests/issues without explicit approval for that
  exact action.
