#!/usr/bin/env python3
"""gmdv — a GTK 4 markdown viewer."""

import html
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
EXTENSIONS = ["tables", "fenced_code", "sane_lists"]

# In-page find: case-insensitive, wraps around; the match count is capped
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


def render_markdown(text):
    """Convert markdown source to an HTML fragment."""
    return markdown.markdown(text, extensions=EXTENSIONS)


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

    def do_activate(self):
        if hasattr(self, "window"):
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)

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
        open_button.set_tooltip_text("Open a markdown file")
        open_button.connect("clicked", self.on_open_clicked)
        header.pack_start(open_button)

        self.width_button = Gtk.ToggleButton(icon_name="zoom-original-symbolic")
        self.width_button.set_tooltip_text("Normal width (click for full width)")
        self.width_button.set_active(self.full_width)
        self.width_button.connect("toggled", self.on_width_toggled)
        header.pack_end(self.width_button)

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic")
        self.search_button.set_tooltip_text("Find in page (Ctrl+F)")
        self.search_button.connect("toggled", self.on_find_toggled)
        header.pack_end(self.search_button)

        for name, handler in (
            ("back", self.go_back),
            ("forward", self.go_forward),
            ("find", self.toggle_find),
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
        self.find_prev_button.set_tooltip_text("Previous match")
        self.find_next_button = Gtk.Button(icon_name="go-down-symbolic")
        self.find_next_button.set_tooltip_text("Next match")

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
        self.window.set_child(self.find_bar)

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

    def on_width_toggled(self, button):
        self.full_width = button.get_active()
        if self.full_width:
            button.set_icon_name("zoom-fit-best-symbolic")
            button.set_tooltip_text("Full width (click for normal width)")
        else:
            button.set_icon_name("zoom-original-symbolic")
            button.set_tooltip_text("Normal width (click for full width)")
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
            body = render_markdown(read_source(self.path))
        except OSError as exc:
            page, uri = error_page(str(exc), palette, self.full_width), "file:///"
        else:
            page, uri = build_page(body, palette, self.full_width), self.document_uri()
        self.set_bg(palette)
        self.webview.load_html(page, uri)

    # -- signals ---------------------------------------------------------

    def on_file_changed(self, monitor, file, other_file, event):
        if os.path.exists(self.path):
            self.refresh()
        else:
            palette = self.page_palette()
            self.set_bg(palette)
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
            self.webview.load_html(build_page(START_PAGE, palette, self.full_width), "file:///")
        elif os.path.exists(self.path):
            self.refresh()
        else:
            self.set_bg(palette)
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

    def on_open_clicked(self, button):
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    return GmdvApp(path).run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
