#!/usr/bin/env python3
"""gmdv — a GTK 4 markdown viewer."""

import html
import json
import os
import sys
import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, WebKit  # noqa: E402

import markdown  # noqa: E402

APP_ID = "io.github.akosmarton.gmdv"
EXTENSIONS = ["tables", "fenced_code", "sane_lists", "toc"]

# Dependency contract. gi.require_version above pins the API *generation* of the
# GUI stack (Gtk 4.0, Adw 1, WebKitGTK 6.0) — the most a distribution package
# can be pinned to, since PyGObject ships as a source tarball on PyPI and has no
# wheels. The releases inside that generation are checked at startup instead:
# a library below them lacks the API gmdv calls, which is a crash rather than a
# degraded view. python-markdown is a plain pip dependency and is pinned
# exactly, in requirements.txt (VERIFIED_MARKDOWN mirrors that pin); the floor
# exists because the page layout is built against the 3.x output and 2.x is
# unmaintained and renders differently.
#
#   GTK        4.10 — Gtk.FileDialog, the file chooser (unannotated Adw methods
#                     and the other Gtk calls date from 4.0)
#   libadwaita 1.4  — Adw.OverlaySplitView, the outline sidebar (Adw.Application
#                     and Adw.StyleManager date from 1.0)
#   WebKitGTK  2.40 — the first stable release of the WebKit 6.0 API itself
MIN_MARKDOWN = (3, 0)
MIN_GTK = (4, 10)
MIN_ADW = (1, 4)
MIN_WEBKIT = (2, 40)
VERIFIED_MARKDOWN = "3.10.3"


def dotted(version):
    """Render a parsed version tuple the way it is written in package names."""
    return ".".join(str(number) for number in version)


def version_tuple(text):
    """Parse a dotted release string into a comparable tuple, () if unparseable."""
    parts = []
    for part in str(text).split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def meets(version, minimum):
    """Whether a parsed version reaches a minimum, shorter ones padded with 0.

    An empty tuple means the version is missing or unparseable: unknown, never
    a failure.
    """
    if not version:
        return True
    return version + (0,) * len(minimum) >= minimum


def gui_stack():
    """Name, loaded release, floor and justifying API of each GUI library."""
    return (
        (
            "GTK",
            (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()),
            MIN_GTK,
            "Gtk.FileDialog",
        ),
        (
            "libadwaita",
            (Adw.MAJOR_VERSION, Adw.MINOR_VERSION, Adw.MICRO_VERSION),
            MIN_ADW,
            "Adw.OverlaySplitView",
        ),
        (
            "WebKitGTK",
            (WebKit.get_major_version(), WebKit.get_minor_version(), WebKit.get_micro_version()),
            MIN_WEBKIT,
            "the WebKit 6.0 API",
        ),
    )


def loaded_report():
    """One line naming every loaded dependency, for a bug report."""
    libraries = [f"python {sys.version.split()[0]}", f"PyGObject {gi.__version__}"]
    libraries += [f"{name} {dotted(version)}" for name, version, _, _ in gui_stack()]
    libraries.append(f"python-markdown {getattr(markdown, '__version__', 'unknown')}")
    return ", ".join(libraries)


def dependency_error():
    """A printable report of unmet dependency floors, or None when all is well.

    PyGObject and the interpreter are reported but not floored: nothing gmdv
    calls is gated on their release, only on the typelib releases above.
    """
    problems = []
    markdown_release = getattr(markdown, "__version__", "")
    if not meets(version_tuple(markdown_release), MIN_MARKDOWN):
        problems.append(
            f"python-markdown {markdown_release} is older than {dotted(MIN_MARKDOWN)} "
            f"(verified with {VERIFIED_MARKDOWN}, see requirements.txt); upgrade it "
            f"with: pip install --upgrade 'Markdown>={dotted(MIN_MARKDOWN)}'"
        )
    for name, version, floor, needed_by in gui_stack():
        if not meets(version, floor):
            problems.append(
                f"{name} {dotted(version)} is older than {dotted(floor)}, "
                f"which {needed_by} needs"
            )
    if not problems:
        return None
    lines = "".join(f"      {problem}\n" for problem in problems)
    return (
        "gmdv: dependency versions below the floor:\n"
        f"{lines}"
        f"      loaded: {loaded_report()}"
    )


