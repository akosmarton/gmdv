#!/usr/bin/env python3
"""gmdv — a GTK 4 markdown viewer."""

import html
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, WebKit  # noqa: E402

import markdown  # noqa: E402

APP_ID = "io.github.gmdv.Gmdv"
EXTENSIONS = ["tables", "fenced_code", "sane_lists"]

# Default window size; the page column is sized to match it exactly so the text
# column fits a freshly opened window without margins or horizontal scrolling.
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 650

PALETTE = {
    False: {
        "bg": "#ffffff",
        "fg": "#1f2328",
        "muted": "#656d76",
        "border": "#d1d9e0",
        "code_bg": "#f6f8fa",
        "link": "#0969da",
    },
    True: {
        "bg": "#0d1117",
        "fg": "#e6edf3",
        "muted": "#8b949e",
        "border": "#30363d",
        "code_bg": "#161b22",
        "link": "#58a6ff",
    },
}

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


def build_page(body_html, dark):
    """Wrap an HTML fragment in a full styled document."""
    colors = PALETTE[bool(dark)]
    style = f"""
body {{
  margin: 0;
  background: {colors["bg"]};
  color: {colors["fg"]};
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
.page {{
  box-sizing:border-box;
  max-width:{WINDOW_WIDTH}px;
  margin:0 auto;
  padding:24px;
}}
h1, h2 {{
  font-weight:600;
  border-bottom:1px solid {colors["border"]};
  padding-bottom:0.3em;
}}
h1 {{ font-size: 2em; }}
h2 {{ font-size: 1.5em; }}
h3 {{ font-size: 1.25em; font-weight: 600; }}
h4 {{ font-size: 1em; font-weight: 600; }}
p, ul, ol, blockquote, table, pre {{ margin: 1em 0; }}
pre {{
  background: {colors["code_bg"]};
  padding: 16px;
  border-radius: 6px;
  overflow: auto;
}}
code {{
  font: 90% ui-monospace, "Cascadia Mono", monospace;
  background: {colors["code_bg"]};
  border-radius: 6px;
  padding: 0.2em 0.4em;
}}
pre code {{
  background: none;
  padding: 0;
}}
table {{ border-collapse: collapse; }}
td, th {{
  border: 1px solid {colors["border"]};
  padding: 6px 13px;
}}
th {{ font-weight: 600; }}
blockquote {{
  border-left: 0.25em solid {colors["muted"]};
  color: {colors["muted"]};
  padding: 0 1em;
}}
a {{ color: {colors["link"]}; }}
img {{ max-width: 100%; }}
hr {{
  border: 0;
  border-top: 1px solid {colors["border"]};
}}
"""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{style}</style></head>"
        f"<body><div class=\"page\">{body_html}</div></body></html>"
    )


def error_page(message, dark):
    """Render a load-failure page."""
    body = f"<h1>Could not load file</h1><p>{html.escape(message)}</p>"
    return build_page(body, dark)


class GmdvApp(Adw.Application):
    """Application object owning the window, web view and file monitor."""

    def __init__(self, initial_path=None):
        super().__init__(application_id=APP_ID)
        self.initial_path = initial_path
        self.path = None
        self.monitor = None
        self.history = []
        self.history_index = -1

    def do_activate(self):
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

        for name, handler in (("back", self.go_back), ("forward", self.go_forward)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        self.set_accels_for_action(
            "app.back", ["<Control>Left", "<Alt>Left", "<Alt>b"]
        )
        self.set_accels_for_action(
            "app.forward", ["<Control>Right", "<Alt>Right", "<Alt>f"]
        )

        self.title_label = Gtk.Label()
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_css_classes(["heading"])
        header.set_title_widget(self.title_label)

        settings = WebKit.Settings.new()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        self.webview = WebKit.WebView(settings=settings)
        self.window.set_child(self.webview)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.window.add_controller(drop)

        self.webview.connect("decide-policy", self.on_decide_policy)

        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.connect("notify::dark", self.on_dark_changed)

        self.window.present()

        if self.initial_path:
            self.load_file(self.initial_path)
        else:
            self.title_label.set_text("gmdv")
            self.set_bg()
            self.webview.load_html(build_page(START_PAGE, self.is_dark()), "file:///")

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

    def set_bg(self):
        rgba = Gdk.RGBA()
        rgba.parse(PALETTE[self.is_dark()]["bg"])
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

    def refresh(self):
        try:
            body = render_markdown(read_source(self.path))
        except OSError as exc:
            page, uri = error_page(str(exc), self.is_dark()), "file:///"
        else:
            page, uri = build_page(body, self.is_dark()), self.document_uri()
        self.set_bg()
        self.webview.load_html(page, uri)

    # -- signals ---------------------------------------------------------

    def on_file_changed(self, monitor, file, other_file, event):
        if os.path.exists(self.path):
            self.refresh()
        else:
            self.set_bg()
            self.webview.load_html(
                error_page("File deleted.", self.is_dark()), "file:///"
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
        self.set_bg()
        if not self.path:
            self.webview.load_html(build_page(START_PAGE, self.is_dark()), "file:///")
        elif os.path.exists(self.path):
            self.refresh()
        else:
            self.webview.load_html(
                error_page("File deleted.", self.is_dark()), "file:///"
            )

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
    return GmdvApp(path).run([])


if __name__ == "__main__":
    sys.exit(main())
