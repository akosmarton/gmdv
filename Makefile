# User-local install. For a system-wide install run the same targets with sudo
# and a system prefix, e.g.:  sudo make install PREFIX=/usr/local
PREFIX ?= $(HOME)/.local
APP_ID = io.github.akosmarton.gmdv
DESTBIN = $(PREFIX)/bin
DESTAPP = $(PREFIX)/share/applications
DESTICON = $(PREFIX)/share/icons/hicolor/scalable/apps
MIMEAPPS = $(HOME)/.config/mimeapps.list

# GIO hides a desktop entry whose Exec command is not on PATH, and a graphical
# session (e.g. GNOME Shell) may not have $(DESTBIN) on its PATH — then the app
# is missing from the app grid and cannot launch. The installed desktop file
# therefore pins the absolute command (see the sed in the install target); the
# repo copy stays portable with a bare `gmdv`.
#
# The hicolor theme ships no index.theme, hence -t. On hosts with third-party
# icons whose filenames contain spaces, this GTK version reports an invalid
# cache; harmless (GTK resolves installed icons without a usable cache), so
# surface a short note instead of a fatal-looking error.
define refresh_icon_cache
	@gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor || \
	  echo "note: icon cache not refreshed (harmless; icons still resolve)"
endef

.PHONY: install uninstall

install:
	install -Dm755 gmdv.py $(DESTBIN)/gmdv
	install -Dm644 data/$(APP_ID).desktop $(DESTAPP)/$(APP_ID).desktop
	sed -i 's|^Exec=gmdv %f$$|Exec=$(DESTBIN)/gmdv %f|' $(DESTAPP)/$(APP_ID).desktop
	install -Dm644 data/$(APP_ID).svg $(DESTICON)/$(APP_ID).svg
	update-desktop-database $(DESTAPP)
	$(refresh_icon_cache)
	xdg-mime default $(APP_ID).desktop text/markdown

uninstall:
	rm -f $(DESTBIN)/gmdv $(DESTAPP)/$(APP_ID).desktop $(DESTICON)/$(APP_ID).svg
	update-desktop-database $(DESTAPP)
	$(refresh_icon_cache)
	-sed -i '/^text\/markdown=io\.github\.gmdv\.Gmdv\.desktop$$/d' $(MIMEAPPS)