# In-page find: case-insensitive, wraps around, the match count is capped
# because WebKit reports UINT32_MAX when the cap is exceeded.
FIND_OPTIONS = WebKit.FindOptions.CASE_INSENSITIVE | WebKit.FindOptions.WRAP_AROUND
FIND_MAX_MATCHES = 1000

# Default window size. The reading column is narrower than the window, so a
# fresh window shows the text centred with equal side margins; PAGE_WIDTH keeps
# that column fixed however the window is resized.
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 1000

# Width of the reading column in normal (non-full-width) mode.
PAGE_WIDTH = 900

# Window width below which the outline sidebar overlays the page instead of
# sitting beside it; applied in GmdvWindow.do_size_allocate (Adw.Breakpoint would
# need an Adw.Bin window, and GTK 4 has no allocation signal or notifying width).
OUTLINE_COLLAPSE_WIDTH = 600

# Bounds the sidebar width may be dragged between, in pixels. The width itself is
# held as a share of the split view capped at the dragged width, so it survives a
# window resize proportionally; OUTLINE_WIDTH_MIN is Adw.OverlaySplitView's own
# minimum, while the 640px ceiling is this app's.
OUTLINE_WIDTH_MIN = 180
OUTLINE_WIDTH_MAX = 640

# Adwaita named colors the page is painted from; read out of the live GTK theme
# by theme_palette(). "muted" (a dim label) is not a theme color, so it is
# derived from the foreground color instead.
THEME_COLORS = {
    "bg": "view_bg_color",
    "fg": "view_fg_color",
    "border": "borders",
    "code_bg": "window_bg_color",
    "link": "accent_color",
}

# Fallback palette — the Adwaita light/dark values — for callers that have no GTK
# theme to read (headless tests). The app always paints from theme_palette().
PALETTE = {
    False: {
        "bg": "#ffffff",
        "fg": "rgba(0,0,6,0.8)",
        "muted": "rgba(0,0,6,0.44)",
        "border": "rgba(0,0,6,0.12)",
        "code_bg": "#fafafb",
        "link": "#0461be",
    },
    True: {
        "bg": "#1d1d20",
        "fg": "#ffffff",
        "muted": "rgba(255,255,255,0.55)",
        "border": "rgba(255,255,255,0.15)",
        "code_bg": "#222226",
        "link": "#81d0ff",
    },
}


