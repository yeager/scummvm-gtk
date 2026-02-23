"""ScummVM game database — metadata, icons, wiki, and detection."""

import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import gettext
_ = gettext.gettext

ICON_BASE_URL = "https://raw.githubusercontent.com/scummvm/scummvm-icons/main/icons"
WIKI_API = "https://en.wikipedia.org/w/api.php"

# ─── Sort options (feature 2) ──────────────────────────────────────────
SORT_OPTIONS = [
    ("name_asc", _("Name (A-Z)")),
    ("name_desc", _("Name (Z-A)")),
    ("year_asc", _("Year (oldest)")),
    ("year_desc", _("Year (newest)")),
    ("developer_asc", _("Developer (A-Z)")),
    ("engine_asc", _("Engine (A-Z)")),
]

# ─── Genre list (feature 8) ────────────────────────────────────────────
ALL_GENRES = ["Adventure", "Puzzle", "RPG", "Action", "Strategy"]

# Translatable compatibility ratings — these are used via _(game.compatibility)
# xgettext markers (not called at import, just for string extraction):
if False:
    _("Excellent")
    _("Good")
    _("Fair")
    _("Poor")


def get_cache_dir():
    p = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "scummvm-gtk"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_icons_dir():
    p = get_cache_dir() / "icons"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_wiki_dir():
    p = get_cache_dir() / "wiki"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_covers_dir():
    p = get_cache_dir() / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_dir():
    p = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "scummvm-gtk"
    p.mkdir(parents=True, exist_ok=True)
    return p


class Game:
    """Represents a ScummVM game."""
    def __init__(self, game_id, name, engine="", description="",
                 year="", company="", platform="", path="",
                 icon_name="", installed=False, genre="",
                 compatibility="", wiki_title=""):
        self.game_id = game_id
        self.name = name
        self.engine = engine
        self.description = description
        self.year = year
        self.company = company
        self.platform = platform
        self.path = path
        self.icon_name = icon_name or game_id
        self.installed = installed
        self.genre = genre
        self.compatibility = compatibility
        self.wiki_title = wiki_title or name
        # Runtime data (loaded from library.json)
        self.favorite = False
        self.last_played = 0
        self.total_play_time = 0  # seconds

    @property
    def era(self):
        if self.year:
            try:
                y = int(self.year)
                if y < 1990:
                    return "80s"
                elif y < 2000:
                    return "90s"
                else:
                    return "00s"
            except ValueError:
                pass
        return ""

    def era_label(self):
        return self.era

    def to_dict(self):
        return {
            "game_id": self.game_id, "name": self.name,
            "engine": self.engine, "description": self.description,
            "year": self.year, "company": self.company,
            "platform": self.platform, "path": self.path,
            "icon_name": self.icon_name, "installed": self.installed,
            "genre": self.genre, "compatibility": self.compatibility,
            "wiki_title": self.wiki_title,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__init__.__code__.co_varnames})


# ─── Settings & Library ───────────────────────────────────────────────

def load_settings():
    p = get_config_dir() / "settings.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "sort_by": "name_asc",
        "launch_mode": "windowed",
        "scummvm_path": "scummvm",
        "show_installed_only": False,
        "favorites_first": True,
    }


def save_settings(s):
    p = get_config_dir() / "settings.json"
    with open(p, "w") as f:
        json.dump(s, f, indent=2)


def load_library():
    p = get_config_dir() / "library.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {"games": {}, "custom_games": []}


def save_library(lib):
    p = get_config_dir() / "library.json"
    with open(p, "w") as f:
        json.dump(lib, f, indent=2)


def export_library(path):
    lib = load_library()
    with open(path, "w") as f:
        json.dump(lib, f, indent=2)


def import_library(path):
    with open(path) as f:
        lib = json.load(f)
    save_library(lib)
    return lib


# ─── Wikipedia ─────────────────────────────────────────────────────────

