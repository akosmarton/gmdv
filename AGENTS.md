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
- `GmdvApp(Adw.Application)`: window assembly in `do_activate`; render pipeline in
  `load_file`/`refresh`; file watching in `load_file`/`on_file_changed`; theme in
  `on_dark_changed`/`set_bg`; file dialog in `on_open_clicked`/`on_open_finish`;
  drag-and-drop in `on_drop`; link navigation in `on_decide_policy`; argv in `main`.

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

## Verification

There is no test suite; verify with throwaway scripts and delete them afterwards.

1. Headless pure layer: `import gmdv` and assert on `render_markdown`, `build_page`
   (palette colors, `max-width:48rem`), `error_page` (escaping of `<script>`), `read_source`
   (invalid UTF-8 replaced, no exception).
2. Runtime DOM probe (needs a display): build the app (`GmdvApp(path)`,
   `register(None)`, `activate()`), wait for the load, then
   `webview.evaluate_javascript(script, -1, None, None, None, cb)` and parse
   `evaluate_javascript_finish(...).to_string()` to assert rendered DOM, theme colors,
   monitor reload, deletion handling and link clicks.
3. Visual proof: `webview.get_snapshot(WebKit.SnapshotRegion.FULL_DOCUMENT,
   WebKit.SnapshotOptions.NONE, None, cb)` then save the texture as PNG and look at it.
4. Window smoke: `timeout 8 python3 gmdv.py /tmp/demo.md; echo $?` → expect `124`
   (window stayed up) with empty stderr.

## Rules

- Never commit, push, or open pull requests/issues without explicit approval for that
  exact action.
