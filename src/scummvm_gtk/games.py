"""ScummVM game database — metadata, icons, and detection."""

import json
import os
import subprocess
import threading
import urllib.request
from pathlib import Path

import gettext
_ = gettext.gettext

ICON_BASE_URL = "https://raw.githubusercontent.com/scummvm/scummvm-icons/main/icons"

# Cache dir for downloaded icons and metadata
def get_cache_dir():
    p = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "scummvm-gtk"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_icons_dir():
    p = get_cache_dir() / "icons"
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
                 icon_name="", installed=False):
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

    def to_dict(self):
        return {
            "game_id": self.game_id,
            "name": self.name,
            "engine": self.engine,
            "description": self.description,
            "year": self.year,
            "company": self.company,
            "platform": self.platform,
            "path": self.path,
            "icon_name": self.icon_name,
            "installed": self.installed,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


# Well-known ScummVM games with metadata
KNOWN_GAMES = [
    Game("monkey", "The Secret of Monkey Island", "scumm", 
         "A young man named Guybrush Threepwood arrives on Mêlée Island with the dream of becoming a pirate.",
         "1990", "LucasArts", "DOS/Amiga/FM-Towns"),
    Game("monkey2", "Monkey Island 2: LeChuck's Revenge", "scumm",
         "Guybrush Threepwood tells the tale of his search for the legendary treasure of Big Whoop.",
         "1991", "LucasArts", "DOS/Amiga/FM-Towns"),
    Game("atlantis", "Indiana Jones and the Fate of Atlantis", "scumm",
         "Indiana Jones must stop the Nazis from harnessing the power of Atlantis.",
         "1992", "LucasArts", "DOS/Amiga/FM-Towns"),
    Game("tentacle", "Day of the Tentacle", "scumm",
         "Purple Tentacle drinks toxic sludge and becomes evil. Bernard, Hoagie and Laverne must stop him across time.",
         "1993", "LucasArts", "DOS"),
    Game("samnmax", "Sam & Max Hit the Road", "scumm",
         "Sam & Max investigate a missing bigfoot from a carnival freak show.",
         "1993", "LucasArts", "DOS"),
    Game("dig", "The Dig", "scumm",
         "An asteroid threatens Earth. A team sent to divert it discovers an alien world.",
         "1995", "LucasArts", "DOS"),
    Game("ft", "Full Throttle", "scumm",
         "Ben, leader of the Polecats biker gang, is framed for murder.",
         "1995", "LucasArts", "DOS"),
    Game("comi", "The Curse of Monkey Island", "scumm",
         "Guybrush accidentally places a cursed ring on Elaine's finger and must find the cure.",
         "1997", "LucasArts", "Windows"),
    Game("grim", "Grim Fandango", "grim",
         "Manny Calavera, a travel agent in the Land of the Dead, uncovers a conspiracy.",
         "1998", "LucasArts", "Windows"),
    Game("maniac", "Maniac Mansion", "scumm",
         "Dave and friends infiltrate a mad scientist's mansion to rescue Sandy.",
         "1987", "LucasArts", "C64/DOS/NES"),
    Game("loom", "Loom", "scumm",
         "Bobbin Threadbare, a young Weaver, must unravel the mystery of the Great Loom.",
         "1990", "LucasArts", "DOS/FM-Towns"),
    Game("zak", "Zak McKracken and the Alien Mindbenders", "scumm",
         "Tabloid journalist Zak McKracken stumbles upon an alien conspiracy.",
         "1988", "LucasArts", "C64/DOS/FM-Towns"),
    Game("sky", "Beneath a Steel Sky", "sky",
         "Robert Foster escapes Union City's oppressive regime with his robot companion Joey.",
         "1994", "Revolution", "DOS/Amiga"),
    Game("sword1", "Broken Sword: Shadow of the Templars", "sword1",
         "George Stobbart investigates a bombing in Paris linked to the Knights Templar.",
         "1996", "Revolution", "DOS/Windows/PS1"),
    Game("sword2", "Broken Sword II: The Smoking Mirror", "sword2",
         "George and Nico investigate a drug lord's connection to a Mayan prophecy.",
         "1997", "Revolution", "Windows/PS1"),
    Game("queen", "Flight of the Amazon Queen", "queen",
         "Pilot Joe King crash-lands in the Amazon and must stop a mad scientist.",
         "1995", "Interactive Binary Illusions", "DOS/Amiga"),
    Game("simon1", "Simon the Sorcerer", "agos",
         "Simon is transported to a fantasy world and must rescue a wizard from an evil sorcerer.",
         "1993", "Adventure Soft", "DOS/Amiga"),
    Game("simon2", "Simon the Sorcerer II", "agos",
         "Simon returns to the fantasy world and must stop the evil sorcerer Sordid again.",
         "1995", "Adventure Soft", "DOS/Windows"),
    Game("kyra1", "The Legend of Kyrandia", "kyra",
         "Brandon must stop the evil jester Malcolm who has turned the land to stone.",
         "1992", "Westwood Studios", "DOS"),
    Game("kyra2", "The Legend of Kyrandia: Hand of Fate", "kyra",
         "Zanthia must find an anchor stone to stop the land from disappearing.",
         "1993", "Westwood Studios", "DOS"),
    Game("kyra3", "The Legend of Kyrandia: Malcolm's Revenge", "kyra",
         "Malcolm escapes prison and must clear his name.",
         "1994", "Westwood Studios", "DOS"),
    Game("lure", "Lure of the Temptress", "lure",
         "Diermot must free the town of Turnvale from the enchantress Selena.",
         "1992", "Revolution", "DOS/Amiga"),
    Game("touche", "Touché: The Adventures of the Fifth Musketeer", "touche",
         "Geoffroi Le Bansen seeks to become the Fifth Musketeer.",
         "1995", "Clipper Software", "DOS"),
    Game("drascula", "Drascula: The Vampire Strikes Back", "drascula",
         "John Hacker must rescue his girlfriend from the vampire Drascula.",
         "1996", "Alcachofa Soft", "DOS"),
    Game("myst", "Myst", "mohawk",
         "Explore the mysterious island of Myst and unravel its secrets.",
         "1993", "Cyan", "Mac/Windows"),
    Game("riven", "Riven: The Sequel to Myst", "mohawk",
         "Continue the story on the Age of Riven.",
         "1997", "Cyan", "Mac/Windows"),
    Game("agi-fanmade", "AGI Fan Games", "agi",
         "Fan-made games using the AGI engine.",
         "", "Various", "DOS"),
    Game("sci-fanmade", "SCI Fan Games", "sci",
         "Fan-made games using the SCI engine.",
         "", "Various", "DOS"),
    Game("bass", "Beneath a Steel Sky (Remastered)", "sky",
         "Remastered version with enhanced audio and graphics.",
         "2009", "Revolution", "iOS/Android"),
    Game("dreamweb", "DreamWeb", "dreamweb",
         "Ryan must prevent the Apocalypse in this cyberpunk adventure.",
         "1994", "Creative Reality", "DOS"),
]


def detect_installed_games(scummvm_path="scummvm"):
    """Use scummvm --list-targets to find installed games."""
    games = []
    try:
        result = subprocess.run(
            [scummvm_path, "--list-targets"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n')[2:]:  # skip header
                parts = line.split()
                if len(parts) >= 2:
                    game_id = parts[0]
                    name = ' '.join(parts[1:])
                    games.append(Game(game_id, name, installed=True))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return games


def get_all_games(scummvm_path="scummvm"):
    """Get combined list of known + installed games."""
    known = {g.game_id: g for g in KNOWN_GAMES}
    
    installed = detect_installed_games(scummvm_path)
    for g in installed:
        if g.game_id in known:
            known[g.game_id].installed = True
            known[g.game_id].path = g.path
        else:
            known[g.game_id] = g
    
    return sorted(known.values(), key=lambda g: g.name)


def download_icon(game_id, callback=None):
    """Download a game icon from the scummvm-icons repo. Returns local path or None."""
    dest = get_icons_dir() / f"{game_id}.png"
    if dest.exists():
        if callback:
            callback(str(dest))
        return str(dest)
    
    url = f"{ICON_BASE_URL}/{game_id}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ScummVM-GTK/0.1.0"})
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
    """Download icon in background thread."""
    thread = threading.Thread(target=download_icon, args=(game_id, callback), daemon=True)
    thread.start()
