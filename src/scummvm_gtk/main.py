#!/usr/bin/env python3
"""ScummVM GTK — A GTK4/Adwaita frontend for ScummVM."""

import gettext
import json
import os
import subprocess
import sys
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gtk, Adw, Gio, GLib, Gdk, GdkPixbuf

from scummvm_gtk import __version__
from scummvm_gtk.games import (
    Game, get_all_games, download_icon, download_icon_async,
    get_icons_dir, KNOWN_GAMES, ALL_GENRES, SORT_OPTIONS,
    sort_games, load_settings, save_settings, load_library, save_library,
    toggle_favorite, is_favorite, record_play_start, record_play_end,
    get_total_play_time, get_last_played, format_play_time,
    fetch_wiki_description, get_scummvm_version,
    export_library_json, import_library_json, clear_cache,
)

TEXTDOMAIN = "scummvm-gtk"
gettext.textdomain(TEXTDOMAIN)
gettext.bindtextdomain(TEXTDOMAIN, "/usr/share/locale")
_ = gettext.gettext

APP_ID = "se.danielnylander.ScummvmGtk"


# ---------------------------------------------------------------------------
# GameCard  (features 6-star, 12-compat badge, 14-era badge)
# ---------------------------------------------------------------------------
class GameCard(Gtk.Box):
    """A card showing a game with icon and title."""

    def __init__(self, game, on_select=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.game = game
        self.on_select = on_select

        self.set_size_request(140, 190)
        self.add_css_class("card")
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_focusable(True)

        # Top row: era badge + fav star
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top_row.set_margin_start(4)
        top_row.set_margin_end(4)
        top_row.set_margin_top(4)

        # Era badge (feature 14)
        era = game.era_label()
        if era:
            era_lbl = Gtk.Label(label=era)
            era_lbl.add_css_class("caption")
            if era == _("80s"):
                era_lbl.add_css_class("accent")
            elif era == _("90s"):
                era_lbl.add_css_class("success")
            else:
                era_lbl.add_css_class("warning")
            top_row.append(era_lbl)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top_row.append(spacer)

        # Favorite star (feature 6)
        if is_favorite(game.game_id):
            star = Gtk.Image.new_from_icon_name("starred-symbolic")
            star.set_pixel_size(14)
            star.add_css_class("warning")
            top_row.append(star)

        self.append(top_row)

        # Icon placeholder
        self.icon_widget = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        self.icon_widget.set_pixel_size(96)
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

        # Bottom badges row
        badge_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        badge_row.set_halign(Gtk.Align.CENTER)
        badge_row.set_margin_bottom(4)

        # Installed indicator
        if game.installed:
            badge = Gtk.Label(label=_("Installed"))
            badge.add_css_class("success")
            badge.add_css_class("caption")
            badge_row.append(badge)

        # Compatibility badge (feature 12)
        if game.compatibility:
            compat = Gtk.Label(label=_(game.compatibility))
            compat.add_css_class("caption")
            if game.compatibility == "Excellent":
                compat.add_css_class("success")
            elif game.compatibility == "Good":
                compat.add_css_class("accent")
            badge_row.append(compat)

        self.append(badge_row)

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


# ---------------------------------------------------------------------------
# DetailPanel (features 1,4,6,7,9,12)
# ---------------------------------------------------------------------------
class DetailPanel(Gtk.Box):
    """Side panel showing detailed game info."""

    def __init__(self, app_window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(320, -1)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self._app_window = app_window

        # Icon — larger as screenshot placeholder (feature 4)
        self.icon = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        self.icon.set_pixel_size(192)
        self.append(self.icon)

        # Title
        self.title_label = Gtk.Label(label=_("Select a game"))
        self.title_label.add_css_class("title-1")
        self.title_label.set_wrap(True)
        self.title_label.set_halign(Gtk.Align.CENTER)
        self.append(self.title_label)

        # Favorite button (feature 6)
        self.fav_btn = Gtk.Button()
        self.fav_btn.set_halign(Gtk.Align.CENTER)
        self.fav_btn.add_css_class("flat")
        self.fav_btn.connect("clicked", self._on_toggle_favorite)
        self._update_fav_icon(False)
        self.append(self.fav_btn)

        # Compatibility badge (feature 12)
        self.compat_badge = Gtk.Label()
        self.compat_badge.set_halign(Gtk.Align.CENTER)
        self.compat_badge.add_css_class("heading")
        self.append(self.compat_badge)

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

        self.genre_row = Adw.ActionRow(title=_("Genre"))
        self.info_group.add(self.genre_row)

        self.id_row = Adw.ActionRow(title=_("Game ID"))
        self.info_group.add(self.id_row)

        # Play time row (feature 9)
        self.playtime_row = Adw.ActionRow(title=_("Play Time"))
        self.info_group.add(self.playtime_row)

        # Last played row (feature 7)
        self.lastplayed_row = Adw.ActionRow(title=_("Last Played"))
        self.info_group.add(self.lastplayed_row)

        self.append(self.info_group)

        # Description
        self.desc_label = Gtk.Label()
        self.desc_label.set_wrap(True)
        self.desc_label.set_halign(Gtk.Align.START)
        self.desc_label.add_css_class("body")
        self.desc_label.set_margin_top(8)
        self.append(self.desc_label)

        # Wikipedia description (feature 1)
        self.wiki_label = Gtk.Label()
        self.wiki_label.set_wrap(True)
        self.wiki_label.set_halign(Gtk.Align.START)
        self.wiki_label.add_css_class("body")
        self.wiki_label.add_css_class("dim-label")
        self.wiki_label.set_margin_top(4)
        self.append(self.wiki_label)

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

    def _update_fav_icon(self, is_fav):
        icon = "starred-symbolic" if is_fav else "non-starred-symbolic"
        self.fav_btn.set_icon_name(icon)
        tip = _("Remove from Favorites") if is_fav else _("Add to Favorites")
        self.fav_btn.set_tooltip_text(tip)

    def _on_toggle_favorite(self, btn):
        if self._current_game:
            now_fav = toggle_favorite(self._current_game.game_id)
            self._update_fav_icon(now_fav)
            if self._app_window:
                self._app_window._refresh_view()

    def show_game(self, game):
        self._current_game = game
        self.title_label.set_text(game.name)
        self.year_row.set_subtitle(game.year or _("Unknown"))
        self.company_row.set_subtitle(game.company or _("Unknown"))
        self.engine_row.set_subtitle(game.engine or _("Unknown"))
        self.platform_row.set_subtitle(game.platform or _("Unknown"))
        self.genre_row.set_subtitle(game.genre or _("Unknown"))
        self.id_row.set_subtitle(game.game_id)
        self.desc_label.set_text(game.description or "")
        self.launch_btn.set_sensitive(game.installed)

        # Favorite
        self._update_fav_icon(is_favorite(game.game_id))

        # Compatibility badge (feature 12)
        if game.compatibility:
            self.compat_badge.set_text(_("Compatibility: %s") % _(game.compatibility))
            self.compat_badge.set_visible(True)
            # Remove old CSS classes
            for c in ("success", "accent", "warning"):
                self.compat_badge.remove_css_class(c)
            if game.compatibility == "Excellent":
                self.compat_badge.add_css_class("success")
            elif game.compatibility == "Good":
                self.compat_badge.add_css_class("accent")
        else:
            self.compat_badge.set_visible(False)

        # Play time (feature 9)
        pt = get_total_play_time(game.game_id)
        self.playtime_row.set_subtitle(format_play_time(pt) if pt > 0 else _("Never"))

        # Last played (feature 7)
        lp = get_last_played(game.game_id)
        if lp > 0:
            import datetime
            dt = datetime.datetime.fromtimestamp(lp)
            self.lastplayed_row.set_subtitle(dt.strftime("%Y-%m-%d %H:%M"))
        else:
            self.lastplayed_row.set_subtitle(_("Never"))

        # Icon — larger (feature 4)
        icon_path = get_icons_dir() / f"{game.icon_name}.png"
        if icon_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), 192, 192, True)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.icon.set_from_paintable(texture)
            except Exception:
                self.icon.set_from_icon_name("applications-games-symbolic")
        else:
            self.icon.set_from_icon_name("applications-games-symbolic")

        # Wikipedia description (feature 1) — async
        self.wiki_label.set_text(_("Loading Wikipedia summary..."))

        def _on_wiki(text):
            GLib.idle_add(self.wiki_label.set_text, text or "")

        fetch_wiki_description(game.name, game.game_id, _on_wiki)

    def _on_launch(self, btn):
        if not self._current_game:
            return
        settings = load_settings()
        scummvm = settings.get("scummvm_path", "scummvm")
        cmd = [scummvm]
        if settings.get("launch_mode") == "fullscreen":
            cmd.append("--fullscreen")
        cmd.append(self._current_game.game_id)
        game_id = self._current_game.game_id
        try:
            record_play_start(game_id)
            proc = subprocess.Popen(cmd)

            def _wait():
                proc.wait()
                record_play_end(game_id)
                GLib.idle_add(self._refresh_playtime)

            threading.Thread(target=_wait, daemon=True).start()
        except FileNotFoundError:
            pass

    def _refresh_playtime(self):
        if self._current_game:
            pt = get_total_play_time(self._current_game.game_id)
            self.playtime_row.set_subtitle(format_play_time(pt) if pt > 0 else _("Never"))
            lp = get_last_played(self._current_game.game_id)
            if lp > 0:
                import datetime
                dt = datetime.datetime.fromtimestamp(lp)
                self.lastplayed_row.set_subtitle(dt.strftime("%Y-%m-%d %H:%M"))


