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
  `read_source`, `render` (returns `(body_html, outline)`, the outline being the
  `(level, name, id)` tuples the sidebar is built from, with the names unescaped
  to plain text), `build_page`/`error_page` (both take a palette
  dict), `PALETTE` (a static fallback palette), `START_PAGE`, the dependency
  helpers `dotted`/`version_tuple`/`meets`/`gui_stack`/`loaded_report`/
  `dependency_error`, and the width constants
  `WINDOW_WIDTH`/`WINDOW_HEIGHT`/`PAGE_WIDTH`/`OUTLINE_COLLAPSE_WIDTH`.
- `GmdvApp(Adw.Application)`: window assembly in `do_activate` (idempotent — presents
  the existing window if one is up); render pipeline in
  `load_file`/`refresh`; file watching in `load_file`/`on_file_changed`; theme in
  `page_palette`/`on_dark_changed`/`apply_theme`/`set_bg`; file dialog in
  `on_open_clicked`/`on_open_finish`;
  drag-and-drop in `on_drop`; link navigation in `on_decide_policy`; back/forward in
  `go_back`/`go_forward`/`update_nav_buttons`; width mode in
  `on_width_toggled`/`apply_width`; outline sidebar in
  `toggle_outline`/`on_outline_toggled`/`set_outline`/`on_outline_row`; in-page find in
  `toggle_find`/`set_search_visible`/`clear_find_highlight`/`run_search`/
  `on_search_changed`/`on_counted_matches`/`on_search_failed`/`on_load_changed`;
  file arguments via
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
  and centres (measured: window 1500 → left offset 300). While the outline sidebar is shown
  the 900px is only a maximum: the page takes the slot the sidebar leaves (measured, 960px
  window with the sidebar inline at its default quarter: sidebar 240px, page 720px,
  `innerWidth == docScrollWidth == 720`, still no horizontal scrolling). The sidebar's
  width is draggable (see the outline divider bullet), so this is the default, not a fixed
  number.
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
  `tables`, `fenced_code`, `sane_lists`, `toc` — `toc` only adds `id` attributes to the
  rendered headings (the outline's anchors, unique per document: duplicates become
  `api`, `api_1`); it changes no visible output.
- Dependency versions: `gi.require_version` pins the API generation of the GUI stack
  (Gtk 4.0, Adw 1, WebKit 6.0), which is all a distribution package can be pinned to —
  PyGObject has no PyPI wheels. The releases inside that generation are enforced in
  `main()` by `dependency_error()`: `MIN_GTK` (4.10, `Gtk.FileDialog`), `MIN_ADW`
  (1.4, `Adw.OverlaySplitView`), `MIN_WEBKIT` (2.40, the 6.0 API) and `MIN_MARKDOWN`
  (3.0). It exits 1 with one line per offending library and a `loaded_report()` line
  naming every loaded version; a missing or unparseable version is unknown, never a
  failure. Only python-markdown is a pip dependency, so only it is pinned exactly
  (`requirements.txt`,
  `VERIFIED_MARKDOWN`); PyGObject and the interpreter are reported but not floored,
  nothing gmdv calls being gated on their release. Lower a floor only against the API
  actually used, and keep README's table in step.
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
- In-page find (`Ctrl+F` / the header magnifier) is a `WebKit.FindController` driven
  from a `Gtk.SearchEntry` inside a `Gtk.Revealer` stacked above the web view in
  `self.find_bar`; the web view needs `set_vexpand(True)` there, since a box hands
  out only natural height and a web view has none (without it the page gets 0px and
  nothing is visible). Only `counted-matches` and `failed-to-find-text` exist on
  this build — connecting `found`/`not-found` raises "unknown signal name", never
  reference them. `count_matches` needs a real cap (`FIND_MAX_MATCHES`): `max=0`,
  or a `max` below the real count, reports UINT32_MAX — hence a count
  `>= FIND_MAX_MATCHES` renders as "1000+ matches"; counting does not cancel a
  running `search`. Never call `search("")`: it emits `failed-to-find-text` and
  drops the query, so empty input goes through `search_finish()`. Beyond the yellow
  find highlight, WebKit also leaves its **selection** on the current match, which
  still paints as a tinted range, so `search_finish()` alone does not clear what
  the user sees: `clear_find_highlight()` also drops the selection ranges (measured:
  after it, closing the bar renders the window pixel-identical to never having
  searched). `search_finish()` likewise leaves `get_search_text()` populated —
  never assert find state through that accessor; the found range *is* a DOM
  selection, so `getSelection().getRangeAt(0).startOffset` is the exact probe for
  the current match, and `find_entry.has_focus()` is always False because a
  `Gtk.Entry`'s focus leaf is its internal `GtkText` (walk `window.get_focus()`
  instead). `load_html` clears WebKit's find state, so `on_load_changed` re-runs an
  open search on `LoadEvent.FINISHED` — the counter then follows monitor reloads,
  link navigation and back/forward. The entry keeps its query across closing
  (reopening reselects and re-runs it), and `set_search_visible` is the single path
  for the toggle and Escape (`stop-search`).
