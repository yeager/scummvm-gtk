#!/usr/bin/env python3
"""ScummVM GTK — A GTK4/Adwaita frontend for ScummVM."""

import gettext
import os
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gtk, Adw, Gio, GLib, Gdk, GdkPixbuf

from scummvm_gtk import __version__
from scummvm_gtk.games import (
    Game, get_all_games, download_icon, download_icon_async,
    get_icons_dir, KNOWN_GAMES,
)

TEXTDOMAIN = "scummvm-gtk"
gettext.textdomain(TEXTDOMAIN)
gettext.bindtextdomain(TEXTDOMAIN, "/usr/share/locale")
_ = gettext.gettext

APP_ID = "se.danielnylander.ScummvmGtk"



def _wlc_settings_path():
    import os
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    d = os.path.join(xdg, "scummvm-gtk")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "welcome.json")

def _load_wlc_settings():
    import os, json
    p = _wlc_settings_path()
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {"welcome_shown": False}

def _save_wlc_settings(s):
    import json
    with open(_wlc_settings_path(), "w") as f:
        json.dump(s, f, indent=2)

class GameCard(Gtk.Box):
    """A card showing a game with icon and title."""

    def __init__(self, game, on_select=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.game = game
        self.on_select = on_select

        self.set_size_request(140, 170)
        self.add_css_class("card")
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(4)
        self.set_margin_end(4)

        # Icon placeholder
        self.icon_widget = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        self.icon_widget.set_pixel_size(96)
        self.icon_widget.set_margin_top(8)
        self.append(self.icon_widget)

        # Title
        title = Gtk.Label(label=game.name)
        title.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        title.set_max_width_chars(16)
        title.set_lines(2)
        title.set_wrap(True)
        title.add_css_class("heading")
        title.set_margin_start(4)
        title.set_margin_end(4)
        self.append(title)

        # Year + company
        if game.year:
            info = Gtk.Label(label=f"{game.year}")
            info.add_css_class("dim-label")
            info.add_css_class("caption")
            self.append(info)

        # Installed indicator
        if game.installed:
            badge = Gtk.Label(label=_("Installed"))
            badge.add_css_class("success")
            badge.add_css_class("caption")
            self.append(badge)

        # Click handler
        click = Gtk.GestureClick.new()
        click.connect("released", self._on_clicked)
        self.add_controller(click)

        # Load icon async
        download_icon_async(game.icon_name, self._on_icon_loaded)

    def _on_icon_loaded(self, path):
        if path:
            GLib.idle_add(self._set_icon, path)

    def _set_icon(self, path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 96, 96, True)
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.icon_widget.set_from_paintable(texture)
        except Exception:
            pass

    def _on_clicked(self, gesture, n_press, x, y):
        if self.on_select:
            self.on_select(self.game)


class DetailPanel(Gtk.Box):
    """Side panel showing detailed game info."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(320, -1)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)

        # Icon
        self.icon = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        self.icon.set_pixel_size(128)
        self.append(self.icon)

        # Title
        self.title_label = Gtk.Label(label=_("Select a game"))
        self.title_label.add_css_class("title-1")
        self.title_label.set_wrap(True)
        self.title_label.set_halign(Gtk.Align.CENTER)
        self.append(self.title_label)

        # Info group
        self.info_group = Adw.PreferencesGroup()
        self.info_group.set_title(_("Details"))

        self.year_row = Adw.ActionRow(title=_("Year"))
        self.info_group.add(self.year_row)

        self.company_row = Adw.ActionRow(title=_("Developer"))
        self.info_group.add(self.company_row)

        self.engine_row = Adw.ActionRow(title=_("Engine"))
        self.info_group.add(self.engine_row)

        self.platform_row = Adw.ActionRow(title=_("Platform"))
        self.info_group.add(self.platform_row)

        self.id_row = Adw.ActionRow(title=_("Game ID"))
        self.info_group.add(self.id_row)

        self.append(self.info_group)

        # Description
        self.desc_label = Gtk.Label()
        self.desc_label.set_wrap(True)
        self.desc_label.set_halign(Gtk.Align.START)
        self.desc_label.add_css_class("body")
        self.desc_label.set_margin_top(8)
        self.append(self.desc_label)

        # Launch button
        self.launch_btn = Gtk.Button(label=_("Launch Game"))
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.add_css_class("pill")
        self.launch_btn.set_halign(Gtk.Align.CENTER)
        self.launch_btn.set_margin_top(16)
        self.launch_btn.set_sensitive(False)
        self.launch_btn.connect("clicked", self._on_launch)
        self.append(self.launch_btn)

        self._current_game = None

    def show_game(self, game):
        self._current_game = game
        self.title_label.set_text(game.name)
        self.year_row.set_subtitle(game.year or _("Unknown"))
        self.company_row.set_subtitle(game.company or _("Unknown"))
        self.engine_row.set_subtitle(game.engine or _("Unknown"))
        self.platform_row.set_subtitle(game.platform or _("Unknown"))
        self.id_row.set_subtitle(game.game_id)
        self.desc_label.set_text(game.description or "")
        self.launch_btn.set_sensitive(game.installed)

        # Load icon
        icon_path = get_icons_dir() / f"{game.icon_name}.png"
        if icon_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), 128, 128, True)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.icon.set_from_paintable(texture)
            except Exception:
                self.icon.set_from_icon_name("applications-games-symbolic")
        else:
            self.icon.set_from_icon_name("applications-games-symbolic")

    def _on_launch(self, btn):
        if self._current_game:
            try:
                subprocess.Popen(["scummvm", self._current_game.game_id])
            except FileNotFoundError:
                pass


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_default_size(1200, 800)
        self.set_title(_("ScummVM GTK"))

        self._games = []
        self._dark = False

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()

        title_widget = Adw.WindowTitle(
            title=_("ScummVM GTK"),
            subtitle=_("ScummVM Game Launcher")
        )
        header.set_title_widget(title_widget)

        # Search
        self.search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic")
        self.search_btn.set_tooltip_text(_("Search games (Ctrl+F)"))
        self.search_btn.connect("toggled", self._on_search_toggled)
        header.pack_start(self.search_btn)

        # View toggle (grid/list)
        self.grid_btn = Gtk.ToggleButton(icon_name="view-grid-symbolic")
        self.grid_btn.set_active(True)
        self.grid_btn.set_tooltip_text(_("Grid View"))
        header.pack_start(self.grid_btn)

        # Theme toggle
        theme_btn = Gtk.Button(icon_name="weather-clear-night-symbolic")
        theme_btn.set_tooltip_text(_("Toggle Theme"))
        theme_btn.connect("clicked", self._toggle_theme)
        header.pack_end(theme_btn)
        self.theme_btn = theme_btn

        # Menu
        menu = Gio.Menu()
        menu.append(_("Scan for Games"), "win.scan")
        menu.append(_("About ScummVM GTK"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_btn)

        main_box.append(header)

        # Search bar
        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text(_("Search games..."))
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        main_box.append(self.search_bar)

        # Content: game grid + detail panel
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_vexpand(True)

        # Game grid (scrollable)
        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(6)
        self.flowbox.set_min_children_per_line(3)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_column_spacing(8)
        self.flowbox.set_row_spacing(8)
        self.flowbox.set_margin_top(12)
        self.flowbox.set_margin_bottom(12)
        self.flowbox.set_margin_start(12)
        self.flowbox.set_margin_end(12)
        scroll.set_child(self.flowbox)
        content_box.append(scroll)

        # Separator
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Detail panel (scrollable)
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.detail_panel = DetailPanel()
        detail_scroll.set_child(self.detail_panel)
        content_box.append(detail_scroll)

        main_box.append(content_box)

        # Status bar
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)
        status_box.set_margin_top(4)
        status_box.set_margin_bottom(4)
        self.status_label = Gtk.Label(label=_("Loading games..."))
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")
        self.status_label.add_css_class("caption")
        status_box.append(self.status_label)
        main_box.append(Gtk.Separator())
        main_box.append(status_box)

        # Actions
        scan_action = Gio.SimpleAction.new("scan", None)
        scan_action.connect("activate", self._on_scan)
        self.add_action(scan_action)

        # Load games
        self._load_games()

    def _load_games(self):
        def do_load():
            games = get_all_games()
            GLib.idle_add(self._on_games_loaded, games)

        thread = threading.Thread(target=do_load, daemon=True)
        thread.start()

    def _on_games_loaded(self, games):
        self._games = games
        self._populate(games)
        installed = sum(1 for g in games if g.installed)
        self.status_label.set_text(
            _("%d games (%d installed)") % (len(games), installed)
        )

    def _populate(self, games):
        # Clear
        while True:
            child = self.flowbox.get_first_child()
            if child is None:
                break
            self.flowbox.remove(child)

        for game in games:
            card = GameCard(game, on_select=self._on_game_selected)
            self.flowbox.append(card)

    def _on_game_selected(self, game):
        self.detail_panel.show_game(game)

    def _on_search_toggled(self, btn):
        self.search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self.search_entry.grab_focus()

    def _on_search_changed(self, entry):
        query = entry.get_text().lower().strip()
        if not query:
            self._populate(self._games)
            return

        filtered = [g for g in self._games
                    if query in g.name.lower()
                    or query in g.game_id.lower()
                    or query in g.company.lower()
                    or query in g.engine.lower()]
        self._populate(filtered)
        self.status_label.set_text(_("%d games found") % len(filtered))

    def _on_scan(self, action, param):
        self.status_label.set_text(_("Scanning for games..."))
        self._load_games()

    def _toggle_theme(self, btn):
        mgr = Adw.StyleManager.get_default()
        self._dark = not self._dark
        if self._dark:
            mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            btn.set_icon_name("weather-clear-symbolic")
        else:
            mgr.set_color_scheme(Adw.ColorScheme.DEFAULT)
            btn.set_icon_name("weather-clear-night-symbolic")


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = MainWindow(application=self)
        window.present()
        # Welcome dialog
        self._wlc_settings = _load_wlc_settings()
        if not self._wlc_settings.get("welcome_shown"):
            self._show_welcome(self.props.active_window or self)


    def do_startup(self):
        Adw.Application.do_startup(self)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        self.set_accels_for_action("win.search", ["<Primary>f"])

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=_("ScummVM GTK"),
            application_icon="applications-games-symbolic",
            developer_name="Daniel Nylander",
            version=__version__,
            developers=["Daniel Nylander"],
            copyright="© 2026 Daniel Nylander",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/yeager/scummvm-gtk",
            issue_url="https://github.com/yeager/scummvm-gtk/issues",
            comments=_("GTK4/Adwaita frontend for ScummVM game launcher.\nBrowse, search and launch your ScummVM games."),
            translator_credits=_("translator-credits"),
        )
        about.present(self.props.active_window)


def main():
    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    main()

    def _show_welcome(self, win):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(420)
        dialog.set_content_height(480)
        page = Adw.StatusPage()
        page.set_icon_name("applications-games-symbolic")
        page.set_title(_("Welcome to ScummVM Launcher"))
        page.set_description(_("Launch and manage ScummVM games.\n\n✓ Browse your game collection\n✓ Grid view with cover art\n✓ Quick launch"))
        btn = Gtk.Button(label=_("Get Started"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_welcome_close, dialog)
        page.set_child(btn)
        box = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        box.add_top_bar(hb)
        box.set_content(page)
        dialog.set_child(box)
        dialog.present(win)

    def _on_welcome_close(self, btn, dialog):
        self._wlc_settings["welcome_shown"] = True
        _save_wlc_settings(self._wlc_settings)
        dialog.close()