# ---------------------------------------------------------------------------
# Settings window (feature 5)
# ---------------------------------------------------------------------------
class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app_window, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_("Settings"))
        self.set_transient_for(app_window)
        self.set_modal(True)
        self._app_window = app_window

        settings = load_settings()

        # General page
        page = Adw.PreferencesPage()
        page.set_title(_("General"))
        page.set_icon_name("preferences-system-symbolic")

        # Launch group
        launch_group = Adw.PreferencesGroup()
        launch_group.set_title(_("Launch"))

        # Launch mode
        self.launch_row = Adw.ComboRow(title=_("Launch Mode"))
        modes = Gtk.StringList.new([_("Windowed"), _("Fullscreen")])
        self.launch_row.set_model(modes)
        self.launch_row.set_selected(0 if settings.get("launch_mode") == "windowed" else 1)
        self.launch_row.connect("notify::selected", self._on_setting_changed)
        launch_group.add(self.launch_row)

        # ScummVM path
        self.path_row = Adw.EntryRow(title=_("ScummVM Path"))
        self.path_row.set_text(settings.get("scummvm_path", "scummvm"))
        self.path_row.connect("changed", self._on_setting_changed)
        launch_group.add(self.path_row)

        page.add(launch_group)

        # Sort group
        sort_group = Adw.PreferencesGroup()
        sort_group.set_title(_("Display"))

        self.sort_row = Adw.ComboRow(title=_("Default Sort"))
        sort_labels = Gtk.StringList.new([label for _, label in SORT_OPTIONS])
        self.sort_row.set_model(sort_labels)
        current_sort = settings.get("default_sort", "name_asc")
        sort_keys = [k for k, _ in SORT_OPTIONS]
        idx = sort_keys.index(current_sort) if current_sort in sort_keys else 0
        self.sort_row.set_selected(idx)
        self.sort_row.connect("notify::selected", self._on_setting_changed)
        sort_group.add(self.sort_row)

        page.add(sort_group)

        # Cover Art group
        art_group = Adw.PreferencesGroup()
        art_group.set_title(_("Cover Art"))
        art_group.set_description(_("Select sources for game cover art, screenshots and media"))

        self.art_source_row = Adw.ComboRow(title=_("Art Source"))
        art_sources = Gtk.StringList.new([
            _("ScummVM Icons (default)"),
            _("MobyGames"),
            _("IGDB"),
            _("TheGamesDB"),
            _("Local folder"),
        ])
        self.art_source_row.set_model(art_sources)
        art_source_keys = ["scummvm", "mobygames", "igdb", "thegamesdb", "local"]
        current_source = settings.get("art_source", "scummvm")
        art_idx = art_source_keys.index(current_source) if current_source in art_source_keys else 0
        self.art_source_row.set_selected(art_idx)
        self.art_source_row.connect("notify::selected", self._on_setting_changed)
        art_group.add(self.art_source_row)

        self.art_local_row = Adw.EntryRow(title=_("Local Art Folder"))
        self.art_local_row.set_text(settings.get("art_local_path", ""))
        self.art_local_row.connect("changed", self._on_setting_changed)
        art_group.add(self.art_local_row)

        self.fetch_screenshots_switch = Adw.SwitchRow(title=_("Fetch Screenshots"))
        self.fetch_screenshots_switch.set_subtitle(_("Download in-game screenshots when available"))
        self.fetch_screenshots_switch.set_active(settings.get("fetch_screenshots", False))
        self.fetch_screenshots_switch.connect("notify::active", self._on_setting_changed)
        art_group.add(self.fetch_screenshots_switch)

        self.fetch_covers_switch = Adw.SwitchRow(title=_("Fetch Cover Art"))
        self.fetch_covers_switch.set_subtitle(_("Download box art and cover images"))
        self.fetch_covers_switch.set_active(settings.get("fetch_covers", True))
        self.fetch_covers_switch.connect("notify::active", self._on_setting_changed)
        art_group.add(self.fetch_covers_switch)

        page.add(art_group)

        # Cache group
        cache_group = Adw.PreferencesGroup()
        cache_group.set_title(_("Cache"))

        clear_row = Adw.ActionRow(title=_("Clear Cache"))
        clear_row.set_subtitle(_("Remove downloaded icons and Wikipedia data"))
        clear_btn = Gtk.Button(label=_("Clear"))
        clear_btn.add_css_class("destructive-action")
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.connect("clicked", self._on_clear_cache)
        clear_row.add_suffix(clear_btn)
        cache_group.add(clear_row)

        page.add(cache_group)

        self.add(page)

    def _on_setting_changed(self, *_args):
        settings = load_settings()
        settings["launch_mode"] = "windowed" if self.launch_row.get_selected() == 0 else "fullscreen"
        settings["scummvm_path"] = self.path_row.get_text().strip() or "scummvm"
        sort_keys = [k for k, _ in SORT_OPTIONS]
        idx = self.sort_row.get_selected()
        settings["default_sort"] = sort_keys[idx] if idx < len(sort_keys) else "name_asc"
        art_source_keys = ["scummvm", "mobygames", "igdb", "thegamesdb", "local"]
        art_idx = self.art_source_row.get_selected()
        settings["art_source"] = art_source_keys[art_idx] if art_idx < len(art_source_keys) else "scummvm"
        settings["art_local_path"] = self.art_local_row.get_text().strip()
        settings["fetch_screenshots"] = self.fetch_screenshots_switch.get_active()
        settings["fetch_covers"] = self.fetch_covers_switch.get_active()
        save_settings(settings)

    def _on_clear_cache(self, btn):
        clear_cache()
        btn.set_label(_("Cleared!"))
        btn.set_sensitive(False)