- The window is `GmdvWindow(Gtk.ApplicationWindow)`, whose child is an
  `Adw.OverlaySplitView` (`self.split`): its sidebar is a horizontal `Gtk.Box`
  of a `Gtk.ScrolledWindow` around a `Gtk.ListBox` of rows built by `set_outline`
  from `render`'s outline, plus the 8px `self.outline_handle` grab strip and the
  1px `Gtk.Separator` after it (the visible divider, see below); its content is
  the old `self.find_bar` (revealer + web view).
  Every `load_html` site calls `set_outline` first — the page and the sidebar can
  never disagree — with `()` for the start page, error pages and a deleted file.
  Rows store their heading id on `row.anchor` and click-to-scroll is
  `getElementById(anchor).scrollIntoView({behavior:'smooth'})` in the live
  document, so no re-render (and no scroll reset) is involved. The row text is a
  plain `Gtk.Label`, so `render` hands back **unescaped** names: the `toc`
  extension keeps the heading's HTML entities (`## Feeder & Nozzle` →
  `'Feeder &amp; Nozzle'`, `## 1 &lt; 2` → `'1 &lt; 2'`), which the label would
  otherwise print literally (the page is fine because the browser unescapes them).
  Inline markup and raw HTML drop out of the names on the way, so a heading written
  as raw `<Common Data>` (not entity-escaped) reads `3. button` in the outline
  while the page shows the tag as text. Collapse: below
  `OUTLINE_COLLAPSE_WIDTH` (600) the sidebar overlays the content, at or above it
  sits beside it. `Adw.Breakpoint` was the obvious driver but needs an `Adw.Bin`
  window, and `Adw.OverlaySplitView` is final (not subclassable), while GTK 4 has
  **no** `size-allocate` signal (connect raises `unknown signal name`) and
  `Gtk.Widget:width` never notifies — so `GmdvWindow.do_size_allocate` sets
  `collapsed` from the allocation it is handed (measured: 960 → `False`, 500 →
  `True`, shrink at runtime → `True`). The sidebar starts hidden
  (`self.outline_visible`), so the default window still shows the plain 900px
  column and the measurements above are unchanged; toggling only sets the widget's
  show state, so page scroll and outline survive navigation and monitor reloads.
  `sidebar-hide-symbolic` is **not** in the installed icon theme (only
  `sidebar-show-symbolic` is), so the toggle keeps that one icon and the tooltip
  ("Outline (F9)" / "Hide outline (F9)") carries the state.
- The sidebar width is dragged on `self.outline_handle`, a `Gtk.GestureDrag` on
  the divider strip (cursor `col-resize`). The strip is 8px of **invisible** grab
  area; the visible line is a `Gtk.Separator` placed *after* it, i.e. as the
  sidebar slot's last pixel, so the divider is exactly the line where the page
  starts. Do not put the separator inside the strip: a `GtkBox` lays a 1px
  `Gtk.Separator` out against the strip's leading edge (alignment is not honoured
  there), which leaves 8px of sidebar colour between the line and the page —
  measured on the user's 1.4×-scaled screenshot as a divider ~11px wide (one
  brighter line, then sidebar colour) — and reads as a thick divider. Verified
  pixel by pixel here: sidebar colour up to `width-2`, one line pixel at
  `width-1` (63,63,67 against a (46,46,50) sidebar and a (29,29,32) page), page
  colour from `width` on. The handler reads the pointer from
  `gesture.get_last_event().get_position()`, i.e. in **surface** coordinates:
  `get_offset`/`get_point` report the pointer in the attached widget's space and
  the handle travels with the edge it drags, so those offsets cancel out exactly
  the movement being dragged (the sidebar would stall). `set_outline_width` then
  sets `max-sidebar-width` to the dragged pixels and `sidebar-width-fraction` to
  the share it had, clamped to `OUTLINE_WIDTH_MIN`..`OUTLINE_WIDTH_MAX` (180..640)
  and to the split view's own width. Both properties exist since libadwaita 1.4,
  the same release `Adw.OverlaySplitView` needs, so the floor does not move.
  Measured: inline the width is `clamp(share × window, 180, dragged)`, so a wider
  window keeps the dragged width (400 @960 → 400 @1200 → still 400 @1600) while a
  narrower one scales it down (400/960 → 360 @800); collapsed, libadwaita sizes
  the overlay as `clamp(window width, 180, dragged)` (a 500px window with a 540px
  drag shows a full-window overlay, and dragging there sets the cap, e.g. 400).
  The width lives only in the split view's properties, so it survives hiding,
  navigation and monitor reloads; nothing is persisted across launches.
  `Adw.OverlaySplitView` has no resize gesture of its own, and `Gtk.Paned` was
  rejected because it would drop the overlay/collapse behaviour.