def fetch_wiki_extract(title, callback=None):
    """Fetch Wikipedia intro extract for a game. Cached."""
    safe_name = title.replace("/", "_").replace(" ", "_")
    cache_path = get_wiki_dir() / f"{safe_name}.txt"
    if cache_path.exists():
        text = cache_path.read_text()
        if callback:
            callback(text)
        return text

    try:
        import urllib.parse
        params = urllib.parse.urlencode({
            "action": "query", "prop": "extracts",
            "exintro": "1", "explaintext": "1",
            "titles": title, "format": "json",
        })
        url = f"{WIKI_API}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ScummVM-GTK/0.2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            extract = page.get("extract", "")
            if extract:
                cache_path.write_text(extract)
                if callback:
                    callback(extract)
                return extract
    except Exception:
        pass
    if callback:
        callback("")
    return ""


def fetch_wiki_async(title, callback):
    threading.Thread(target=fetch_wiki_extract, args=(title, callback), daemon=True).start()


# ─── Icons ──────────────────────────────────────────────────────────────

def download_icon(game_id, callback=None):
    dest = get_icons_dir() / f"{game_id}.png"
    if dest.exists():
        if callback:
            callback(str(dest))
        return str(dest)
    url = f"{ICON_BASE_URL}/{game_id}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ScummVM-GTK/0.2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            with open(dest, "wb") as f:
                f.write(resp.read())
        if callback:
            callback(str(dest))
        return str(dest)
    except Exception:
        if callback:
            callback(None)
        return None


def download_icon_async(game_id, callback):
    threading.Thread(target=download_icon, args=(game_id, callback), daemon=True).start()


# ─── Cover Art ──────────────────────────────────────────────────────────

def generate_placeholder_cover(game_name, cover_path):
    """Generate a placeholder cover with game name if no cover art is found."""
    try:
        import gi
        gi.require_version("Cairo", "1.0")
        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Cairo, Pango, PangoCairo
        
        # Create a 300x400 image (typical cover ratio)
        WIDTH, HEIGHT = 300, 400
        surface = Cairo.ImageSurface(Cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
        ctx = Cairo.Context(surface)
        
        # Background gradient (dark to light)
        gradient = Cairo.LinearGradient(0, 0, 0, HEIGHT)
        gradient.add_color_stop_rgb(0, 0.2, 0.25, 0.3)  # Dark blue
        gradient.add_color_stop_rgb(1, 0.4, 0.45, 0.5)  # Light blue
        ctx.set_source(gradient)
        ctx.rectangle(0, 0, WIDTH, HEIGHT)
        ctx.fill()
        
        # Border
        ctx.set_source_rgb(0.6, 0.6, 0.7)
        ctx.set_line_width(2)
        ctx.rectangle(1, 1, WIDTH-2, HEIGHT-2)
        ctx.stroke()
        
        # Text setup
        layout = PangoCairo.create_layout(ctx)
        font_desc = Pango.FontDescription.from_string("Sans Bold 24")
        layout.set_font_description(font_desc)
        layout.set_width((WIDTH - 40) * Pango.SCALE)
        layout.set_alignment(Pango.Alignment.CENTER)
        layout.set_wrap(Pango.WrapMode.WORD)
        
        # Game name text
        layout.set_text(game_name)
        text_width, text_height = layout.get_pixel_size()
        
        # Position text in center
        ctx.move_to(20, (HEIGHT - text_height) / 2)
        ctx.set_source_rgb(1.0, 1.0, 1.0)  # White text
        PangoCairo.show_layout(ctx, layout)
        
        # Add "ScummVM" at bottom
        small_font = Pango.FontDescription.from_string("Sans 12")
        layout.set_font_description(small_font)
        layout.set_text("ScummVM")
        small_width, small_height = layout.get_pixel_size()
        ctx.move_to((WIDTH - small_width) / 2, HEIGHT - 40)
        ctx.set_source_rgb(0.8, 0.8, 0.8)  # Light gray
        PangoCairo.show_layout(ctx, layout)
        
        # Save as PNG
        surface.write_to_png(str(cover_path))
        return True
    except Exception:
        return False


def search_mobygames_cover(game_name, callback=None):
    """Search for cover art on MobyGames (simplified approach)."""
    try:
        import urllib.parse
        
        # Search MobyGames for the game
        search_query = urllib.parse.quote(game_name)
        search_url = f"https://www.mobygames.com/search/?q={search_query}&type=game"
        
        req = urllib.request.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ScummVM-GTK/0.2.3"
        })
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8')
        
        # Look for cover art URL in the HTML (basic regex approach)
        import re
        
        # Try to find cover image URLs
        cover_patterns = [
            r'src="(https://cdn\.mobygames\.com/covers/[^"]*\.jpg)"',
            r'src="(https://cdn\.mobygames\.com/covers/[^"]*\.png)"',
            r'href="([^"]*covers/[^"]*\.jpg)"',
            r'href="([^"]*covers/[^"]*\.png)"'
        ]
        
        for pattern in cover_patterns:
            matches = re.findall(pattern, html)
            if matches:
                # Return the first valid cover URL found
                cover_url = matches[0]
                if not cover_url.startswith('http'):
                    cover_url = 'https://www.mobygames.com' + cover_url
                if callback:
                    callback(cover_url)
                return cover_url
                
    except Exception:
        pass
    
    if callback:
        callback(None)
    return None