# ---------------------------------------------------------------------------
# MainWindow — all features integrated
# ---------------------------------------------------------------------------
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_default_size(1200, 800)
        self.set_title(_("ScummVM GTK"))

        self._games = []
        self._filtered_games = []
        self._dark = False
        self._show_installed_only = False
        self._current_sort = load_settings().get("default_sort", "name_asc")
        self._current_genre_filter = ""
        self._group_by_engine = False
        self._favorites_first = False

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

        # Show installed only toggle (feature 3)
        self.installed_btn = Gtk.ToggleButton(icon_name="emblem-default-symbolic")
        self.installed_btn.set_tooltip_text(_("Show Installed Only"))
        self.installed_btn.connect("toggled", self._on_installed_toggled)
        header.pack_start(self.installed_btn)

        # Favorites first toggle (feature 6)
        self.favfirst_btn = Gtk.ToggleButton(icon_name="starred-symbolic")
        self.favfirst_btn.set_tooltip_text(_("Favorites First"))
        self.favfirst_btn.connect("toggled", self._on_favfirst_toggled)
        header.pack_start(self.favfirst_btn)

        # Sort dropdown (feature 2)
        sort_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sort_model = Gtk.StringList.new([label for _, label in SORT_OPTIONS])
        self.sort_dropdown = Gtk.DropDown(model=sort_model)
        sort_keys = [k for k, _ in SORT_OPTIONS]
        idx = sort_keys.index(self._current_sort) if self._current_sort in sort_keys else 0
        self.sort_dropdown.set_selected(idx)
        self.sort_dropdown.set_tooltip_text(_("Sort games"))
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        sort_box.append(self.sort_dropdown)
        header.pack_start(sort_box)

        # Genre filter dropdown (feature 8)
        genre_items = [_("All Genres")] + ALL_GENRES
        genre_model = Gtk.StringList.new(genre_items)
        self.genre_dropdown = Gtk.DropDown(model=genre_model)
        self.genre_dropdown.set_tooltip_text(_("Filter by genre"))
        self.genre_dropdown.connect("notify::selected", self._on_genre_changed)
        header.pack_start(self.genre_dropdown)

        # Theme toggle
        theme_btn = Gtk.Button(icon_name="weather-clear-night-symbolic")
        theme_btn.set_tooltip_text(_("Toggle Theme"))
        theme_btn.connect("clicked", self._toggle_theme)
        header.pack_end(theme_btn)
        self.theme_btn = theme_btn

        # Menu
        menu = Gio.Menu()
        menu.append(_("Scan for Games"), "win.scan")
        menu.append(_("Group by Engine"), "win.group-engine")
        menu.append(_("Export Library"), "win.export")
        menu.append(_("Import Library"), "win.import")
        menu.append(_("Settings"), "win.settings")
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
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_hexpand(True)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Container for grid or grouped view
        self.grid_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.grid_container.set_margin_top(12)
        self.grid_container.set_margin_bottom(12)
        self.grid_container.set_margin_start(12)
        self.grid_container.set_margin_end(12)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(6)
        self.flowbox.set_min_children_per_line(3)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_column_spacing(8)
        self.flowbox.set_row_spacing(8)
        self.grid_container.append(self.flowbox)

        self.scroll.set_child(self.grid_container)
        content_box.append(self.scroll)

        # Separator
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Detail panel (scrollable)
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.detail_panel = DetailPanel(app_window=self)
        detail_scroll.set_child(self.detail_panel)
        content_box.append(detail_scroll)

        main_box.append(content_box)

        # Status bar (feature 11 — ScummVM version)
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

        self.scummvm_version_label = Gtk.Label()
        self.scummvm_version_label.set_halign(Gtk.Align.END)
        self.scummvm_version_label.add_css_class("dim-label")
        self.scummvm_version_label.add_css_class("caption")
        status_box.append(self.scummvm_version_label)

        main_box.append(Gtk.Separator())
        main_box.append(status_box)

        # Actions
        scan_action = Gio.SimpleAction.new("scan", None)
        scan_action.connect("activate", self._on_scan)
        self.add_action(scan_action)

        settings_action = Gio.SimpleAction.new("settings", None)
        settings_action.connect("activate", self._on_open_settings)
        self.add_action(settings_action)

        export_action = Gio.SimpleAction.new("export", None)
        export_action.connect("activate", self._on_export)
        self.add_action(export_action)

        import_action = Gio.SimpleAction.new("import", None)
        import_action.connect("activate", self._on_import)
        self.add_action(import_action)

        group_engine_action = Gio.SimpleAction.new("group-engine", None)
        group_engine_action.connect("activate", self._on_toggle_group_engine)
        self.add_action(group_engine_action)

        # Keyboard navigation (feature 15)
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Drag and drop (feature 16)
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        self.add_controller(drop_target)

        # Load games
        self._load_games()

        # ScummVM version check (feature 11)
        self._check_scummvm_version()

    # -- Loading -----------------------------------------------------------
    def _load_games(self):
        settings = load_settings()
        scummvm = settings.get("scummvm_path", "scummvm")

        def do_load():
            games = get_all_games(scummvm)
            GLib.idle_add(self._on_games_loaded, games)

        thread = threading.Thread(target=do_load, daemon=True)
        thread.start()

    def _on_games_loaded(self, games):
        self._games = games
        self._apply_filters_and_sort()
        installed = sum(1 for g in games if g.installed)
        self.status_label.set_text(
            _("%d games (%d installed)") % (len(games), installed)
        )

    # -- Filtering / sorting / grouping ------------------------------------
    def _apply_filters_and_sort(self):
        games = list(self._games)

        # Installed filter (feature 3)
        if self._show_installed_only:
            games = [g for g in games if g.installed]

        # Genre filter (feature 8)
        if self._current_genre_filter:
            games = [g for g in games if g.genre == self._current_genre_filter]

        # Search
        query = self.search_entry.get_text().lower().strip()
        if query:
            games = [g for g in games
                     if query in g.name.lower()
                     or query in g.game_id.lower()
                     or query in (g.company or "").lower()
                     or query in (g.engine or "").lower()
                     or query in (g.genre or "").lower()]

        # Sort (feature 2)
        games = sort_games(games, self._current_sort, self._favorites_first)

        self._filtered_games = games

        # Group by engine (feature 13) or normal
        if self._group_by_engine:
            self._populate_grouped(games)
        else:
            self._populate(games)

        self.status_label.set_text(
            _("%d games shown") % len(games)
        )

    def _refresh_view(self):
        self._apply_filters_and_sort()

    def _populate(self, games):
        # Clear grid_container and re-add flowbox
        while True:
            child = self.grid_container.get_first_child()
            if child is None:
                break
            self.grid_container.remove(child)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(6)
        self.flowbox.set_min_children_per_line(3)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_column_spacing(8)
        self.flowbox.set_row_spacing(8)

        for game in games:
            card = GameCard(game, on_select=self._on_game_selected)
            self.flowbox.append(card)

        self.grid_container.append(self.flowbox)

    def _populate_grouped(self, games):
        """Group by engine with section headers (feature 13)."""
        while True:
            child = self.grid_container.get_first_child()
            if child is None:
                break
            self.grid_container.remove(child)

        # Group games by engine
        groups = {}
        for g in games:
            eng = g.engine or _("Unknown")
            groups.setdefault(eng, []).append(g)

        for engine_name in sorted(groups.keys()):
            engine_games = groups[engine_name]

            # Section header
            header = Gtk.Label(label=_("Engine: %s") % engine_name)
            header.add_css_class("title-3")
            header.set_halign(Gtk.Align.START)
            header.set_margin_top(16)
            header.set_margin_bottom(4)
            self.grid_container.append(header)

            sep = Gtk.Separator()
            self.grid_container.append(sep)

            fb = Gtk.FlowBox()
            fb.set_valign(Gtk.Align.START)
            fb.set_max_children_per_line(6)
            fb.set_min_children_per_line(3)
            fb.set_selection_mode(Gtk.SelectionMode.NONE)
            fb.set_homogeneous(True)
            fb.set_column_spacing(8)
            fb.set_row_spacing(8)
            for game in engine_games:
                card = GameCard(game, on_select=self._on_game_selected)
                fb.append(card)
            self.grid_container.append(fb)

    # -- Event handlers ----------------------------------------------------
    def _on_game_selected(self, game):
        self.detail_panel.show_game(game)

    def _on_search_toggled(self, btn):
        self.search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self.search_entry.grab_focus()

    def _on_search_changed(self, entry):
        self._apply_filters_and_sort()

    def _on_scan(self, action, param):
        self.status_label.set_text(_("Scanning for games..."))
        self._load_games()

    def _on_sort_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        sort_keys = [k for k, _ in SORT_OPTIONS]
        if idx < len(sort_keys):
            self._current_sort = sort_keys[idx]
            # Save preference (feature 2)
            settings = load_settings()
            settings["default_sort"] = self._current_sort
            save_settings(settings)
            self._apply_filters_and_sort()

    def _on_installed_toggled(self, btn):
        self._show_installed_only = btn.get_active()
        self._apply_filters_and_sort()

    def _on_favfirst_toggled(self, btn):
        self._favorites_first = btn.get_active()
        self._apply_filters_and_sort()

    def _on_genre_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if idx == 0:
            self._current_genre_filter = ""
        else:
            self._current_genre_filter = ALL_GENRES[idx - 1] if idx - 1 < len(ALL_GENRES) else ""
        self._apply_filters_and_sort()

    def _on_toggle_group_engine(self, action, param):
        self._group_by_engine = not self._group_by_engine
        self._apply_filters_and_sort()

    def _toggle_theme(self, btn):
        mgr = Adw.StyleManager.get_default()
        self._dark = not self._dark
        if self._dark:
            mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            btn.set_icon_name("weather-clear-symbolic")
        else:
            mgr.set_color_scheme(Adw.ColorScheme.DEFAULT)
            btn.set_icon_name("weather-clear-night-symbolic")

    # -- Settings (feature 5) ---------------------------------------------
    def _on_open_settings(self, action, param):
        win = SettingsWindow(self)
        win.present()

    # -- Export / Import (feature 10) --------------------------------------
    def _on_export(self, action, param):
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Export Library"))
        dialog.set_initial_name("scummvm-gtk-library.json")
        dialog.save(self, None, self._on_export_finish)

    def _on_export_finish(self, dialog, result):
        try:
            f = dialog.save_finish(result)
            if f:
                export_library_json(self._games, f.get_path())
        except Exception:
            pass

    def _on_import(self, action, param):
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Import Library"))
        json_filter = Gtk.FileFilter()
        json_filter.set_name(_("JSON files"))
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_import_finish)

    def _on_import_finish(self, dialog, result):
        try:
            f = dialog.open_finish(result)
            if f:
                custom = import_library_json(f.get_path())
                if custom:
                    lib = load_library()
                    existing = {cg["game_id"] for cg in lib.get("custom_games", [])}
                    for cg in custom:
                        if cg.get("game_id") and cg["game_id"] not in existing:
                            lib.setdefault("custom_games", []).append(cg)
                    save_library(lib)
                self._load_games()
        except Exception:
            pass

    # -- ScummVM version (feature 11) --------------------------------------
    def _check_scummvm_version(self):
        def _do():
            settings = load_settings()
            ver = get_scummvm_version(settings.get("scummvm_path", "scummvm"))
            GLib.idle_add(self.scummvm_version_label.set_text, ver or _("ScummVM not found"))

        threading.Thread(target=_do, daemon=True).start()

    # -- Keyboard navigation (feature 15) ----------------------------------
    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self.search_bar.get_search_mode():
                self.search_btn.set_active(False)
                return True
        elif keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            # Launch focused card's game if detail panel has a game
            if self.detail_panel._current_game and self.detail_panel._current_game.installed:
                self.detail_panel._on_launch(None)
                return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_Down):
            # Let flowbox handle arrow navigation when it has focus
            child = self.flowbox.get_focus_child()
            if child is None:
                first = self.flowbox.get_first_child()
                if first:
                    first.get_first_child().grab_focus()
                return True
        return False

    # -- Drag and drop (feature 16) ----------------------------------------
    def _on_drop(self, target, value, x, y):
        if not isinstance(value, Gdk.FileList):
            return False
        files = value.get_files()
        lib = load_library()
        custom = lib.setdefault("custom_games", [])
        existing_ids = {cg["game_id"] for cg in custom}
        added = 0
        for f in files:
            path = f.get_path()
            if path and os.path.isdir(path):
                folder_name = os.path.basename(path)
                game_id = folder_name.lower().replace(" ", "_")
                if game_id not in existing_ids:
                    g = Game(
                        game_id=game_id,
                        name=folder_name,
                        path=path,
                        installed=True,
                    )
                    custom.append(g.to_dict())
                    existing_ids.add(game_id)
                    added += 1
        if added:
            save_library(lib)
            self._load_games()
        return True


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = MainWindow(application=self)
        window.present()
        # Welcome dialog
        settings = load_settings()
        if not settings.get("welcome_shown"):
            self._show_welcome(window)

    def _show_welcome(self, win):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(500)
        dialog.set_content_height(580)
        page = Adw.StatusPage()
        page.set_icon_name("applications-games-symbolic")
        page.set_title(_("Welcome to ScummVM Launcher"))
        page.set_description(_(
            "Launch and manage ScummVM games.\n\n"
            "\u2713 Browse your game collection\n"
            "\u2713 Grid view with cover art\n"
            "\u2713 Quick launch\n"
            "\u2713 Favorites and play time tracking\n"
            "\u2713 Wikipedia game descriptions"
        ))
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
        settings = load_settings()
        settings["welcome_shown"] = True
        save_settings(settings)
        dialog.close()

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
            copyright="\u00a9 2026 Daniel Nylander",
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