- The sidebar must be **one** colour. Adwaita paints a `Gtk.ListBox` in the page's own
  `view_bg_color`, so the list area came out darker than the 8px grab strip beside it
  (transparent, so the pane's `sidebar_bg_color` shows through) — measured as a band
  exactly the strip's width next to the divider. `self.outline_list` therefore carries
  the stock **`.navigation-sidebar`** class, which repaints the list in
  `sidebar_bg_color` — measured uniform (46,46,50) over the list area, the strip, and
  the area below the rows of a short outline, against (29,29,32) for the page. The
  `.sidebar` class is not that rule: it changes nothing here.
- Every header and find-bar button has an accelerator, and every one of them goes
  through the app action of the same feature: `app.back`/`app.forward` (arrows and
  `Alt+b`/`Alt+f`), `app.find` (`Ctrl+F`), `app.outline` (`F9`), `app.open`
  (`Ctrl+O`), `app.width` (`Ctrl+0`), `app.next-match` (`Ctrl+G`),
  `app.previous-match` (`Ctrl+Shift+G`) and `app.close` (`Ctrl+W`, closing the one
  window this launch owns). The buttons themselves stay wired to signals (or to
  the toggle path, e.g. `toggle_width` flipping `width_button`) rather than to
  `action-name`: a `Gtk.Actionable` binding takes over the widget's sensitivity
  from the action's enabled state, which would fight the hand-managed
  `update_nav_buttons` sensitivity on back/forward. Tooltips name the keys
  ("Outline (F9)"); GTK canonicalises the modifier order when the accelerator is
  read back (`<Control><Shift>g` comes back as `<Shift><Control>g`), so assert
  that spelling, not the one passed to `set_accels_for_action`.
- Installed desktop entry: `make install` rewrites the repo copy's bare
  `Exec=gmdv %f` to the absolute `$(DESTBIN)/gmdv %f`. GIO does not load — and so
  GNOME Shell's app grid does not list, and cannot launch — a desktop entry whose
  `Exec` command is absent from `PATH`; a graphical session's `PATH` (measured:
  `/usr/lib64/ccache:/usr/local/bin:/usr/bin`) need not contain `~/.local/bin`.
  The repo `data/*.desktop` stays portable; only the installed copy is pinned.

## Verification

There is no test suite; verify with throwaway scripts and delete them afterwards.