def theme_palette(context, dark):
    """Page palette taken from the live GTK/Adwaita theme.

    ``Gtk.StyleContext.lookup_color`` is deprecated since GTK 4.10 yet remains
    the only way to read the theme's named colors; every color the theme does
    not define keeps its static ``PALETTE`` value.
    """
    palette = dict(PALETTE[bool(dark)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for key, name in THEME_COLORS.items():
            found, rgba = context.lookup_color(name)
            if found:
                palette[key] = rgba.to_string()
        found, fg = context.lookup_color(THEME_COLORS["fg"])
    if found:
        palette["muted"] = (
            f"rgba({round(fg.red * 255)},{round(fg.green * 255)},"
            f"{round(fg.blue * 255)},{fg.alpha * 0.55:.3f})"
        )
    return palette


START_PAGE = (
    "<h1>gmdv</h1>"
    "<p>No file loaded. Use the button in the header bar or drop a markdown file here.</p>"
)


def read_source(path):
    """Read a file as UTF-8, replacing undecodable bytes instead of failing."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def render(text):
    """Convert markdown source to an HTML fragment and its heading outline.

    Outline entries carry the ids the ``toc`` extension gave the rendered
    headings; they come from the rendered result, not from re-parsing the
    source, so setext headings are outlined and fenced code blocks are not.

    The names come out HTML-escaped (``&amp;``, ``&lt;``) because they are taken
    from the rendered heading, so they are unescaped here: the sidebar shows them
    in a plain ``Gtk.Label``, which would print the entities literally. Inline
    markup and raw HTML drop out of the names along the way (``**bold**`` and
    ``<span>x</span>`` leave just their text).
    """
    converter = markdown.Markdown(extensions=EXTENSIONS)
    body = converter.convert(text)
    entries = []

    def walk(tokens):
        for token in tokens:
            entries.append(
                (token["level"], html.unescape(token["name"]), token["id"])
            )
            walk(token["children"])

    walk(converter.toc_tokens)
    return body, tuple(entries)


def build_page(body_html, palette, full_width=False):
    """Wrap an HTML fragment in a full styled document."""
    page_class = "page full" if full_width else "page"
    style = f"""
body {{
  margin: 0;
  background: {palette["bg"]};
  color: {palette["fg"]};
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
.page {{
  box-sizing:border-box;
  max-width:{PAGE_WIDTH}px;
  margin:0 auto;
  padding:24px;
}}
.page.full {{
  max-width:none;
  margin:0;
}}
h1, h2 {{
  font-weight:600;
  border-bottom:1px solid {palette["border"]};
  padding-bottom:0.3em;
}}
h1 {{ font-size: 2em; }}
h2 {{ font-size: 1.5em; }}
h3 {{ font-size: 1.25em; font-weight: 600; }}
h4 {{ font-size: 1em; font-weight: 600; }}
p, ul, ol, blockquote, table, pre {{ margin: 1em 0; }}
pre {{
  background: {palette["code_bg"]};
  padding: 16px;
  border-radius: 6px;
  overflow: auto;
}}
code {{
  font: 90% ui-monospace, "Cascadia Mono", monospace;
  background: {palette["code_bg"]};
  border-radius: 6px;
  padding: 0.2em 0.4em;
}}
pre code {{
  background: none;
  padding: 0;
}}
table {{ border-collapse: collapse; }}
td, th {{
  border: 1px solid {palette["border"]};
  padding: 6px 13px;
}}
th {{ font-weight: 600; }}
blockquote {{
  border-left: 0.25em solid {palette["muted"]};
  color: {palette["muted"]};
  padding: 0 1em;
}}
a {{ color: {palette["link"]}; }}
img {{ max-width: 100%; }}
hr {{
  border: 0;
  border-top: 1px solid {palette["border"]};
}}
/* Paper colors, whatever scheme the window is in. */
@media print {{
  body {{ background:#ffffff; color:#1b1b1f; }}
  pre, code {{ background:#f6f8fa; }}
  h1, h2, td, th, hr {{ border-color:#d0d0d5; }}
  blockquote {{ border-left-color:#8b8b90; color:#57575e; }}
  a {{ color:#0461be; }}
}}
"""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{style}</style></head>"
        f"<body><div class=\"{page_class}\">{body_html}</div></body></html>"
    )


def error_page(message, palette, full_width=False):
    """Render a load-failure page."""
    body = f"<h1>Could not load file</h1><p>{html.escape(message)}</p>"
    return build_page(body, palette, full_width)


class GmdvWindow(Gtk.ApplicationWindow):
    """The application window and the split view holding the outline sidebar.

    ``Adw.Breakpoint`` would express the collapse below ``OUTLINE_COLLAPSE_WIDTH``,
    but it needs an ``Adw.Bin`` window and ours is a plain ``Gtk.ApplicationWindow``
    (``Adw.OverlaySplitView`` is final, so it cannot be subclassed either). GTK 4 has
    no ``size-allocate`` signal and ``Gtk.Widget:width`` does not notify, so the
    decision is taken in the allocation vfunc itself.
    """

    __gtype_name__ = "GmdvWindow"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.split = Adw.OverlaySplitView()
        # show-sidebar defaults to True on this libadwaita; the outline starts
        # hidden, and every other split-view default (sidebar-width-fraction
        # 0.25, hide gesture on, pin off) is left alone.
        self.split.set_show_sidebar(False)
        self.set_child(self.split)

    def do_size_allocate(self, width, height, baseline):
        Gtk.ApplicationWindow.do_size_allocate(self, width, height, baseline)
        collapsed = width < OUTLINE_COLLAPSE_WIDTH
        if collapsed != self.split.get_collapsed():
            self.split.set_collapsed(collapsed)


class GmdvApp(Adw.Application):
    """Application object owning the window, web view and file monitor."""

    def __init__(self, initial_path=None):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.initial_path = initial_path
        self.path = None
        self.monitor = None
        self.history = []
        self.history_index = -1
        self.full_width = False
        self.outline_visible = False
        self.outline_drag = None

    def do_activate(self):
        if hasattr(self, "window"):
            self.window.present()
            return
        self.window = GmdvWindow(application=self)
        self.window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.split = self.window.split

        header = Gtk.HeaderBar()
        self.window.set_titlebar(header)

        self.back_button = Gtk.Button(icon_name="go-previous-symbolic")
        self.back_button.set_tooltip_text("Go back")
        self.back_button.connect("clicked", self.go_back)
        header.pack_start(self.back_button)

        self.forward_button = Gtk.Button(icon_name="go-next-symbolic")
        self.forward_button.set_tooltip_text("Go forward")
        self.forward_button.connect("clicked", self.go_forward)
        header.pack_start(self.forward_button)
        self.update_nav_buttons()

        open_button = Gtk.Button(icon_name="document-open-symbolic")
        open_button.set_tooltip_text("Open a markdown file (Ctrl+O)")
        open_button.connect("clicked", self.on_open_clicked)
        header.pack_start(open_button)

        print_button = Gtk.Button(icon_name="printer-symbolic")
        print_button.set_tooltip_text("Print (Ctrl+P)")
        print_button.connect("clicked", self.on_print)
        header.pack_start(print_button)

        self.width_button = Gtk.ToggleButton(icon_name="zoom-original-symbolic")
        self.width_button.set_tooltip_text("Normal width (Ctrl+0, click for full width)")
        self.width_button.set_active(self.full_width)
        self.width_button.connect("toggled", self.on_width_toggled)
        header.pack_end(self.width_button)

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic")
        self.search_button.set_tooltip_text("Find in page (Ctrl+F)")
        self.search_button.connect("toggled", self.on_find_toggled)
        header.pack_end(self.search_button)

        self.outline_button = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self.outline_button.set_tooltip_text("Outline (F9)")
        self.outline_button.set_active(self.outline_visible)
        self.outline_button.connect("toggled", self.on_outline_toggled)
        header.pack_end(self.outline_button)

        for name, handler in (
            ("back", self.go_back),
            ("forward", self.go_forward),
            ("find", self.toggle_find),
            ("outline", self.toggle_outline),
            ("open", self.on_open_clicked),
            ("print", self.on_print),
            ("width", self.toggle_width),
            ("next-match", self.on_search_next),
            ("previous-match", self.on_search_previous),
            ("close", self.close_window),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        self.set_accels_for_action(
            "app.back", ["<Control>Left", "<Alt>Left", "<Alt>b"]
        )
        self.set_accels_for_action(
            "app.forward", ["<Control>Right", "<Alt>Right", "<Alt>f"]
        )
        self.set_accels_for_action("app.find", ["<Control>f"])
        self.set_accels_for_action("app.outline", ["F9"])
        self.set_accels_for_action("app.open", ["<Control>o"])
        self.set_accels_for_action("app.print", ["<Control>p"])
        self.set_accels_for_action("app.width", ["<Control>0"])
        self.set_accels_for_action("app.next-match", ["<Control>g"])
        self.set_accels_for_action("app.previous-match", ["<Control><Shift>g"])
        self.set_accels_for_action("app.close", ["<Control>w"])

        self.title_label = Gtk.Label()
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_css_classes(["heading"])
        header.set_title_widget(self.title_label)

        settings = WebKit.Settings.new()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        self.webview = WebKit.WebView(settings=settings)
        # The box hands out only natural height otherwise, and a WebKit web view
        # has none: without this the page is allocated zero height.
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)

        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_placeholder_text("Find…")
        self.find_entry.set_hexpand(True)

        self.find_label = Gtk.Label()
        self.find_label.set_css_classes(["dim-label"])
        self.find_label.set_width_chars(12)
        self.find_label.set_xalign(1.0)

        self.find_prev_button = Gtk.Button(icon_name="go-up-symbolic")
        self.find_prev_button.set_tooltip_text("Previous match (Ctrl+Shift+G)")
        self.find_next_button = Gtk.Button(icon_name="go-down-symbolic")
        self.find_next_button.set_tooltip_text("Next match (Ctrl+G)")

        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        find_row.set_margin_top(6)
        find_row.set_margin_bottom(6)
        find_row.set_margin_start(6)
        find_row.set_margin_end(6)
        find_row.append(self.find_entry)
        find_row.append(self.find_label)
        find_row.append(self.find_prev_button)
        find_row.append(self.find_next_button)

        self.find_revealer = Gtk.Revealer()
        self.find_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.find_revealer.set_transition_duration(200)
        self.find_revealer.set_child(find_row)
        self.find_revealer.set_reveal_child(False)

        # A vertical box holding the find bar above the page: the bar sits
        # directly under the header bar and pushes the page down while revealed.
        self.find_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.find_bar.append(self.find_revealer)
        self.find_bar.append(self.webview)

        # Outline sidebar: the headings of the loaded document, click to scroll.
        self.outline_list = Gtk.ListBox()
        self.outline_list.set_selection_mode(Gtk.SelectionMode.NONE)
        # Adwaita's list background is the page's own view_bg_color, which shows as
        # a band next to the grab strip (it is transparent, so the pane's
        # sidebar_bg_color shows there instead). The navigation-sidebar class
        # repaints the list in sidebar_bg_color, making the whole sidebar one color.
        self.outline_list.set_css_classes(["navigation-sidebar"])
        self.outline_list.connect("row-activated", self.on_outline_row)
        self.outline_empty = Gtk.Label(label="No headings")
        self.outline_empty.set_css_classes(["dim-label"])
        self.outline_empty.set_visible(False)
        outline_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outline_box.append(self.outline_list)
        outline_box.append(self.outline_empty)
        outline_scroll = Gtk.ScrolledWindow()
        outline_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outline_scroll.set_child(outline_box)
        outline_scroll.set_hexpand(True)

        # The divider: an invisible 8px grab strip on the sidebar's inner edge,
        # with the visible 1px line after it so the line lands exactly where the
        # page starts (a separator *inside* the strip would sit 8px short of it).
        self.outline_handle = Gtk.Box()
        self.outline_handle.set_size_request(8, -1)
        self.outline_handle.set_cursor_from_name("col-resize")
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_outline_drag_begin)
        drag.connect("drag-update", self.on_outline_drag_update)
        self.outline_handle.add_controller(drag)

        outline_sidebar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        outline_sidebar.append(outline_scroll)
        outline_sidebar.append(self.outline_handle)
        outline_sidebar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.split.set_min_sidebar_width(OUTLINE_WIDTH_MIN)
        self.split.set_max_sidebar_width(OUTLINE_WIDTH_MAX)
        self.split.set_sidebar(outline_sidebar)
        self.split.set_content(self.find_bar)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.window.add_controller(drop)

        self.webview.connect("decide-policy", self.on_decide_policy)
        self.webview.connect("load-changed", self.on_load_changed)

        self.find_controller = self.webview.get_find_controller()
        self.find_controller.connect("counted-matches", self.on_counted_matches)
        self.find_controller.connect("failed-to-find-text", self.on_search_failed)
        self.find_entry.connect("search-changed", self.on_search_changed)
        self.find_entry.connect("activate", self.on_search_next)
        self.find_entry.connect("next-match", self.on_search_next)
        self.find_entry.connect("previous-match", self.on_search_previous)
        self.find_entry.connect("stop-search", self.on_search_stop)
        self.find_prev_button.connect("clicked", self.on_search_previous)
        self.find_next_button.connect("clicked", self.on_search_next)

        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.connect("notify::dark", self.on_dark_changed)

        self.window.present()

        if self.initial_path:
            self.load_file(self.initial_path)
        else:
            self.title_label.set_text("gmdv")
            palette = self.page_palette()
            self.set_bg(palette)
            self.set_outline(())
            self.webview.load_html(build_page(START_PAGE, palette, self.full_width), "file:///")

    def do_open(self, files, n_files, hint):
        """Load a file passed by GApplication (file manager, CLI, ``xdg-open``).

        Instances are unique-per-launch (`NON_UNIQUE`), so no file is ever
        forwarded: a launch carrying a file argument reaches this handler in its
        own process, where GApplication on this host calls ``open`` *instead of*
        ``activate`` (neither is called first) and no window exists yet — build
        it here, reusing ``do_activate``. If a window is already up (an
        in-process ``open()``), load the file and raise that window.
        """
        if n_files < 1:
            return
        path = files[0].get_path()
        if not path:
            return
        if not hasattr(self, "window"):
            self.initial_path = path
            self.do_activate()
        else:
            self.load_file(path)
            self.window.present()

    # -- helpers ---------------------------------------------------------

    def is_dark(self):
        return self.style_manager.get_dark()

    def document_uri(self):
        """URI the rendered page pretends to live at.

        The file's own URI (not its directory) so that relative subresources
        resolve next to the file and in-page ``#fragment`` links resolve to the
        document instead of the directory.
        """
        return GLib.filename_to_uri(os.path.abspath(self.path))

    def page_palette(self):
        """Palette for the page, read from the web view's live GTK theme."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            context = self.webview.get_style_context()
        return theme_palette(context, self.is_dark())

    def set_bg(self, palette=None):
        rgba = Gdk.RGBA()
        rgba.parse((palette or self.page_palette())["bg"])
        self.webview.set_background_color(rgba)

    def load_file(self, path, push=True):
        """Show ``path``, optionally recording it as a new history entry."""
        path = os.path.abspath(path)
        if push and path != self.path:
            del self.history[self.history_index + 1:]
            self.history.append(path)
            self.history_index = len(self.history) - 1
        self.path = path
        self.title_label.set_text(os.path.basename(path))
        if self.monitor:
            self.monitor.cancel()
        self.monitor = Gio.File.new_for_path(path).monitor_file(Gio.FileMonitorFlags.NONE)
        self.monitor.connect("changed", self.on_file_changed)
        self.update_nav_buttons()
        self.refresh()

    def go_back(self, *_args):
        if self.history_index > 0:
            self.history_index -= 1
            self.load_file(self.history[self.history_index], push=False)

    def go_forward(self, *_args):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self.load_file(self.history[self.history_index], push=False)

    def update_nav_buttons(self):
        self.back_button.set_sensitive(self.history_index > 0)
        self.forward_button.set_sensitive(self.history_index + 1 < len(self.history))

    def toggle_width(self, *_args):
        """Header width toggle and ``Ctrl+0`` share this entry point."""
        self.width_button.set_active(not self.width_button.get_active())

    def on_width_toggled(self, button):
        self.full_width = button.get_active()
        if self.full_width:
            button.set_icon_name("zoom-fit-best-symbolic")
            button.set_tooltip_text("Full width (Ctrl+0, click for normal width)")
        else:
            button.set_icon_name("zoom-original-symbolic")
            button.set_tooltip_text("Normal width (Ctrl+0, click for full width)")
        self.apply_width()

    def apply_width(self):
        """Switch the loaded page between the normal and full-width column.

        The class is toggled in the live document rather than re-rendering, so the
        scroll position survives; every later render picks the state up from
        ``self.full_width``.
        """
        full = "true" if self.full_width else "false"
        script = (
            "(() => { const page = document.querySelector('.page');"
            f" if (page) page.classList.toggle('full', {full}); }})()"
        )
        self.webview.evaluate_javascript(script, -1, None, None, None, None)

    # -- outline sidebar -------------------------------------------------

    def set_outline(self, entries):
        """Rebuild the sidebar rows for the page being loaded."""
        row = self.outline_list.get_first_child()
        while row:
            following = row.get_next_sibling()
            self.outline_list.remove(row)
            row = following
        for level, name, anchor in entries:
            label = Gtk.Label(label=name)
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0.0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_margin_start(12 + 12 * (level - 1))
            label.set_margin_top(3)
            label.set_margin_bottom(3)
            item = Gtk.ListBoxRow()
            item.anchor = anchor
            item.set_child(label)
            self.outline_list.append(item)
        self.outline_empty.set_visible(not entries)

    def toggle_outline(self, *_args):
        """Header button and ``F9`` share this entry point."""
        self.outline_button.set_active(not self.outline_button.get_active())

    def on_outline_toggled(self, button):
        self.outline_visible = button.get_active()
        self.split.set_show_sidebar(self.outline_visible)
        if self.outline_visible:
            button.set_tooltip_text("Hide outline (F9)")
        else:
            button.set_tooltip_text("Outline (F9)")

    def on_outline_row(self, box, row):
        script = (
            "(() => {"
            f" const node = document.getElementById({json.dumps(row.anchor)});"
            " if (node) node.scrollIntoView({behavior:'smooth', block:'start'});"
            " })()"
        )
        self.webview.evaluate_javascript(script, -1, None, None, None, None)

    def on_outline_drag_begin(self, gesture, start_x, start_y):
        """Anchor a divider drag on the width and pointer position it starts at.

        The pointer is read in surface coordinates: the handle travels with the
        edge it drags, so the offsets GTK reports for it (``get_offset``,
        ``get_point``) are measured against a moving origin and would cancel out
        the very movement being dragged.
        """
        position = self.pointer_x(gesture)
        if position is not None:
            self.outline_drag = (self.split.get_sidebar().get_width(), position)

    def on_outline_drag_update(self, gesture, offset_x, offset_y):
        """Follow the pointer: the two offsets are ignored, see the begin handler."""
        position = self.pointer_x(gesture)
        if position is None or self.outline_drag is None:
            return
        width, start = self.outline_drag
        self.set_outline_width(width + position - start)

    def pointer_x(self, gesture):
        """The pointer's x during ``gesture``, in surface coordinates, or None."""
        event = gesture.get_last_event()
        if event is None:
            return None
        found, x, _y = event.get_position()
        return x if found else None

    def set_outline_width(self, width):
        """Give the sidebar ``width`` pixels, within the bounds it may take.

        The width is held as a share of the split view, capped at ``width``: a
        wider window therefore keeps the dragged width (up to
        ``OUTLINE_WIDTH_MAX``), while a narrower one scales the sidebar down with
        it instead of squeezing the page out.
        """
        split_width = self.split.get_width()
        if not split_width:
            return
        width = max(OUTLINE_WIDTH_MIN, min(OUTLINE_WIDTH_MAX, round(width)))
        self.split.set_max_sidebar_width(width)
        self.split.set_sidebar_width_fraction(min(1.0, width / split_width))

    # -- find in page ----------------------------------------------------

    def toggle_find(self, *_args):
        """Header magnifier and ``Ctrl+F`` share this entry point."""
        self.search_button.set_active(not self.search_button.get_active())

    def on_find_toggled(self, button):
        self.set_search_visible(button.get_active())

    def set_search_visible(self, visible):
        """Slide the find bar in or out; Escape and the toggle share this path."""
        self.find_revealer.set_reveal_child(visible)
        if visible:
            self.find_entry.grab_focus()
            text = self.find_entry.get_text()
            if text:
                # Re-select the kept query so typing replaces it.
                self.find_entry.select_region(0, len(text))
                self.run_search(text)
        else:
            self.clear_find_highlight()
            self.find_label.set_text("")
            self.find_entry.remove_css_class("error")

    def clear_find_highlight(self):
        """Drop WebKit's find highlight and the selection it leaves behind.

        ``search_finish()`` removes the yellow find highlight but keeps the
        selection WebKit set for the current match, which still shows up as a
        tinted range; clearing the selection ranges takes that away too.
        """
        self.find_controller.search_finish()
        self.webview.evaluate_javascript(
            "(() => { const s = window.getSelection(); if (s) s.removeAllRanges(); })()",
            -1,
            None,
            None,
            None,
            None,
        )

    def run_search(self, text):
        """(Re)run the find for ``text`` and refresh the match counter."""
        self.find_controller.search(text, FIND_OPTIONS, 0)
        self.find_controller.count_matches(text, FIND_OPTIONS, FIND_MAX_MATCHES)

    def on_search_changed(self, entry):
        text = entry.get_text()
        if text:
            self.run_search(text)
        else:
            self.clear_find_highlight()
            self.find_label.set_text("")
            entry.remove_css_class("error")

    def on_search_next(self, *_args):
        self.find_controller.search_next()

    def on_search_previous(self, *_args):
        self.find_controller.search_previous()

    def on_search_stop(self, *_args):
        self.search_button.set_active(False)

    def on_counted_matches(self, _controller, n_matches):
        if n_matches >= FIND_MAX_MATCHES:
            # count_matches reports UINT32_MAX once the cap is exceeded.
            self.find_label.set_text(f"{FIND_MAX_MATCHES}+ matches")
        elif n_matches == 0:
            self.find_label.set_text("no matches")
        elif n_matches == 1:
            self.find_label.set_text("1 match")
        else:
            self.find_label.set_text(f"{n_matches} matches")
        if n_matches == 0:
            self.find_entry.add_css_class("error")
        else:
            self.find_entry.remove_css_class("error")

    def on_search_failed(self, _controller):
        self.find_entry.add_css_class("error")

    def on_load_changed(self, webview, event):
        """A load clears WebKit's find state — re-run an open search."""
        if (
            event == WebKit.LoadEvent.FINISHED
            and self.find_revealer.get_reveal_child()
            and self.find_entry.get_text()
        ):
            self.run_search(self.find_entry.get_text())

    def refresh(self):
        palette = self.page_palette()
        try:
            body, outline = render(read_source(self.path))
        except OSError as exc:
            page, outline = error_page(str(exc), palette, self.full_width), ()
            uri = "file:///"
        else:
            page = build_page(body, palette, self.full_width)
            uri = self.document_uri()
        self.set_bg(palette)
        self.set_outline(outline)
        self.webview.load_html(page, uri)

    # -- signals ---------------------------------------------------------

    def on_file_changed(self, monitor, file, other_file, event):
        if os.path.exists(self.path):
            self.refresh()
        else:
            palette = self.page_palette()
            self.set_bg(palette)
            self.set_outline(())
            self.webview.load_html(
                error_page("File deleted.", palette, self.full_width), "file:///"
            )

    def on_decide_policy(self, webview, decision, decision_type):
        """Render markdown reached by clicking a link instead of showing it as text."""
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION or not self.path:
            return False
        action = decision.get_navigation_action()
        if action.get_navigation_type() != WebKit.NavigationType.LINK_CLICKED:
            return False
        request = action.get_request()
        uri = request.get_uri() if request else None
        if not uri or not uri.startswith("file://"):
            return False
        target, _, fragment = uri.partition("#")
        path = GLib.filename_from_uri(target)[0]
        if fragment and path == os.path.abspath(self.path):
            return False
        decision.ignore()
        self.load_file(path)
        return True

    def on_dark_changed(self, *args):
        """Queue a re-render for the freshly applied color scheme.

        Reading the theme colors from inside this handler still yields the
        previous scheme (GTK revalidates the CSS after the style manager has
        notified), so the work is deferred by one main-loop turn, by which time
        ``page_palette`` returns the new colors.
        """
        GLib.idle_add(self.apply_theme)

    def apply_theme(self):
        """Re-render the current page with the current theme colors."""
        palette = self.page_palette()
        if not self.path:
            self.set_bg(palette)
            self.set_outline(())
            self.webview.load_html(build_page(START_PAGE, palette, self.full_width), "file:///")
        elif os.path.exists(self.path):
            self.refresh()
        else:
            self.set_bg(palette)
            self.set_outline(())
            self.webview.load_html(
                error_page("File deleted.", palette, self.full_width), "file:///"
            )
        return False

    def on_drop(self, target, value, x, y):
        if hasattr(value, "get_files"):
            files = value.get_files()
        else:
            files = list(value)
        for file in files:
            path = file.get_path()
            if path:
                self.load_file(path)
                return True
        return False

    def close_window(self, *_args):
        """``Ctrl+W``: one window per document, so closing it ends the process."""
        self.window.close()

    def on_open_clicked(self, *_args):
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Markdown File")

        filters = Gio.ListStore.new(Gtk.FileFilter)

        markdown_filter = Gtk.FileFilter()
        markdown_filter.set_name("Markdown files")
        markdown_filter.add_pattern("*.md")
        markdown_filter.add_pattern("*.markdown")
        markdown_filter.add_pattern("*.mkd")
        markdown_filter.add_mime_type("text/markdown")
        filters.append(markdown_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        filters.append(all_filter)

        dialog.set_filters(filters)
        dialog.set_default_filter(markdown_filter)
        dialog.open(self.window, None, self.on_open_finish)

    def on_open_finish(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if path:
            self.load_file(path)

    def on_print(self, *_args):
        """Print the displayed page; the header button and Ctrl+P share this path."""
        print_operation = WebKit.PrintOperation.new(self.webview)
        print_operation.connect("failed", self.on_print_failed)
        print_operation.run_dialog(self.window)

    def on_print_failed(self, _operation, error):
        print(f"gmdv: printing failed: {error.message}", file=sys.stderr)


def main():
    GLib.set_application_name("gmdv")
    problem = dependency_error()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    path = sys.argv[1] if len(sys.argv) > 1 else None
    return GmdvApp(path).run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