def download_cover(game, callback=None):
    """Download cover art for a game, with fallback to placeholder."""
    covers_dir = get_covers_dir()
    cover_path = covers_dir / f"{game.game_id}.png"
    
    # Return cached cover if exists
    if cover_path.exists():
        if callback:
            callback(str(cover_path))
        return str(cover_path)
    
    # Try to find cover art online
    cover_url = search_mobygames_cover(game.name)
    
    if cover_url:
        try:
            req = urllib.request.Request(cover_url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ScummVM-GTK/0.2.3"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(cover_path, "wb") as f:
                    f.write(resp.read())
            if callback:
                callback(str(cover_path))
            return str(cover_path)
        except Exception:
            pass
    
    # Fallback: generate placeholder
    if generate_placeholder_cover(game.name, cover_path):
        if callback:
            callback(str(cover_path))
        return str(cover_path)
    
    # Ultimate fallback: return None (will use icon)
    if callback:
        callback(None)
    return None


def download_cover_async(game, callback):
    """Download cover art asynchronously."""
    threading.Thread(target=download_cover, args=(game, callback), daemon=True).start()


def clear_covers_cache():
    """Clear all cached cover art."""
    covers_dir = get_covers_dir()
    for cover_file in covers_dir.glob("*.png"):
        try:
            cover_file.unlink()
        except Exception:
            pass
    for cover_file in covers_dir.glob("*.jpg"):
        try:
            cover_file.unlink()
        except Exception:
            pass


# ─── ScummVM detection ──────────────────────────────────────────────────

def get_scummvm_version(scummvm_path="scummvm"):
    try:
        r = subprocess.run([scummvm_path, "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "ScummVM" in line:
                    return line.strip()
    except Exception:
        pass
    return None


def detect_installed_games(scummvm_path="scummvm"):
    games = []
    try:
        result = subprocess.run(
            [scummvm_path, "--list-targets"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 2:
                    game_id = parts[0]
                    name = ' '.join(parts[1:])
                    games.append(Game(game_id, name, installed=True))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return games


# ─── Known games database ──────────────────────────────────────────────

KNOWN_GAMES = [
    Game("monkey", "The Secret of Monkey Island", "scumm",
         "A young man named Guybrush Threepwood arrives on Mêlée Island with the dream of becoming a pirate.",
         "1990", "LucasArts", "DOS/Amiga/FM-Towns", genre="Adventure",
         compatibility="Excellent", wiki_title="The Secret of Monkey Island"),
    Game("monkey2", "Monkey Island 2: LeChuck's Revenge", "scumm",
         "Guybrush Threepwood tells the tale of his search for the legendary treasure of Big Whoop.",
         "1991", "LucasArts", "DOS/Amiga/FM-Towns", genre="Adventure",
         compatibility="Excellent", wiki_title="Monkey Island 2: LeChuck's Revenge"),
    Game("atlantis", "Indiana Jones and the Fate of Atlantis", "scumm",
         "Indiana Jones must stop the Nazis from harnessing the power of Atlantis.",
         "1992", "LucasArts", "DOS/Amiga/FM-Towns", genre="Adventure",
         compatibility="Excellent", wiki_title="Indiana Jones and the Fate of Atlantis"),
    Game("tentacle", "Day of the Tentacle", "scumm",
         "Purple Tentacle drinks toxic sludge and becomes evil. Bernard, Hoagie and Laverne must stop him across time.",
         "1993", "LucasArts", "DOS", genre="Adventure",
         compatibility="Excellent", wiki_title="Day of the Tentacle"),
    Game("samnmax", "Sam & Max Hit the Road", "scumm",
         "Sam & Max investigate a missing bigfoot from a carnival freak show.",
         "1993", "LucasArts", "DOS", genre="Adventure",
         compatibility="Excellent", wiki_title="Sam & Max Hit the Road"),
    Game("dig", "The Dig", "scumm",
         "An asteroid threatens Earth. A team sent to divert it discovers an alien world.",
         "1995", "LucasArts", "DOS", genre="Adventure",
         compatibility="Excellent", wiki_title="The Dig (video game)"),
    Game("ft", "Full Throttle", "scumm",
         "Ben, leader of the Polecats biker gang, is framed for murder.",
         "1995", "LucasArts", "DOS", genre="Adventure",
         compatibility="Excellent", wiki_title="Full Throttle (1995 video game)"),
    Game("comi", "The Curse of Monkey Island", "scumm",
         "Guybrush accidentally places a cursed ring on Elaine's finger and must find the cure.",
         "1997", "LucasArts", "Windows", genre="Adventure",
         compatibility="Excellent", wiki_title="The Curse of Monkey Island"),
    Game("grim", "Grim Fandango", "grim",
         "Manny Calavera, a travel agent in the Land of the Dead, uncovers a conspiracy.",
         "1998", "LucasArts", "Windows", genre="Adventure",
         compatibility="Good", wiki_title="Grim Fandango"),
    Game("maniac", "Maniac Mansion", "scumm",
         "Dave and friends infiltrate a mad scientist's mansion to rescue Sandy.",
         "1987", "LucasArts", "C64/DOS/NES", genre="Adventure",
         compatibility="Excellent", wiki_title="Maniac Mansion"),
    Game("loom", "Loom", "scumm",
         "Bobbin Threadbare, a young Weaver, must unravel the mystery of the Great Loom.",
         "1990", "LucasArts", "DOS/FM-Towns", genre="Adventure",
         compatibility="Excellent", wiki_title="Loom (video game)"),
    Game("zak", "Zak McKracken and the Alien Mindbenders", "scumm",
         "Tabloid journalist Zak McKracken stumbles upon an alien conspiracy.",
         "1988", "LucasArts", "C64/DOS/FM-Towns", genre="Adventure",
         compatibility="Excellent", wiki_title="Zak McKracken and the Alien Mindbenders"),
    Game("sky", "Beneath a Steel Sky", "sky",
         "Robert Foster escapes Union City's oppressive regime with his robot companion Joey.",
         "1994", "Revolution", "DOS/Amiga", genre="Adventure",
         compatibility="Excellent", wiki_title="Beneath a Steel Sky"),
    Game("sword1", "Broken Sword: Shadow of the Templars", "sword1",
         "George Stobbart investigates a bombing in Paris linked to the Knights Templar.",
         "1996", "Revolution", "DOS/Windows/PS1", genre="Adventure",
         compatibility="Excellent", wiki_title="Broken Sword: The Shadow of the Templars"),
    Game("sword2", "Broken Sword II: The Smoking Mirror", "sword2",
         "George and Nico investigate a drug lord's connection to a Mayan prophecy.",
         "1997", "Revolution", "Windows/PS1", genre="Adventure",
         compatibility="Good", wiki_title="Broken Sword II: The Smoking Mirror"),
    Game("queen", "Flight of the Amazon Queen", "queen",
         "Pilot Joe King crash-lands in the Amazon and must stop a mad scientist.",
         "1995", "Interactive Binary Illusions", "DOS/Amiga", genre="Adventure",
         compatibility="Excellent", wiki_title="Flight of the Amazon Queen"),
    Game("simon1", "Simon the Sorcerer", "agos",
         "Simon is transported to a fantasy world and must rescue a wizard from an evil sorcerer.",
         "1993", "Adventure Soft", "DOS/Amiga", genre="Adventure",
         compatibility="Excellent", wiki_title="Simon the Sorcerer"),
    Game("simon2", "Simon the Sorcerer II", "agos",
         "Simon returns to the fantasy world and must stop the evil sorcerer Sordid again.",
         "1995", "Adventure Soft", "DOS/Windows", genre="Adventure",
         compatibility="Good", wiki_title="Simon the Sorcerer II: The Lion, the Wizard and the Wardrobe"),
    Game("kyra1", "The Legend of Kyrandia", "kyra",
         "Brandon must stop the evil jester Malcolm who has turned the land to stone.",
         "1992", "Westwood Studios", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="The Legend of Kyrandia"),
    Game("kyra2", "The Legend of Kyrandia: Hand of Fate", "kyra",
         "Zanthia must find an anchor stone to stop the land from disappearing.",
         "1993", "Westwood Studios", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="The Legend of Kyrandia: Hand of Fate"),
    Game("kyra3", "The Legend of Kyrandia: Malcolm's Revenge", "kyra",
         "Malcolm escapes prison and must clear his name.",
         "1994", "Westwood Studios", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="The Legend of Kyrandia: Malcolm's Revenge"),
    Game("lure", "Lure of the Temptress", "lure",
         "Diermot must free the town of Turnvale from the enchantress Selena.",
         "1992", "Revolution", "DOS/Amiga", genre="Adventure",
         compatibility="Good", wiki_title="Lure of the Temptress"),
    Game("touche", "Touché: The Adventures of the Fifth Musketeer", "touche",
         "Geoffroi Le Bansen seeks to become the Fifth Musketeer.",
         "1995", "Clipper Software", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="Touché: The Adventures of the Fifth Musketeer"),
    Game("drascula", "Drascula: The Vampire Strikes Back", "drascula",
         "John Hacker must rescue his girlfriend from the vampire Drascula.",
         "1996", "Alcachofa Soft", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="Drascula: The Vampire Strikes Back"),
    Game("myst", "Myst", "mohawk",
         "Explore the mysterious island of Myst and unravel its secrets.",
         "1993", "Cyan", "Mac/Windows", genre="Puzzle",
         compatibility="Good", wiki_title="Myst"),
    Game("riven", "Riven: The Sequel to Myst", "mohawk",
         "Continue the story on the Age of Riven.",
         "1997", "Cyan", "Mac/Windows", genre="Puzzle",
         compatibility="Good", wiki_title="Riven"),
    Game("agi-fanmade", "AGI Fan Games", "agi",
         "Fan-made games using the AGI engine.",
         "", "Various", "DOS", genre="Adventure",
         compatibility="Good"),
    Game("sci-fanmade", "SCI Fan Games", "sci",
         "Fan-made games using the SCI engine.",
         "", "Various", "DOS", genre="Adventure",
         compatibility="Good"),
    Game("bass", "Beneath a Steel Sky (Remastered)", "sky",
         "Remastered version with enhanced audio and graphics.",
         "2009", "Revolution", "iOS/Android", genre="Adventure",
         compatibility="Good"),
    Game("dreamweb", "DreamWeb", "dreamweb",
         "Ryan must prevent the Apocalypse in this cyberpunk adventure.",
         "1994", "Creative Reality", "DOS", genre="Adventure",
         compatibility="Good", wiki_title="DreamWeb"),
]


def get_all_games(scummvm_path="scummvm"):
    known = {g.game_id: g for g in KNOWN_GAMES}

    # Load library data (favorites, play times)
    lib = load_library()
    game_data = lib.get("games", {})

    # Add custom games
    for cg in lib.get("custom_games", []):
        gid = cg.get("game_id")
        if gid and gid not in known:
            known[gid] = Game.from_dict(cg)

    installed = detect_installed_games(scummvm_path)
    for g in installed:
        if g.game_id in known:
            known[g.game_id].installed = True
            known[g.game_id].path = g.path
        else:
            known[g.game_id] = g

    # Apply library data
    for gid, game in known.items():
        gd = game_data.get(gid, {})
        game.favorite = gd.get("favorite", False)
        game.last_played = gd.get("last_played", 0)
        game.total_play_time = gd.get("total_play_time", 0)

    return sorted(known.values(), key=lambda g: g.name)


def get_covers_dir():
    p = get_cache_dir() / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_screenshots_dir():
    p = get_cache_dir() / "screenshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─── Cover Art Sources ──────────────────────────────────────────────────

# MobyGames mapping: game_id → MobyGames slug
MOBYGAMES_SLUGS = {
    "monkey": "secret-of-monkey-island", "monkey2": "monkey-island-2-lechucks-revenge",
    "atlantis": "indiana-jones-and-the-fate-of-atlantis", "tentacle": "maniac-mansion-day-of-the-tentacle",
    "samnmax": "sam-max-hit-the-road", "dig": "dig", "ft": "full-throttle",
    "comi": "curse-of-monkey-island", "grim": "grim-fandango",
    "maniac": "maniac-mansion", "loom": "loom", "zak": "zak-mckracken-and-the-alien-mindbenders",
    "sky": "beneath-a-steel-sky", "sword1": "broken-sword-shadow-of-the-templars",
    "sword2": "broken-sword-ii-the-smoking-mirror", "queen": "flight-of-the-amazon-queen",
    "simon1": "simon-the-sorcerer", "simon2": "simon-the-sorcerer-ii-the-lion-the-wizard-and-the-wardrobe",
    "myst": "myst", "riven": "riven-the-sequel-to-myst", "dreamweb": "dreamweb",
}


def fetch_cover_art(game_id, source="scummvm", callback=None):
    """Fetch cover art from the selected source. Returns path to image or None."""
    dest = get_covers_dir() / f"{game_id}_{source}.jpg"
    if dest.exists():
        if callback:
            callback(str(dest))
        return str(dest)

    url = None
    if source == "scummvm":
        # Use the standard ScummVM icon (already handled by download_icon)
        return download_icon(game_id, callback)

    elif source == "mobygames":
        slug = MOBYGAMES_SLUGS.get(game_id)
        if slug:
            # MobyGames cover art (public, no API key needed for thumbnails)
            url = f"https://www.mobygames.com/game/{slug}/cover/coverart"

    elif source == "igdb":
        # IGDB requires auth — placeholder for future API integration
        pass

    elif source == "thegamesdb":
        # TheGamesDB — free API, covers available
        try:
            search_url = f"https://cdn.thegamesdb.net/images/original/boxart/front/{game_id}-1.jpg"
            url = search_url
        except Exception:
            pass

    elif source == "local":
        settings = load_settings()
        local_path = Path(settings.get("art_local_path", ""))
        if local_path.is_dir():
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                candidate = local_path / f"{game_id}{ext}"
                if candidate.exists():
                    if callback:
                        callback(str(candidate))
                    return str(candidate)

    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ScummVM-GTK/0.2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 1000:  # sanity check
                    with open(dest, "wb") as f:
                        f.write(data)
                    if callback:
                        callback(str(dest))
                    return str(dest)
        except Exception:
            pass

    if callback:
        callback(None)
    return None


def fetch_cover_art_async(game_id, source, callback):
    threading.Thread(target=fetch_cover_art, args=(game_id, source, callback), daemon=True).start()


def fetch_screenshot(game_id, source="scummvm", callback=None):
    """Fetch in-game screenshot if available."""
    dest = get_screenshots_dir() / f"{game_id}_{source}.jpg"
    if dest.exists():
        if callback:
            callback(str(dest))
        return str(dest)

    # ScummVM wiki has screenshots for many games
    if source == "scummvm":
        url = f"https://www.scummvm.org/data/screenshots/{game_id}/scummvm-{game_id}-0.jpg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ScummVM-GTK/0.2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 1000:
                    with open(dest, "wb") as f:
                        f.write(data)
                    if callback:
                        callback(str(dest))
                    return str(dest)
        except Exception:
            pass

    if callback:
        callback(None)
    return None


def fetch_screenshot_async(game_id, source, callback):
    threading.Thread(target=fetch_screenshot, args=(game_id, source, callback), daemon=True).start()


def clear_cache():
    """Clear wiki, icon, cover and screenshot caches."""
    import shutil
    for d in [get_wiki_dir(), get_icons_dir(), get_covers_dir(), get_screenshots_dir()]:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)


# ─── Sorting (feature 2) ───────────────────────────────────────────────

def sort_games(games, sort_key="name_asc", favorites_first=False):
    """Sort games by key. Optionally put favorites first."""
    def _key(g):
        if sort_key == "name_asc":
            return g.name.lower()
        elif sort_key == "name_desc":
            return g.name.lower()
        elif sort_key == "year_asc":
            return g.year or "9999"
        elif sort_key == "year_desc":
            return g.year or "0000"
        elif sort_key == "developer_asc":
            return (g.company or "").lower()
        elif sort_key == "engine_asc":
            return (g.engine or "").lower()
        return g.name.lower()

    reverse = sort_key in ("name_desc", "year_desc")
    result = sorted(games, key=_key, reverse=reverse)

    if favorites_first:
        favs = [g for g in result if is_favorite(g.game_id)]
        non_favs = [g for g in result if not is_favorite(g.game_id)]
        result = favs + non_favs

    return result


# ─── Favorites (feature 6) ─────────────────────────────────────────────

def is_favorite(game_id):
    lib = load_library()
    return lib.get("games", {}).get(game_id, {}).get("favorite", False)


def toggle_favorite(game_id):
    lib = load_library()
    games = lib.setdefault("games", {})
    gd = games.setdefault(game_id, {})
    gd["favorite"] = not gd.get("favorite", False)
    save_library(lib)
    return gd["favorite"]


# ─── Play time tracking (features 7, 9) ────────────────────────────────

def record_play_start(game_id):
    lib = load_library()
    games = lib.setdefault("games", {})
    gd = games.setdefault(game_id, {})
    gd["play_start"] = time.time()
    save_library(lib)


def record_play_end(game_id):
    lib = load_library()
    games = lib.setdefault("games", {})
    gd = games.setdefault(game_id, {})
    start = gd.pop("play_start", 0)
    if start:
        elapsed = time.time() - start
        gd["total_play_time"] = gd.get("total_play_time", 0) + elapsed
    gd["last_played"] = time.time()
    save_library(lib)


def get_total_play_time(game_id):
    lib = load_library()
    return lib.get("games", {}).get(game_id, {}).get("total_play_time", 0)


def get_last_played(game_id):
    lib = load_library()
    return lib.get("games", {}).get(game_id, {}).get("last_played", 0)


def format_play_time(seconds):
    """Format seconds into human-readable play time."""
    if seconds < 60:
        return _("%d seconds") % int(seconds)
    elif seconds < 3600:
        return _("%d minutes") % int(seconds / 60)
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        if mins:
            return _("%dh %dm") % (hours, mins)
        return _("%d hours") % hours


# ─── Wikipedia description (feature 1) ─────────────────────────────────

def fetch_wiki_description(game_name, game_id, callback):
    """Fetch Wikipedia description async with cache."""
    # Look up wiki_title from KNOWN_GAMES
    wiki_title = game_name
    for g in KNOWN_GAMES:
        if g.game_id == game_id and g.wiki_title:
            wiki_title = g.wiki_title
            break
    fetch_wiki_async(wiki_title, callback)


# ─── Export / Import (feature 10) ──────────────────────────────────────

def export_library_json(games, path):
    """Export full library with game metadata."""
    lib = load_library()
    data = {
        "library": lib,
        "games": [g.to_dict() for g in games],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def import_library_json(path):
    """Import library JSON, return list of custom game dicts."""
    try:
        with open(path) as f:
            data = json.load(f)
        # Import library data (favorites, play times)
        if "library" in data:
            lib = load_library()
            imported_games = data["library"].get("games", {})
            lib.setdefault("games", {}).update(imported_games)
            save_library(lib)
        # Return custom games for merging
        return data.get("games", [])
    except Exception:
        return []
