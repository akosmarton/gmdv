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
  `read_source`, `render_markdown`, `build_page`/`error_page` (both take a palette
  dict), `PALETTE` (a static fallback palette), `START_PAGE`, and the width
  constants `WINDOW_WIDTH`/`WINDOW_HEIGHT`/`PAGE_WIDTH`.
- `GmdvApp(Adw.Application)`: window assembly in `do_activate` (idempotent — presents
  the existing window if one is up); render pipeline in
  `load_file`/`refresh`; file watching in `load_file`/`on_file_changed`; theme in
  `page_palette`/`on_dark_changed`/`apply_theme`/`set_bg`; file dialog in
  `on_open_clicked`/`on_open_finish`;
  drag-and-drop in `on_drop`; link navigation in `on_decide_policy`; back/forward in
  `go_back`/`go_forward`/`update_nav_buttons`; width mode in
  `on_width_toggled`/`apply_width`; file arguments via
  `Gio.ApplicationFlags.HANDLES_OPEN`/`NON_UNIQUE` in `__init__` and `do_open`; argv in
  `main`.

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
- The reading column is sized independently of the window: `WINDOW_WIDTH`/`WINDOW_HEIGHT`
  (960×1000) feed only `set_default_size`, while `PAGE_WIDTH` (900) feeds the `.page` rule
  (`box-sizing:border-box; max-width:{PAGE_WIDTH}px`). A fresh window therefore shows the
  900px column centred with 30px side margins and no horizontal scrolling (measured
  `docScrollWidth == innerWidth == 960`, page width 900, left offset 30). `border-box` keeps
  the 24px padding inside those 900px, leaving an 852px text column (~107 characters per
  line, measured 99-111). A wider window does not stretch the text: the column stays 900px
  and centres (measured: window 1500 → left offset 300).
- Do not express this in `ch`: `ch` is the width of `0` (10.09px at the 16px font) while
  prose averages ~8.08px per character, so `100ch` rendered 105-125 characters per line
  depending on window width. Measure, never guess: count characters per rendered line with
  the Range API, grouping characters by line top. Re-measure this way after changing the
  font stack, font size, padding or window size.
- Width mode lives in `self.full_width` and shows up as the `page` / `page full` class from
  `build_page`, so every render path agrees: file loads, error pages, theme changes, link
  navigation and back/forward. Pressing the header toggle only flips that class in the live
  document (`apply_width`, no re-render) so the scroll position survives; the next render
  picks the state up from `self.full_width`. In the default 960px window the two modes are
  distinct: normal is the 900px column with 30px side margins, full is 960px edge to edge
  (measured; window 1500 → normal 900px centred with 300px margins, full 1500px edge to
  edge, no horizontal scrolling in either).
- One `Gio.FileMonitor` per loaded file (cancel the previous one in `load_file`). Monitor
  events re-render directly, with no debounce; transient double renders on atomic saves
  are accepted. Deleted files render an error page.
- Theme: the page is painted from the live GTK/Adwaita named colors, read by
  `theme_palette(context, dark)` through the `THEME_COLORS` mapping
  (`bg`=`view_bg_color`, `fg`=`view_fg_color`, `border`=`borders`,
  `code_bg`=`window_bg_color`, `link`=`accent_color`; `muted` is the foreground at
  55% alpha). `PALETTE` is only the fallback for callers with no theme to read
  (headless tests). `Gtk.StyleContext.lookup_color` is deprecated since GTK 4.10
  but remains the only way to read named colors; its `DeprecationWarning` is
  suppressed locally. Tests drive the scheme with
  `set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)` / `FORCE_DARK`.
- Reading those colors from inside the `notify::dark` handler still returns the
  **previous** scheme — GTK revalidates the CSS only after the style manager has
  notified — so `on_dark_changed` defers the re-render by one main-loop turn
  (`GLib.idle_add(self.apply_theme)`). Re-rendering inline leaves the page one
  scheme change behind.
- WebKit 6.0 snapshots resolve to a `Gdk.Texture` (`texture.save_to_png(path)`), not a
  cairo surface.
- `read_source` decodes with `errors="replace"`: bad bytes must never raise.
- UI strings are English. No syntax highlighting and no `nl2br`; extensions are exactly
  `tables`, `fenced_code`, `sane_lists`.
- Instances are per launch (`NON_UNIQUE`): the app owns no bus name and never forwards,
  so opening a file from outside (file manager, `xdg-open`) starts a **fresh, focused
  window** instead of swapping the document inside a background instance (measured:
  launched through the desktop entry the new window is `is_active() == True`, and a
  running instance keeps its own file). `run(sys.argv)` lets GApplication parse the file
  argument and hands it to `do_open`; `load_file`'s `path != self.path` check keeps the
  history from growing on repeat opens. On a **cold** start with a file argument this
  GLib calls `do_open` *instead of* `do_activate` (neither is called first), so `do_open`
  builds the window itself — hence `do_activate` is idempotent (present and return if the
  window exists) and `do_open` falls back to `initial_path` + `do_activate()` when no
  window is up yet; an in-process `open()` with a window already up loads the file and
  raises it.
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
   `evaluate_javascript_finish(...).to_string()` to assert rendered DOM, theme colors
   (equal to `app.page_palette()`, also after a scheme switch), monitor reload,
   deletion handling and link clicks.
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
7. Install / file association: `desktop-file-validate data/io.github.akosmarton.gmdv.desktop`
   (exit 0, no output); `make install` → `~/.local/bin/gmdv` executable, desktop entry
   and icon under `~/.local/share`; `gio mime text/markdown` and
   `xdg-mime query default text/markdown` both report `io.github.akosmarton.gmdv.desktop`.
8. Multi-instance (the real "opens with gmdv" path): with one instance showing file A,
   `gio open fileB.md` must start a **second** process whose window shows B and is
   `is_active()`, while the first keeps showing A; `busctl --user list | grep gmdv`
   reports no bus name. Verify the launched window is active by pointing a throwaway
   desktop file's `Exec` at a probe script that logs `window.is_active()`.

## Rules

- Never commit, push, or open pull requests/issues without explicit approval for that
  exact action.