1. Headless pure layer: `import gmdv` and assert on `render` (the outline of
   setext/duplicate headings, that fenced code contributes none, and that
   entity-escaped headings come back as plain text: `## 1 &lt; 2 &amp; 3` →
   `'1 < 2 & 3'`), `build_page`
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
   For the accelerator inventory, walk `app.list_actions()` and compare
   `get_accels_for_action` against the expected spelling per action (remember GTK
   canonicalises the modifier order), then drive the action and assert the effect:
   `app.width` flips `app.full_width`, the toggle's `get_active()`, its tooltip and the
   `.page full` class in the DOM; `app.next-match`/`app.previous-match` move the current
   match (read `getSelection().getRangeAt(0).startOffset` — WebKit re-splits the text
   node around a match, so the numbers are opaque: assert three activations give three
   distinct offsets and that `previous-match` returns to the one before); `app.close`
   closes the window (`app.window.get_visible()` False — it also ends the process, so
   run that step last). `app.open` would raise a modal dialog: patch the *class* before
   `activate()` (`gmdv.GmdvApp.on_open_clicked = recorder`) so the handler captured at
   action-registration time is the recorder — activating the action, and emitting
   `clicked` on the header button, both land there without a dialog. Tooltips naming the
   keys are collected by walking the `Gtk.HeaderBar` and `app.find_bar` for
   `Gtk.Button`s and asserting the expected `get_tooltip_text()` strings. Delivery
   itself is untestable here, but the window does carry a `Gtk.ShortcutController`
   with `Gtk.ShortcutScope.GLOBAL` — walk `app.window.observe_controllers()`, which
   is what makes the accels fire whatever holds focus.
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
9. In-page find: `GmdvApp(path)`, `activate()`, then `activate_action("find", None)`
   shows the bar (`app.find_revealer.get_reveal_child()` — do not probe focus with
   `find_entry.has_focus()`, see the invariants) and `app.find_entry.set_text("lorem")`
   drives the assertions — `app.find_label.get_text()`
   ("3 matches" / "1 match" / "no matches" / "1000+ matches") and the entry's
   `error` CSS class. Which match is current, and whether Enter/`next-match`/
   `previous-match`/the bar buttons move and wrap it, is read from the DOM:
   `document.getSelection().getRangeAt(0).startOffset`. Reopen and monitor-reload
   behaviour is asserted the same way after rewriting the file. Highlight presence is
   pixels only (WebKit paints the current match yellow): snapshot the page and count
   `r>180, g>180, b<140` pixels — nonzero for a hit, 0 after clearing the query or
   closing the bar. `GObject.signal_lookup` and `GObject.signal_list_names` return
   nothing useful on this host, so a signal's existence is proven by connecting to it
   at runtime, not by introspection.
10. Outline sidebar: `GmdvApp(path)`, `activate()`, then `activate_action("outline", None)`
   shows the sidebar (`app.split.get_show_sidebar()`, default `False`) and
   `app.get_accels_for_action("app.outline") == ("F9",)`; rows are asserted by walking
   `app.outline_list`'s children (count, label text, `row.anchor`, and the label's
   `margin_start` growing with the heading level). Clicking is
   `app.outline_list.emit("row-activated", row)` and the scroll is proven from the DOM
   (`window.scrollY` and the target heading's `getBoundingClientRect().top` inside the
   viewport, via `evaluate_javascript` + `evaluate_javascript_finish(...).to_string()`
   after ~700ms for the smooth scroll). A file with no headings (or the start page)
   leaves 0 rows and shows `app.outline_empty`; a monitor reload or link navigation
   replaces the rows with the new document's. Rows and page agree for
   entity-escaped headings too: the label texts (`row.get_child().get_text()`) must
   equal the DOM's `textContent` for the matching `h1`-`h6` (see the unescaped-name
   invariant). Collapse:
   `app.window.set_default_size(500, 800)` on a live instance → the next allocation
   sets `app.split.get_collapsed() is True` (`False` at the 960 default; measured
   on this host, where a mapped window does honour `set_default_size`).
   Divider: the strip's geometry and hit area are checked directly —
   `handle.compute_bounds(app.window)` (8px, left edge at `sidebar_width - 9`,
   the line being the slot's last pixel) and
   `app.window.pick(x, y, Gtk.PickFlags.DEFAULT)` reaching the handle — plus
   `handle.get_cursor().get_name() == "col-resize"` and
   `set_min/max_sidebar_width` being in place. Whether the divider *looks* right
   is pixels: snapshot the window and read it back with
   `GdkPixbuf.Pixbuf.new_from_file` (`get_pixels()` + `get_rowstride()`), then
   assert the column run across the boundary is sidebar colour, **one** different
   pixel at `width - 1`, page colour from `width` on — and that the sidebar is
   that one colour across the list area, the grab strip and the area below the
   rows of a short outline (see the `.navigation-sidebar` invariant; sampled at a
   list row and well below the last row). `Gtk.WidgetPaintable` snapshots return a
   `None` node on some frames, so retry the snapshot after a main-loop turn.
   There is no input injection here, so a drag is driven with a stubbed gesture
   (`get_last_event()` → an object whose `get_position()` returns a chosen point):
   `app.on_outline_drag_begin(stub, 0, 0)` then
   `app.on_outline_drag_update(stub, dx, 0)` with a moved point. Assert the
   rendered width (`app.split.get_sidebar().get_width()`, 240 of 960 by default)
   follows the pointer, that a ±10px wobble is absolute rather than cumulative,
   that both bounds clamp, and that after a window resize the width sticks
   (400 @960 → 400 @1200) while a narrower window scales it.

## Rules

- Never commit, push, or open pull requests/issues without explicit approval for that
  exact action.
