import math
import os
import random
import sys
import time
from datetime import datetime
import traceback
from collections.abc import Callable, Generator, Sequence
from functools import partial

import PyImGui
import PySystem

from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import AutoPathing
from Py4GWCoreLib import ColorPalette
from Py4GWCoreLib import Effects
from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import ImGui
from Py4GWCoreLib import Map
from Py4GWCoreLib import Party
from Py4GWCoreLib import Player
from Py4GWCoreLib import Routines
from Py4GWCoreLib import SkillBar

TEXTURE = os.path.join(
    PySystem.Console.get_projects_path(),
    "Assets",
    "Textures",
    "Module_Icons",
    "Ministerial Commendations BT.png",
)
MODULE_ICON = "Assets\\Textures\\Module_Icons\\Ministerial Commendations BT.png"
MODULE_NAME = 'WoC'
MODULE_DESCRIPTION = 'Farmt Ministeriumsauszeichnungen in der Quest "Ein zufaelliges Treffen".'

_PACKAGE = 'shared_data'


def _find_script_directory() -> str:
    """
    Sucht den Ordner, der das Paket shared_data enthaelt.

    Py4GW kompiliert Skripte als <string>; __file__ und der Skriptordner auf sys.path
    sind daher nicht verfuegbar. Das Skript liegt je nach Installation in Bots/custom
    oder Bots/own, deshalb erst diese pruefen und sonst Widgets/ durchsuchen.
    """
    projects_root = os.path.abspath(PySystem.Console.get_projects_path())
    bots_dir = os.path.join(projects_root, 'Widgets', 'Automation', 'Bots')

    def has_package(directory: str) -> bool:
        return os.path.isfile(os.path.join(directory, _PACKAGE, '__init__.py'))

    for name in ('custom', 'own'):
        if has_package(os.path.join(bots_dir, name)):
            return os.path.join(bots_dir, name)
    for current, dirs, _files in os.walk(os.path.join(projects_root, 'Widgets')):
        if _PACKAGE in dirs and has_package(current):
            return current
        dirs[:] = [d for d in dirs if d != '__pycache__']
    raise ModuleNotFoundError(f'{MODULE_NAME}: Ordner {_PACKAGE}/ neben dem Bot nicht gefunden.')


_SCRIPT_DIR = _find_script_directory()
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# Beim Neuladen des Skripts die Untermodule frisch importieren, damit Code-Aenderungen
# ohne Reset der Python-Umgebung greifen und kein alter Zustand uebrig bleibt.
for _name in [n for n in sys.modules if n == _PACKAGE or n.startswith(_PACKAGE + '.')]:
    del sys.modules[_name]

# Keine @dataclass in dieser Datei: Py4GW fuehrt sie als <string> aus (nicht in sys.modules).
from shared_data.common import EMPTY_OVERVIEW, Builds, Icons, Locations, Log, Maps, Names, Overview, SkillBuild  # noqa: E402
from shared_data.common import Enemies, Format, GroundItems, PartyHeroes, PlayerState, SkillData, Skills  # noqa: E402
from shared_data.common import GroundItem, Survivor, Trainers, World  # noqa: E402
from shared_data.common import Inventory, ItemActions, Kits, PickedItems, Traders, WidgetCheck  # noqa: E402
from shared_data.items import PICK, LootRules, default_rules_path, draw_rules_tab, item_keys  # noqa: E402
from shared_data.items import DropLog, UnknownItems, is_known_model  # noqa: E402
from shared_data.items import check_inventory_items, inventory_item_keys, item_label, watch_items_json  # noqa: E402

from Py4GWCoreLib.enums_src.GameData_enums import Profession, Range  # noqa: E402
from Py4GWCoreLib.enums_src.Hero_enums import HeroType  # noqa: E402
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_WITH_EQUIPMENT_BAGS, Bags, ItemType, Rarity  # noqa: E402
from Py4GWCoreLib.enums_src.Model_enums import ModelID  # noqa: E402
from Py4GWCoreLib.py4gwcorelib_src.ActionQueue import ActionQueueManager  # noqa: E402
from Py4GWCoreLib.py4gwcorelib_src.FileDialog import FileDialog  # noqa: E402
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings  # noqa: E402

# Templates, Rollen und Default-Helden je Partyposition.
# Der Held ist der Default; fehlt er, springt ein anderer freigeschalteter Held derselben Primaerklasse ein.
_MC_HERO_BUILDS: tuple[tuple[int, str, str], ...] = (
    (HeroType.AcolyteSousuke, 'Fire Ele / Starburst', 'OgBDgqyMSlVHR3C8CLg4CKDADA'),
    (HeroType.Vekk, 'Earth Ele / Stone Sheath', 'OgljkwMopOdVm22oHuK2x14UBA'),
    (HeroType.PyreFierceshot, 'Trapper', 'OggjclYsYSNHLHJHKHchYOIHCAA'),
    (HeroType.Gwen, 'Martyr Prot Mesmer', 'OQNDAowvOqkcw0z0NEEcaRBA'),
    (HeroType.Razah, 'SoS Resto + Recall', 'OAejEyiM5QXTYMdOTMSTdiVPciA'),
    (HeroType.Olias, 'BiP Resto', 'OAhjQoGYIP3BqdVV4JNncDzxJA'),
    (HeroType.Xandra, 'ST', 'OAmjAyk85QYTWPPOhTOTkTQTfiA'),
)
_MC_PLAYER_BUILDS: tuple[tuple[Profession, str], ...] = (
    (Profession.Warrior, 'OQojQhV6KT4k9F8E7gUiEY5iwF'),
    (Profession.Ranger, 'OgEUcDqWV8S4k9F8E7gUi+G5iMH'),
    (Profession.Monk, 'OwEUAj2S1qS4k9F8E7gUigE5iwF'),
    (Profession.Necromancer, 'OAFUYCqWVyS4k9F8E7gUizB5iwF'),
    (Profession.Mesmer, 'OQFUAixS1qS4k9F8E7gUioA5iwF'),
    (Profession.Elementalist, 'OgFUwi1S1qS4k9F8E7gUitT5iwF'),
    (Profession.Assassin, 'OwFkQpV63OG0dZfBPxOYDkLTuIcB'),
    (Profession.Ritualist, 'OAGkQGhLlWpEOZfBPxOIlo0UuIcB'),
    (Profession.Paragon, 'OQGjgOUcFT4k9F8E7gUiBA5iwF'),
    (Profession.Dervish, 'OgGlwWrJlWpqFhT2XwTsDSJSglL29B'),
)

# Einmal beim Laden decodieren; shared_data rechnet nur mit dem, was hier vorgegeben wird.
HERO_BUILDS = Builds.decode_hero_builds(_MC_HERO_BUILDS)
PLAYER_BUILDS = Builds.decode_player_builds(_MC_PLAYER_BUILDS)
REQUIRED_PRIMARIES = Builds.required_primaries(HERO_BUILDS)

COLOR_OK = (0.2, 1.0, 0.2, 1.0)
COLOR_WARN = (1.0, 0.8, 0.2, 1.0)
COLOR_MISSING = (1.0, 0.25, 0.25, 1.0)
COLOR_ELITE = (1.0, 210 / 255, 80 / 255, 1.0)  # Gold (255, 210, 80)
# Farben im Reiter Statistik.
_STAT_CYAN = (80 / 255, 210 / 255, 1.0, 1.0)
_STAT_WHITE = (1.0, 1.0, 1.0, 1.0)
_STAT_YELLOW = (1.0, 210 / 255, 0.0, 1.0)
_STAT_RED = (1.0, 70 / 255, 70 / 255, 1.0)
_STAT_HEADER_BG = 26 | (38 << 8) | (51 << 16) | (255 << 24)

# Klassenfarben aus der Py4GW-Palette (wie HeroAI): "GW_Warrior", "GW_Ranger", ...
_PROFESSION_COLORS: dict[int, tuple[float, ...]] = {
    int(prof): tuple(ColorPalette.GetColor(f'GW_{prof.name}').to_tuple_normalized())
    for prof in Profession
    if int(prof)
}

_TABLE_FLAGS = (
    PyImGui.TableFlags.Borders
    | PyImGui.TableFlags.RowBg
    | PyImGui.TableFlags.SizingFixedFit
    | PyImGui.TableFlags.NoHostExtendX
)

_overview: Overview = EMPTY_OVERVIEW
# True nur, wenn bei der letzten Pruefung (START) alle Helden und Skills fuer die Builds vorhanden sind.
_requirements_ok: bool = False
_BUILD_LOAD_TIMEOUT_S = 15.0
_LEAVE_PARTY_SETTLE_S = 0.25
_LEAVE_PARTY_TIMEOUT_S = 5.0
_BUILD_LOAD_INTERVAL_S = 0.25  # Abstand zwischen zwei Template-Ladungen
# Party wird in Kaineng aufgestellt; Schritt Preparation reist ggf. erst hin.
_KAINENG_CENTER = Maps.id('KAINENG_CENTER_DEFAULT')
# Mission betreten: ohne BehaviorTree (Generator, in main() getaktet).
_A_CHANCE_ENCOUNTER = 861
_MISSION_DIALOG = 0x84
_MISSION_NPC_XY = (2240.0, -1264.0)
_KAINENG_DETOUR_XY = (1474.0, -1197.0)  # Zwischenpunkt, wenn der Spieler im Bereich unten links startet
_MOVE_REISSUE_S = 2.0  # Bewegungsbefehl erneuern, wenn der Spieler so lange haengt
_MAP_LOAD_TIMEOUT_S = 45.0
# Item Handling: so nah an den Kaufmann (Haendler finden, Werkzeuge, Aktionen: shared_data.common).
_MERCHANT_TOLERANCE = 150.0
# BT.Move mit pause_on_combat=False rechnet mit max(tolerance, 125) und 15 s je Wegpunkt; hier genauso.
_MOVE_MIN_TOLERANCE = 125.0
_MOVE_WAYPOINT_TIMEOUT_S = 15.0

# Ablauf in der Mission: Positionen, Slots, Wartezeiten.
_HERO_FIRE_ELE, _HERO_EARTH_ELE, _HERO_TRAPPER, _HERO_PROT_MESMER, _HERO_SOS, _HERO_BIP, _HERO_ST = range(1, 8)
_STARTING_POSITIONS = (
    (_HERO_FIRE_ELE, -6362.0, -4967.0),
    (_HERO_EARTH_ELE, -6060.0, -5168.0),
    (_HERO_TRAPPER, -6245.0, -5232.0),
    (_HERO_PROT_MESMER, -6362.0, -4967.0),
    (_HERO_SOS, -5691.0, -5195.0),
    (_HERO_BIP, -5606.0, -4747.0),
    (_HERO_ST, -5452.0, -4380.0),
)
_PLAYER_HERO_SETUP_POSITION = (-6232.0, -5392.0)
_PLAYER_TRAP_POSITION = (-6306.0, -5260.0)
_SAFE_SPOT = (-6080.0, -5020.0)
_FIGHT_EXIT = (-4800.0, -3700.0)
_JOURNEY_MID_1 = (-4658.0, -757.0)
_STAIR_PATH = ((-4761.0, -608.0), (-4464.0, -323.0), (-3869.0, 240.0))  # erzwingt die Treppenlinie
_JOURNEY_MID_2 = (-3135.0, 628.0)
_JOURNEY_MID_3 = (-2127.0, -1224.0)
_JOURNEY_MID_4 = (-878.0, -1854.0)
_STAIRS_APPROACH = (-766.0, -3262.0)
_FARM_POSITION = (-840.25, -3955.57)
_XANDRA_SPIKE_SETUP_POSITION = (-1665.0, -6015.0)
_XANDRA_RETREAT_POSITION = (-4950.0, -7955.0)
_MIKU_LEGACY_AGENT_ID = 58
_MIKU_SEARCH_ANCHOR = (-6300.0, -5300.0)
_INITIAL_FOE_CAPTURE_RADIUS = 4_800.0
_INITIAL_FOE_CAPTURE_WINDOW_S = 3.0
_INITIAL_FOE_EXPECTED_COUNT = 10
# Spike erst ab so vielen Gegnern in 1000; in Config 20-60 einstellbar, Standard 48.
_MIN_FOES_DEFAULT = 48
_MIN_FOES_MIN = 20
_MIN_FOES_MAX = 60
_SPIKE_MIN_ENERGY = 15.0
_SURVIVAL_CAST_MIN_ENERGY = 25.0
# Ein Gegner der Welle zaehlt als erledigt, wenn er so viele Frames (nicht Sekunden) in 1000 stand.
_WAVE_DWELL_TICKS = 24
_WAVE_STABLE_S = 0.5  # so lange muss die Entscheidung der Welle (Spike oder zu klein) stabil gelten
# Loot: im Earshot-Radius, alle 500 ms das naechste Item, nach 15 s weiter.
_LOOT_RADIUS = Range.Earshot.value
_LOOT_APPEAR_S = 1.0
_LOOT_CLEAR_S = 1.5
_LOOT_INTERACT_S = 0.5
_LOOT_TIMEOUT_S = 15.0
_UNKNOWN_NAME_WAIT_S = 0.5  # Scan 1 fragt Namen an, Scan 2 liest sie danach aus
_mission_runner: Generator[None, None, None] | None = None
_mission_step_name = ''
_mission_step_index = -1  # 0-basiert, -1 = kein Schritt laeuft
# Laufzeit: startet mit START. Watchdog: startet bzw. wird zurueckgesetzt am Anfang von Enter A Chance Encounter;
# beide zaehlen nur, solange der Ablauf laeuft. Abgelaufener Watchdog startet den Ablauf ab Schritt 1 neu.
_run_elapsed_s = 0.0
_last_run_s = 0.0
_timer_last_tick = 0.0
_watchdog_active = False
_watchdog_elapsed_s = 0.0
_death_restart_armed = True  # False nach einem Tod-Neustart, bis Spieler und Miku wieder leben
_no_map_since = 0.0  # seit wann keine Map geladen ist; 0 = Map da
_WATCHDOG_DEFAULT_MINUTES = 4
_WATCHDOG_MAX_MINUTES = 10

# Reiter Config: in Widgets/Config/WoC.ini (fuer alle Accounts); Settings speichert selbst verzoegert.
_SETTINGS = Settings('Widgets/Config/WoC.ini', 'global')
_CONFIG_SECTION = 'Config'
Log.set_enabled(_SETTINGS.get_bool(_CONFIG_SECTION, 'log', True))
# Fehlersuche: jeden schnellen Spieler-Cast der Kampfschleifen (Schritt 5, 9, 10) mit HP und Energie ins Log.
_log_casts = _SETTINGS.get_bool(_CONFIG_SECTION, 'log_casts', False)
# Statistik: Sitzung nur im Speicher, Gesamt in WoC.ini [Statistik]. Ein Lauf = Schritt 2 bis Loot.
_STATS_SECTION = 'Statistik'
_STATS_KEYS = ('runs', 'commendations', 'drop_runs', 'run_seconds')
_session_stats: dict[str, float] = dict.fromkeys(_STATS_KEYS, 0.0)
_total_stats: dict[str, float] = {key: max(0.0, _SETTINGS.get_float(_STATS_SECTION, key, 0.0)) for key in _STATS_KEYS}
_run_start_commendations = -1  # Auszeichnungen im Inventar zu Beginn des Laufs; -1 = kein Lauf gemessen
_last_run_commendations = 0
_stats_reset_pending = False
# Fehler: jeder gescheiterte Schritt (nicht STOP). Nur fuer die Sitzung; Speichern ueber den Explorer.
_ERROR_LIST_MAX = 500
_errors: list[tuple[str, str, str]] = []  # (Zeit, Schritt, Grund), neueste zuletzt
_error_count = 0
_last_fail_reason = ''  # Meldung des letzten _fail im laufenden Schritt
# FEHLER-LOG SPEICHERN: Datei-Explorer im Overlay (Core-FileDialog); startet im zuletzt benutzten Ordner.
# Ohne eingegebenen Dateinamen wird _ERROR_EXPORT_NAME genommen.
_ERROR_EXPORT_NAME = f'{MODULE_NAME}_error_log.txt'
_ERROR_EXPORT_TITLE = 'Fehler-Log speichern'
_error_export_dir = os.path.join(PySystem.Console.get_projects_path(), 'Settings', 'Global', 'Widgets', 'Config')
_error_export_message = ''
_error_dialog: FileDialog | None = None
_watchdog_minutes = min(
    _WATCHDOG_MAX_MINUTES,
    max(0, _SETTINGS.get_int(_CONFIG_SECTION, 'watchdog_minutes', _WATCHDOG_DEFAULT_MINUTES)),
)  # 0 = aus
_min_foes_for_spike = min(
    _MIN_FOES_MAX,
    max(_MIN_FOES_MIN, _SETTINGS.get_int(_CONFIG_SECTION, 'min_foes_for_spike', _MIN_FOES_DEFAULT)),
)
# Survivor (Ueberlebender-Titel): faellt die Spieler-HP ab Schritt 3 unter min HP, Neustart ab Schritt 2. 0 = aus.
_SURVIVOR = Survivor(_SETTINGS, _CONFIG_SECTION)
# Loot-Regeln: Settings/Global/Widgets/Config/WoC_loot.json; Reiter Items kommt aus shared_data.items.
_LOOT_RULES = LootRules(default_rules_path(MODULE_NAME))
# Items, die beim Loot lagen, aber nicht in items.json stehen; nach dem Loot traegt der Bot sie dort ein.
_UNKNOWN_ITEMS = UnknownItems()  # nur bis nach dem Loot; dann in items.json (check_inventory_items)
# Eigene Drops beim Loot (gesehen/aufgehoben), nur fuer die Sitzung im Speicher.
_DROPS = DropLog()
# Vom Bot beim Loot aufgehobene Items (ohne Gold) mit ihrem Schluessel in _DROPS; nur diese bearbeitet Item Handling.
_PICKED = PickedItems()
# Beim Loot am Boden gelesen (Model-ID -> ModelFileID); nach dem Loot fuellt check_inventory_items damit Luecken.
_ground_file_ids: dict[int, int] = {}
_item_handling_paused = False  # Item Handling haelt gerade an (siehe _pause_before)
# Items > Merchant / Salvage: aus der Loot-Auswahl anhaken, was verkauft bzw. zerlegt wird. Je Liste eine eigene
# Datei neben WoC_loot.json (WoC_merchant.json, WoC_salvage.json); PICK = Haken.
_RULES_DIR = os.path.dirname(default_rules_path(MODULE_NAME))
_MERCHANT_RULES = LootRules(os.path.join(_RULES_DIR, f'{MODULE_NAME}_merchant.json'))
_SALVAGE_RULES = LootRules(os.path.join(_RULES_DIR, f'{MODULE_NAME}_salvage.json'))
# Identifizieren (Items > Item-Info): eigene Regeln; neu angelegt mit den Seltenheiten ab Blau (wie frueher fest).
_IDENTIFY_RULES = LootRules(os.path.join(_RULES_DIR, f'{MODULE_NAME}_identify.json'))
_IDENTIFY_RULES.seed_rarities((int(Rarity.Blue), int(Rarity.Purple), int(Rarity.Gold), int(Rarity.Green)))
# Schalter im Reiter Config (Item Handling, Schritt 12).
_merchant_enabled = _SETTINGS.get_bool(_CONFIG_SECTION, 'merchant', False)
_salvage_enabled = _SETTINGS.get_bool(_CONFIG_SECTION, 'salvage', False)
_identify_enabled = _SETTINGS.get_bool(_CONFIG_SECTION, 'identify', False)
_item_handling_pauses = _SETTINGS.get_bool(_CONFIG_SECTION, 'item_handling_pauses', True)  # Pausen in Schritt 12
# Taschen, aus denen Merchant verkaufen darf; Ausruestungspack standardmaessig aus (dort liegt meist Ausruestung).
_BAG_NAMES: dict[Bags, str] = {
    Bags.Backpack: 'Backpack',
    Bags.BeltPouch: 'Belt Pouch',
    Bags.Bag1: 'Bag 1',
    Bags.Bag2: 'Bag 2',
    Bags.EquipmentPack: 'Equipment Pack',
}
# Inventar-Grenzen (Config); 0 = aus. Freie Plaetze nur in den angehakten und vorhandenen Taschen (wie Merchant).
# Item Handling nur unter X freien Plaetzen. Stop bei X freien Plaetzen: laufend geprueft (ausser in Item Handling,
# dort am Ende), dann nach Kaineng und stoppen. Gold max. = Platin x 1000 + Gold, geprueft nach Loot und am Ende
# von Item Handling; nach Loot ebenfalls nach Kaineng und stoppen.
_MAX_FREE_SLOTS = 65  # Backpack 20 + Belt Pouch 5 + Bag 1/2 je bis 10 + Equipment Pack 20
_handling_free_slots = min(_MAX_FREE_SLOTS, max(0, _SETTINGS.get_int(_CONFIG_SECTION, 'min_free_slots', 0)))
_stop_free_slots = min(_MAX_FREE_SLOTS, max(0, _SETTINGS.get_int(_CONFIG_SECTION, 'stop_free_slots', 0)))
_FREE_SLOT_POLL_S = 1.0
_free_slot_polled = 0.0
_last_stop_reason = ''  # 'HH:MM:SS Grund' des letzten Stopps, unter START im Reiter Main; START loescht ihn
_stopping_to_town = False  # Stop nach Kaineng (freie Plaetze, Gold nach Loot): Reise laeuft, danach Ende
_town_stop_request = ''  # Grund, den ein Schritt meldet; main() fuehrt "nach Kaineng und stoppen" aus
_max_platinum = min(100, max(0, _SETTINGS.get_int(_CONFIG_SECTION, 'max_platinum', 99)))
_max_gold = min(999, max(0, _SETTINGS.get_int(_CONFIG_SECTION, 'max_gold', 0)))
_stop_request = ''  # Grund; main() stoppt den Ablauf im naechsten Frame (ein Schritt kann sich nicht selbst beenden)
_stop_after_run = False  # Knopf STOP NACH LAUF: am Ende des Laufs (fertig oder gescheitert) nach Kaineng und stoppen
_merchant_bags: dict[Bags, bool] = {
    bag: _SETTINGS.get_bool(_CONFIG_SECTION, f'merchant_bag_{int(bag)}', bag != Bags.EquipmentPack)
    for bag in INVENTORY_WITH_EQUIPMENT_BAGS
}


def _requirements_met(overview: Overview) -> bool:
    """Prueft alles zu Helden und Skills; alles Unbekannte zaehlt als fehlend."""
    # Einlesen erfolgreich und alle Templates gueltig.
    if not overview.heroes:
        return False
    if any(entry.build is None for entry in HERO_BUILDS):
        return False
    # Jeder Helden-Build hat einen Helden, Freischaltungen abfragbar, kein Skill fehlt.
    if overview.unlocked_skills is None or len(overview.assignments) != len(HERO_BUILDS):
        return False
    if any(entry.hero is None or entry.missing_skills for entry in overview.assignments):
        return False
    # Spieler: Klasse lesbar, gueltiges Template, gelernte Skills abfragbar, kein Skill fehlt.
    primary = overview.player_primary
    if primary == 0 or Builds.player_build_for(primary, PLAYER_BUILDS) is None:
        return False
    if overview.learnt_skills is None or overview.player_missing_skills:
        return False
    return True


def _draw_icon_slot(path: str | None, size: float) -> None:
    """Icon oder gleich grosser Platzhalter, damit nachfolgender Text buendig bleibt."""
    if path:
        ImGui.DrawTexture(path, size, size)
    else:
        PyImGui.dummy((size, size))
    PyImGui.same_line(0, 4)


def _draw_profession(profession: int) -> None:
    """Klassen-Icon plus deutscher Klassenname, z. B. in Tabellenzellen."""
    _draw_icon_slot(Icons.profession(profession), PyImGui.get_text_line_height())
    PyImGui.text(Names.profession(profession))


def _draw_status(ok: bool, ok_text: str, missing_text: str) -> None:
    if ok:
        PyImGui.text_colored(ok_text, COLOR_OK)
    else:
        PyImGui.text_colored(missing_text, COLOR_MISSING)


# Zeile der Build-Tabelle im Reiter Main: (Rolle, Primaerklasse oder 0, Name, Namensfarbe, Skills, Status,
# Statusfarbe, fehlende Skill-IDs fuer den Tooltip).
_BuildRow = tuple[str, int, str, tuple[float, float, float, float] | None, str, str,
                  tuple[float, float, float, float], tuple[int, ...]]


def _hero_rows() -> list[_BuildRow]:
    """Helden-Builds, deren Status nicht OK ist."""
    rows: list[_BuildRow] = []
    for entry in _overview.assignments:
        if entry.hero is not None and not entry.missing_skills and _overview.unlocked_skills is not None:
            continue
        if entry.hero is None:
            name, name_color = 'kein Held', COLOR_MISSING
        elif entry.is_preferred:
            name, name_color = entry.hero.name, None
        else:
            name, name_color = f'{entry.hero.name} (Ersatz)', COLOR_WARN
        if entry.build is None or _overview.unlocked_skills is None:
            skills = '?'
        else:
            total = sum(1 for s in entry.build.skills if s)
            skills = f'{total - len(entry.missing_skills)}/{total}'
        if entry.hero is None:
            status, status_color = 'Held fehlt', COLOR_MISSING
        elif entry.missing_skills:
            status, status_color = 'Skills fehlen', COLOR_WARN
        else:
            status, status_color = 'Skills unbekannt', COLOR_WARN
        primary = entry.build.primary if entry.build is not None else 0
        rows.append((entry.role, primary, name, name_color, skills, status, status_color, entry.missing_skills))
    return rows


def _player_row() -> _BuildRow | None:
    """Der Spieler, wenn ihm Skills seines Builds fehlen oder Klasse/Template/gelernte Skills nicht lesbar sind."""
    primary = _overview.player_primary  # Stand von START, nicht live (Ladebildschirm meldet keine Klasse)
    build = Builds.player_build_for(primary, PLAYER_BUILDS) if primary else None
    missing = _overview.player_missing_skills
    if primary and build is not None and _overview.learnt_skills is not None and not missing:
        return None
    name = Player.GetName() or 'Spieler'
    if build is None or _overview.learnt_skills is None:
        skills = '?'
    else:
        total = sum(1 for s in build.skills if s)
        skills = f'{total - len(missing)}/{total}'
    if not primary:
        status, status_color = 'Klasse unbekannt', COLOR_MISSING
    elif build is None:
        status, status_color = 'kein Template', COLOR_MISSING
    elif missing:
        status, status_color = 'Skills fehlen', COLOR_WARN
    else:
        status, status_color = 'Skills unbekannt', COLOR_WARN
    return 'Spieler', primary, name, None, skills, status, status_color, missing


def _draw_assignments_table() -> None:
    """Builds, deren Status nicht OK ist: Helden und Spieler; ohne solche Zeilen entfaellt die Tabelle."""
    rows = _hero_rows()
    player = _player_row()
    if player is not None:
        rows.append(player)
    if not rows:
        return
    PyImGui.spacing()
    PyImGui.text('Builds')
    if not PyImGui.begin_table('##woc_assignments', 5, _TABLE_FLAGS):
        return
    for label in ('Rolle', 'Primaerklasse', 'Held / Spieler', 'Skills', 'Status'):
        PyImGui.table_setup_column(label)
    PyImGui.table_headers_row()
    for role, primary, name, name_color, skills, status, status_color, missing in rows:
        # Tooltip mit den fehlenden Fertigkeiten, egal ueber welcher Zelle der Zeile die Maus steht.
        tooltip = ''
        if missing:
            names = sorted((SkillData.label(s) for s in missing), key=str.casefold)
            tooltip = 'Fehlende Fertigkeiten:\n' + '\n'.join(f'- {skill}' for skill in names)
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        PyImGui.text(role)
        _row_tooltip(tooltip)
        PyImGui.table_next_column()
        if primary:
            _draw_profession(primary)
        else:
            PyImGui.text('?')
        _row_tooltip(tooltip)
        PyImGui.table_next_column()
        if name_color is None:
            PyImGui.text(name)
        else:
            PyImGui.text_colored(name, name_color)
        _row_tooltip(tooltip)
        PyImGui.table_next_column()
        PyImGui.text(skills)
        _row_tooltip(tooltip)
        PyImGui.table_next_column()
        PyImGui.text_colored(status, status_color)
        _row_tooltip(tooltip)
    PyImGui.end_table()


def _row_tooltip(text: str) -> None:
    if text and PyImGui.is_item_hovered():
        PyImGui.set_tooltip(text)


def _draw_missing_skills() -> None:
    missing = _overview.missing_skills()
    if not missing:
        return
    PyImGui.spacing()
    if not PyImGui.collapsing_header(f'Fehlende Skills ({len(missing)})##WoCMissing'):
        return
    icon_size = PyImGui.get_text_line_height()
    elite_icon = Icons.elite()
    # Elite-Skills zuerst alphabetisch, danach normale nach Klasse (Spielreihenfolge, klassenlose zuletzt) und Name.
    for skill_id in SkillData.sort_ids(missing):
        info = SkillData.info_de(skill_id)
        title = f'{SkillData.label(skill_id)} - {info.attribute or "kein Attribut"}'
        # Reihenfolge: Klassen-Icon, Elite-Symbol, Skill-Bild, Name. Leere Plaetze halten die Spalten buendig.
        _draw_icon_slot(Icons.profession(info.profession), icon_size)
        if elite_icon:
            _draw_icon_slot(elite_icon if info.elite else None, icon_size)
        elif info.elite:
            title = f'[Elite] {title}'
        _draw_icon_slot(Icons.skill(skill_id), icon_size)
        # Elite bleibt gold, sonst Klassenfarbe; klassenlose Skills in normaler Textfarbe.
        color = COLOR_ELITE if info.elite else _PROFESSION_COLORS.get(info.profession)
        if color is not None:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, color)
        is_open = PyImGui.tree_node(f'{title}##missing_{skill_id}')
        if color is not None:
            PyImGui.pop_style_color(1)
        if not is_open:
            continue
        PyImGui.spacing()
        if not info.sources:
            PyImGui.text_disabled('Keine Bezugsquelle hinterlegt.')
        for index, (category, items) in enumerate(info.sources):
            if index:
                PyImGui.spacing()
            PyImGui.text_colored(category, COLOR_WARN)
            for item_index, item in enumerate(items):
                # Verkaeufer in einem eindeutigen Aussenposten sind anklickbar und reisen dorthin.
                target = Trainers.location(category, item)
                map_id = Locations.travel_map_id(target[1]) if target else None
                if target is None or map_id is None:
                    PyImGui.bullet_text(item)
                    continue
                PyImGui.bullet()
                PyImGui.same_line(0, -1)
                if PyImGui.selectable(f'{item}##travel_{skill_id}_{index}_{item_index}'):
                    _travel_to(map_id, target[1])
                if PyImGui.is_item_hovered():
                    PyImGui.set_tooltip(f'Klicken: Reise nach {target[1]}')
        PyImGui.tree_pop()
        # Trennlinie nur unter aufgeklappten Skills, damit Bloecke klar enden.
        PyImGui.spacing()
        PyImGui.separator()
    PyImGui.spacing()
    PyImGui.text_disabled('Quelle: guildwiki.de')


def _travel_to(map_id: int, location: str) -> None:
    if Map.GetMapID() == map_id:
        Log.write(f'Bereits in {location}.', PySystem.Console.MessageType.Info, MODULE_NAME)
        return
    Log.write(f'Reise nach {location} (Map {map_id}).', PySystem.Console.MessageType.Info, MODULE_NAME)
    Map.Travel(map_id)


def _draw_trainer_offers() -> None:
    offers = Trainers.offers(_overview.missing_skills())
    if not offers:
        return
    PyImGui.spacing()
    if not PyImGui.collapsing_header(f'Nicht-Elite-Skills kaufen ({len(offers)} Trainer)##WoCTrainers'):
        return
    if not PyImGui.begin_table('##woc_trainers', 4, _TABLE_FLAGS):
        return
    for label in ('Skills', 'Trainer', 'Ort', 'Art'):
        PyImGui.table_setup_column(label)
    PyImGui.table_headers_row()
    for offer in offers:
        PyImGui.table_next_row()
        for column, value in enumerate((len(offer.skill_ids), offer.trainer, offer.location, offer.kind)):
            PyImGui.table_next_column()
            color = _location_color(offer.location) if column == 2 else None
            if color is not None:
                PyImGui.text_colored(str(value), color)
            else:
                PyImGui.text(str(value))
            if PyImGui.is_item_hovered():
                _draw_offer_tooltip(offer.skill_ids)
    PyImGui.end_table()
    PyImGui.text_disabled('Quelle: guildwiki.de')


def _location_color(location: str) -> tuple[float, float, float, float] | None:
    """Gruen = freigeschaltet, rot = nicht; None (normale Farbe), wenn Ort ohne eindeutige ID oder nicht abfragbar."""
    unlocked = Locations.unlocked(location)
    if unlocked is None:
        return None
    return COLOR_OK if unlocked else COLOR_MISSING


def _draw_offer_tooltip(skill_ids: tuple[int, ...]) -> None:
    """Skills eines Trainers mit Klassen-Icon in Klassenfarbe, sortiert nach Klasse und Name."""
    icon_size = PyImGui.get_text_line_height()
    PyImGui.begin_tooltip()
    for skill_id in SkillData.sort_ids(skill_ids):
        info = SkillData.info_de(skill_id)
        name = info.name or SkillData.name(skill_id)
        _draw_icon_slot(Icons.profession(info.profession), icon_size)
        color = _PROFESSION_COLORS.get(info.profession)
        if color is not None:
            PyImGui.text_colored(name, color)
        else:
            PyImGui.text(name)
    PyImGui.end_tooltip()


def _draw_required_primaries() -> None:
    # Nur Klassen, bei denen Helden fehlen; ohne solche Zeilen entfaellt die ganze Tabelle.
    rows = Builds.missing_primaries(REQUIRED_PRIMARIES, _overview.heroes)
    if not rows:
        return
    PyImGui.spacing()
    PyImGui.text('Benoetigte Primaerklassen')
    if not PyImGui.begin_table('##woc_required', 4, _TABLE_FLAGS):
        return
    for label in ('Primaerklasse', 'Benoetigt', 'Vorhanden', 'Status'):
        PyImGui.table_setup_column(label)
    PyImGui.table_headers_row()
    for profession, required, available in rows:
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        _draw_profession(profession)
        for value in (required, available):
            PyImGui.table_next_column()
            PyImGui.text(str(value))
        PyImGui.table_next_column()
        _draw_status(available >= required, 'OK', 'fehlt')
    PyImGui.end_table()


def _draw_all_heroes() -> None:
    if not PyImGui.collapsing_header(f'Alle Helden ({len(_overview.heroes)})##WoCAll'):
        return
    if not PyImGui.begin_table('##woc_table', 3, _TABLE_FLAGS):
        return
    for label in ('Held', 'Stufe', 'Primaerklasse'):
        PyImGui.table_setup_column(label)
    PyImGui.table_headers_row()
    for row in _overview.heroes:
        PyImGui.table_next_row()
        for value in (row.name, row.level):
            PyImGui.table_next_column()
            PyImGui.text(str(value))
        PyImGui.table_next_column()
        _draw_profession(row.primary_id)
    PyImGui.end_table()


def _not_ready_reasons() -> list[str]:
    """Gruende fuer 'nicht startbereit': zuerst Lese-/Abfragefehler mit Ort, dann Fehlendes."""
    if _overview.error:
        return [_overview.error.rstrip('.')]
    if not _overview.heroes:
        return ['keine Helden gelesen']
    reasons = [f'Template ungueltig: {entry.role}' for entry in HERO_BUILDS if entry.build is None]
    if _overview.unlocked_skills is None:
        reasons.append('Skill-Freischaltungen nicht abfragbar')
    if _overview.learnt_skills is None:
        reasons.append('gelernte Skills nicht abfragbar')
    primary = _overview.player_primary  # Stand von START
    if primary == 0:
        reasons.append('Spielerklasse nicht lesbar')
    elif Builds.player_build_for(primary, PLAYER_BUILDS) is None:
        reasons.append(f'kein Spieler-Template fuer {Names.profession(primary)}')
    if any(entry.hero is None for entry in _overview.assignments):
        reasons.append('Helden fehlen')
    if any(entry.missing_skills for entry in _overview.assignments) or _overview.player_missing_skills:
        reasons.append('Skills fehlen')
    return reasons


def _not_ready_message() -> str:
    reasons = _not_ready_reasons()
    if not reasons:
        return 'Nicht startbereit; beheben und erneut START.'
    return f'Nicht startbereit ({", ".join(reasons)}); beheben und erneut START.'


def _check_requirements() -> bool:
    """Helden und Skills lesen und pruefen (frueher CHECK); Ergebnis bleibt fuer Main, Info und Builds stehen."""
    global _overview, _requirements_ok
    _overview = Overview.read(HERO_BUILDS, PLAYER_BUILDS)
    _requirements_ok = _requirements_met(_overview)
    return _requirements_ok


def _draw_main_tab() -> None:
    PyImGui.spacing()
    _draw_mission_controls()
    # Vor dem ersten START der Hinweis; danach nur bei Fehler oder unerfuellten Bedingungen die rote Meldung.
    # Erfolgsmeldung und Fehlergrund stehen im Log.
    if _overview is EMPTY_OVERVIEW:
        PyImGui.same_line(0, 10)
        PyImGui.text(_overview.status)
        return
    if not _requirements_ok:
        PyImGui.same_line(0, 10)
        PyImGui.text_colored(_not_ready_message(), COLOR_MISSING)
    if not _overview.heroes:
        return
    _draw_required_primaries()
    _draw_assignments_table()


def _load_player_build() -> None:
    primary = Skills.player_primary()
    template = next((code for prof, code in _MC_PLAYER_BUILDS if int(prof) == primary), None)
    if template is None:
        _step(f'Kein Spieler-Template fuer {Names.profession(primary)}.')
        return
    SkillBar.LoadSkillTemplate(template)
    _step(f'Spieler-Build geladen ({Names.profession(primary)}).')


def _quest_skill_ai() -> dict[int, dict[int, bool]]:
    """GW-Skill-KI je Heldenposition/Slot fuer die Quest; True = KI darf nutzen."""
    states = {position: {slot: True for slot in range(1, 9)} for position in range(1, 8)}
    states[1].update({6: False, 7: False, 8: False})              # Fire Ele
    states[2].update({6: False, 7: True, 8: False})               # Earth Ele
    states[3].update({slot: False for slot in range(1, 8)})       # Trapper
    states[5].update({1: False, 2: False, 3: False})              # SoS Resto
    states[6].update({1: False, 2: False, 7: False, 8: False})    # BiP Resto
    states[7].update({slot: False for slot in range(2, 9)})       # ST
    return states


_STATUS_INTERVAL_S = 2.0  # Statuszeile in Warteschleifen (Laufen, Karte laden)


def _step(message: str) -> None:
    Log.write(f'Mission: {message}', PySystem.Console.MessageType.Info, MODULE_NAME)


def _wait(seconds: float) -> Generator[None, None, None]:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        yield


def _wait_for_map(map_id: int, timeout_s: float) -> Generator[None, None, bool]:
    """Wartet, bis die Karte geladen ist (und die Gruppe), wie BT.WaitForMapLoad / TravelToOutpost."""
    _step(f'warte auf Map {map_id} (max. {timeout_s:.0f} s); jetzt: {World.map_state()}')
    start = time.monotonic()
    next_status = start + _STATUS_INTERVAL_S
    while not (Map.IsMapReady() and Map.GetMapID() == map_id and Party.IsPartyLoaded()):
        now = time.monotonic()
        if now > start + timeout_s:
            _step(f'Timeout beim Warten auf Map {map_id}; zuletzt: {World.map_state()}')
            return False
        if now >= next_status:
            _step(f'... warte auf Map {map_id} seit {now - start:.0f} s: {World.map_state()}')
            next_status = now + _STATUS_INTERVAL_S
        yield
    _step(f'Map {map_id} geladen nach {time.monotonic() - start:.1f} s.')
    return True


def _issue_move(x: float, y: float, last: tuple[float, float] | None) -> tuple[float, float]:
    """Player.Move wie BT.Move: einen schon gesendeten Punkt leicht versetzen, sonst ignoriert GW den Befehl."""
    if last is not None and abs(x - last[0]) <= 10 and abs(y - last[1]) <= 10:
        x += random.uniform(-10.0, 10.0)
        y += random.uniform(-10.0, 10.0)
    Player.Move(x, y)
    return (x, y)


def _move_to(
    x: float, y: float, tolerance: float = _MOVE_MIN_TOLERANCE, waypoint_timeout_s: float = _MOVE_WAYPOINT_TIMEOUT_S
) -> Generator[None, None, bool]:
    """Wie BT.Move: Weg per AutoPathing (margin 250), Wegpunkt fuer Wegpunkt, Befehl alle 2 s erneuert (mit Jitter)."""
    tolerance = max(tolerance, _MOVE_MIN_TOLERANCE)
    px, py = Player.GetXY()
    _step(f'laufe von ({px:.0f}, {py:.0f}) nach ({x:.0f}, {y:.0f}), Abstand {math.hypot(px - x, py - y):.0f}.')
    start = time.monotonic()
    path = list((yield from AutoPathing().get_path_to(x, y, margin=250)) or [])
    if path:
        _step(f'    Weg berechnet in {time.monotonic() - start:.1f} s: {len(path)} Wegpunkte.')
    else:
        path = [(x, y)]
        _step('    kein Weg berechnet; laufe direkt zum Ziel.')
    commands = 0
    last_command: tuple[float, float] | None = None
    for index, (wx, wy) in enumerate(path, 1):
        waypoint_start = time.monotonic()
        next_command = 0.0
        next_status = waypoint_start + _STATUS_INTERVAL_S
        while True:
            px, py = Player.GetXY()
            # Wie BT.Move: am Ziel angekommen beendet auch dann, wenn noch Wegpunkte uebrig sind.
            if math.hypot(px - x, py - y) <= tolerance:
                _step(f'Ziel ({x:.0f}, {y:.0f}) erreicht nach {time.monotonic() - start:.1f} s.')
                return True
            distance = math.hypot(px - wx, py - wy)
            if distance <= tolerance:
                break
            now = time.monotonic()
            if now > waypoint_start + waypoint_timeout_s:
                _step(
                    f'Timeout beim Laufen: Position ({px:.0f}, {py:.0f}), Wegpunkt {index}/{len(path)} '
                    f'({wx:.0f}, {wy:.0f}), Abstand {distance:.0f}, {commands} Move-Befehle.'
                )
                return False
            if now >= next_command:
                last_command = _issue_move(wx, wy, last_command)
                commands += 1
                next_command = now + _MOVE_REISSUE_S
            if now >= next_status:
                _step(f'... Position ({px:.0f}, {py:.0f}), Wegpunkt {index}/{len(path)}, Abstand {distance:.0f}, Move-Befehle {commands}.')
                next_status = now + _STATUS_INTERVAL_S
            yield
        if index < len(path):
            _step(f'    Wegpunkt {index}/{len(path)} ({wx:.0f}, {wy:.0f}) erreicht.')
    _step(f'Ziel ({x:.0f}, {y:.0f}) erreicht nach {time.monotonic() - start:.1f} s.')
    return True


# --- Bausteine (ohne BehaviorTree) ------------------------------------------------------------------------------

Step = Generator[None, None, bool]
Target = int | Callable[[], int]


def _fail(reason: str) -> bool:
    global _last_fail_reason
    _last_fail_reason = reason
    Log.write(f'Mission: FEHLER: {reason}', PySystem.Console.MessageType.Error, MODULE_NAME)
    return False


def _hero_names() -> tuple[str, ...]:
    """Aktuelle Heldennamen der Positionen 1-7 (Fire Ele, Earth Ele, Trapper, Prot Mesmer, SoS, BiP, ST)."""
    return tuple(PartyHeroes.label(position) for position in range(1, 8))


def _resolve(target: Target) -> int:
    return int((target() if callable(target) else target) or 0)


def _resolve_miku() -> int:
    if Agent.IsValid(_MIKU_LEGACY_AGENT_ID) and Agent.IsLiving(_MIKU_LEGACY_AGENT_ID):
        allegiance, _ = Agent.GetAllegiance(_MIKU_LEGACY_AGENT_ID)
        if allegiance != 3:
            return _MIKU_LEGACY_AGENT_ID
    party_ids = {int(Player.GetAgentID() or 0)}
    party_ids.update(PartyHeroes.agent(position) for position in range(1, int(Party.GetHeroCount() or 0) + 1))
    candidates = [
        agent_id for agent_id in AgentArray.GetAllyArray()
        if agent_id not in party_ids and Agent.IsLiving(agent_id)
        and math.dist(Agent.GetXY(agent_id), _MIKU_SEARCH_ANCHOR) <= Range.SafeCompass.value
    ]
    return min(candidates, key=lambda agent_id: math.dist(Agent.GetXY(agent_id), _MIKU_SEARCH_ANCHOR)) if candidates else 0


def _dead_party_member() -> str:
    """'Spieler' oder 'Miku', wenn einer von beiden tot ist; sonst ''."""
    player_id = int(Player.GetAgentID() or 0)
    if player_id and Agent.IsDead(player_id):
        return 'Spieler'
    miku_id = _resolve_miku()
    return 'Miku' if miku_id and Agent.IsDead(miku_id) else ''


def _mission_failed() -> bool:
    """Spieler tot oder Miku tot."""
    player_id = int(Player.GetAgentID() or 0)
    if player_id == 0 or Agent.IsDead(player_id):
        return True
    miku_id = _resolve_miku()
    return bool(miku_id and Agent.IsDead(miku_id))


def _cast_player_now(slot: int, target_id: int = 0) -> bool:
    """Sofort-Cast ohne Wartezeit, fuer die Kampfschleifen; mit Config "Kampf-Casts loggen" ins Log."""
    if not PlayerState.skill_ready(slot):
        return False
    if _log_casts:
        _log_fast_cast(slot, target_id)
    GLOBAL_CACHE.SkillBar.UseSkill(slot, int(target_id or 0), aftercast_delay=0)
    return True


def _log_fast_cast(slot: int, target_id: int) -> None:
    """Ein Kampf-Cast: Skill, Ziel, HP/Energie des Spielers direkt davor und der Zustand der ACTION-Warteschlange.

    UseSkill legt den Cast nur in die Warteschlange ACTION; der Environment Upkeeper arbeitet sie ab (ein Eintrag pro
    Frame). Waechst sie oder steht sie still ("zuletzt vor"), kommen Casts zu spaet oder gar nicht an.
    """
    player_id = Player.GetAgentID()
    skill_id = int(GLOBAL_CACHE.SkillBar.GetSkillIDBySlot(slot) or 0)
    hp = float(Agent.GetHealth(player_id) or 0.0) * 100.0
    queue = ActionQueueManager().GetQueue('ACTION').action_queue
    history = queue.history
    last = f'{(datetime.now() - history[-1][0]).total_seconds():.1f} s' if history else 'nie'
    _step(f'Kampf-Cast Slot {slot} {SkillData.name(skill_id)} (Ziel {target_id or "-"}), '
          f'HP {hp:.0f}%, Energie {PlayerState.energy():.0f}, Warteschlange {len(queue.queue)} '
          f'(zuletzt abgearbeitet vor {last}), FPS {PyImGui.get_io().framerate:.0f}.')


def _defensive_ball_tick(state: dict[str, float]) -> None:
    """Spieler am Leben halten, Energie fuer den Spike behalten."""
    now_ms = time.monotonic() * 1000.0
    if now_ms - state.get('action_ms', 0.0) < 500.0:
        return
    energy = PlayerState.energy()
    casted = energy >= _SURVIVAL_CAST_MIN_ENERGY and _cast_player_now(8)
    if not casted and energy >= _SURVIVAL_CAST_MIN_ENERGY:
        casted = _cast_player_now(6)
    if not casted and PlayerState.skill_adrenaline(4) < 130:
        casted = _cast_player_now(3)
    if not casted and not PlayerState.has_effect_for_slot(1):
        casted = _cast_player_now(1)
    if casted:
        state['action_ms'] = now_ms


def _hero_cast(
    position: int, slot: int, target: Target = 0, *,
    condition: Callable[[], bool] | None = None, aftercast_ms: int = 100, name: str = '',
) -> Step:
    """Held castet Slot (HeroUseSkill mit Partyposition); scheitert, wenn der Held fehlt/tot ist."""
    label = name or f'{PartyHeroes.label(position)}: Slot {slot}'
    if condition is not None and not condition():
        _step(f'{label}: Bedingung nicht erfuellt, uebersprungen.')
        return True
    target_id = _resolve(target)
    agent_id = PartyHeroes.agent(position)
    if agent_id == 0 or Agent.IsDead(agent_id):
        return _fail(f'{label}: Held {position} nicht verfuegbar.')
    GLOBAL_CACHE.SkillBar.HeroUseSkill(target_id, slot, position)
    _step(f'{label} (Held {position}, Slot {slot}, Ziel {target_id or "-"}).')
    yield from _wait(aftercast_ms / 1000.0)
    return True


def _optional_hero_cast(position: int, slot: int, *, aftercast_ms: int = 100, name: str = '') -> Step:
    """Wie CastVekkFallBack: Fehlschlag wird ignoriert."""
    yield from _hero_cast(position, slot, aftercast_ms=aftercast_ms, name=name)
    return True


def _player_cast(slot: int, target: Target = 0, *, aftercast_ms: int = 100, name: str = '') -> Step:
    """Spieler castet nur, wenn Explorable, genug Energie und Slot bereit; sonst still weiter."""
    label = name or f'Spieler Slot {slot}'
    target_id = _resolve(target)
    skill_id = GLOBAL_CACHE.SkillBar.GetSkillIDBySlot(slot)
    ready = (
        Routines.Checks.Map.IsExplorable()
        and Routines.Checks.Skills.HasEnoughEnergy(Player.GetAgentID(), skill_id)
        and Routines.Checks.Skills.IsSkillSlotReady(slot)
    )
    if not ready:
        _step(f'{label}: nicht bereit, uebersprungen.')
        return True
    GLOBAL_CACHE.SkillBar.UseSkill(slot, target_agent_id=target_id, aftercast_delay=aftercast_ms)
    _step(f'{label} (Slot {slot}, Ziel {target_id or "-"}).')
    yield from _wait(aftercast_ms / 1000.0)
    return True


def _flag_hero(position: int, x: float, y: float) -> Step:
    agent_id = PartyHeroes.agent(position)
    if not 0 < position <= int(Party.GetHeroCount() or 0) or agent_id == 0:
        return _fail(f'Flagge: Held {position} nicht verfuegbar.')
    Party.Heroes.FlagHero(agent_id, float(x), float(y))
    _step(f'Flagge {PartyHeroes.label(position)} (Position {position}) -> ({x:.0f}, {y:.0f}).')
    yield from _wait(0.125)
    return True


def _flag_all(x: float, y: float) -> Step:
    Party.Heroes.FlagAllHeroes(float(x), float(y))
    _step(f'Flagge alle Helden -> ({x:.0f}, {y:.0f}).')
    yield from _wait(0.125)
    return True


def _pause(seconds: float) -> Step:
    yield from _wait(seconds)
    return True


def _go(point: tuple[float, float], tolerance: float = _MOVE_MIN_TOLERANCE) -> Step:
    return _move_to(point[0], point[1], tolerance)


def _skill_ai(name: str, states: dict[int, dict[int, bool]], behaviors: dict[int, int] | None = None) -> Step:
    """GW-Skill-KI je Held/Slot und optional Verhalten (0 Fight, 1 Guard, 2 Avoid)."""
    for position, slots in states.items():
        agent_id = PartyHeroes.agent(position)
        if agent_id <= 0:
            return _fail(f'{name}: Held {position} nicht verfuegbar.')
        for slot, enabled in slots.items():
            Party.Heroes.SetSkillAIEnabled(agent_id, int(slot), bool(enabled))
    for position, behavior in (behaviors or {}).items():
        agent_id = PartyHeroes.agent(position)
        if agent_id > 0:
            Party.Heroes.SetHeroBehavior(agent_id, int(behavior))
    _step(f'{name}: angewendet.')
    yield from _wait(0.25)
    return True


def _wait_until(
    name: str, condition: Callable[[], bool | None], timeout_s: float, throttle_s: float, *, continue_on_timeout: bool,
) -> Step:
    """WaitUntilNode: Bedingung alle throttle_s; None = gescheitert; Timeout -> weiter (Selector-Fallback) oder Fehler."""
    _step(f'{name}: warte (max. {timeout_s:.1f} s).')
    start = time.monotonic()
    while True:
        result = condition()
        if result is None:
            return _fail(f'{name}: Mission gescheitert.')
        if result:
            _step(f'{name}: erfuellt nach {time.monotonic() - start:.1f} s.')
            return True
        if time.monotonic() - start >= timeout_s:
            if continue_on_timeout:
                _step(f'{name}: Timeout nach {timeout_s:.1f} s; weiter.')
                return True
            return _fail(f'{name}: Timeout nach {timeout_s:.1f} s.')
        yield from _wait(throttle_s)


def _run(actions: Sequence[Callable[[], Step]]) -> Step:
    """Fuehrt Aktionen nacheinander aus; die erste gescheiterte bricht ab (wie eine BT-Sequence)."""
    for make in actions:
        if not (yield from make()):
            return False
    return True


def _speedboost() -> Step:
    """Speedboost: Assassine 1 -> 0,1 s -> 5, sonst 3 und 5."""
    primary, _secondary = Agent.GetProfessionNames(Player.GetAgentID())
    if primary == 'Assassin':
        return _run([
            partial(_player_cast, 1, name='Spieler: Dwarven Stability'),
            partial(_pause, 0.1),
            partial(_player_cast, 5, name='Spieler: Dark Escape'),
        ])
    return _run([
        partial(_player_cast, 3, name='Spieler: To The Limit'),
        partial(_player_cast, 5, name="Spieler: Soldier's Speed"),
    ])


def _drop_hero_buff(position: int, slot: int, name: str) -> Step:
    """Gehaltene Verzauberung des Helden aufheben; scheitert nie."""
    agent_id = PartyHeroes.agent(position)
    skill_id = PartyHeroes.skill_id(position, slot)
    if agent_id <= 0 or skill_id <= 0:
        _step(f'{name}: Held/Skill nicht verfuegbar; nichts aufzuheben.')
    else:
        try:
            for buff in GLOBAL_CACHE.Effects.GetBuffs(agent_id):
                buff_id = int(getattr(buff, 'buff_id', 0) or 0)
                if int(getattr(buff, 'skill_id', 0) or 0) == skill_id and buff_id > 0:
                    Effects.get_instance(agent_id).DropBuff(buff_id)
                    _step(f'{name}: aufgehoben (skill_id={skill_id}, buff_id={buff_id}).')
                    break
            else:
                _step(f'{name}: war nicht aktiv; weiter.')
        except Exception as exc:
            _step(f'{name}: Aufheben fehlgeschlagen ({exc}); weiter.')
    yield from _wait(0.25)
    return True


def _hero_at(position: int, target: tuple[float, float], tolerance: float) -> bool | None:
    if _mission_failed():
        return None
    agent_id = PartyHeroes.agent(position)
    if agent_id <= 0 or Agent.IsDead(agent_id):
        return None
    return math.dist(Agent.GetXY(agent_id), target) <= tolerance


def _enemies_near_player(radius: float) -> bool | None:
    if _mission_failed():
        return None
    return bool(Enemies.near(Player.GetXY(), radius))


def _journey_gate(name: str) -> Step:
    """Weiter bei Gegnern im Umkreis 2500 oder nach 7,5 s."""
    return _wait_until(name, partial(_enemies_near_player, 2500.0), 7.5, 0.25, continue_on_timeout=True)


def _miku_at_fight_exit() -> bool | None:
    if _mission_failed():
        return None
    miku_id = _resolve_miku()
    if miku_id <= 0 or Agent.IsDead(miku_id):
        return False
    return math.dist(Agent.GetXY(miku_id), _FIGHT_EXIT) <= 2500.0


def _travel_to_kaineng() -> Step:
    """Nach Zentrum von Kaineng reisen, falls nicht schon dort."""
    if Map.GetMapID() == _KAINENG_CENTER:
        return True
    _step(f'Reise nach Zentrum von Kaineng (Map {_KAINENG_CENTER}).')
    Map.Travel(_KAINENG_CENTER)
    if not (yield from _wait_for_map(_KAINENG_CENTER, _MAP_LOAD_TIMEOUT_S)):
        return _fail('Kaineng nicht erreicht.')
    return True


def _prepare_party() -> Step:
    """Preparation: nach Kaineng, Gruppe verlassen, Helden in Build-Reihenfolge rein, Builds laden.

    Wie BT.CreateParty (LeaveParty, dann LoadParty). Ein Helden-Build wird erst geladen, wenn der Held wirklich auf seiner
    Position steht (AddHero ist nur eine Anfrage an den Server); Abstand 250 ms.
    """
    _step(f'Start; {World.map_state()}.')
    if Map.GetMapID() != _KAINENG_CENTER:
        if not (yield from _travel_to_kaineng()):
            return False
        _step('Nach der Reise 1 s warten, dann Party laden.')
        yield from _wait(1.0)
    if not Map.IsOutpost():
        return _fail('Helden nur im Aussenposten einladbar.')
    # Position = Reihenfolge der tatsaechlich eingeladenen Helden; Builds ohne Held belegen keinen Platz.
    pending: list[tuple[int, int, str, str]] = []
    for entry, (_hero_id, _role, template) in zip(_overview.assignments, _MC_HERO_BUILDS):
        if entry.hero is not None:
            pending.append((len(pending) + 1, entry.hero.hero_id, entry.hero.name, template))
    if not pending:
        return _fail('keine Helden zugeordnet (START im Reiter Main).')
    # Gruppe verlassen statt KickAllHeroes (wie CreateParty: LeaveParty vor LoadParty); wirft Helden und Soeldner raus.
    # Erst einladen, wenn die Gruppe leer ist, sonst sind Plaetze belegt; ob der Held wirklich steht, prueft das Build-Laden.
    Party.LeaveParty()
    yield from _wait(_LEAVE_PARTY_SETTLE_S)
    yield from _wait_until('Gruppe verlassen', lambda: int(Party.GetHeroCount() or 0) == 0,
                           _LEAVE_PARTY_TIMEOUT_S, 0.1, continue_on_timeout=True)
    for _position, hero_id, _name, _template in pending:
        Party.Heroes.AddHero(hero_id)
    _step(f'Lade Helden ein: {", ".join(name for _pos, _id, name, _template in pending)}')
    _load_player_build()
    deadline = time.monotonic() + _BUILD_LOAD_TIMEOUT_S
    while pending:
        if time.monotonic() > deadline:
            return _fail(f'Build nicht geladen (Held nicht in der Gruppe): {", ".join(n for _p, _i, n, _t in pending)}')
        ready = next(
            (index for index, (position, hero_id, _name, _template) in enumerate(pending)
             if (agent_id := PartyHeroes.agent(position)) and Party.Heroes.GetHeroIDByAgentID(agent_id) == hero_id),
            None,
        )
        if ready is None:
            yield
            continue
        position, _hero_id, name, template = pending.pop(ready)
        SkillBar.LoadHeroSkillTemplate(position, template)
        _step(f'Build geladen: {name} (Position {position}).')
        yield from _wait(_BUILD_LOAD_INTERVAL_S)
    _step('Alle Builds geladen.')
    return True


def _enter_mission() -> Step:
    """Kaineng -> Helden-Skill-KI fuer die Quest -> NPC -> Dialog -> A Chance Encounter."""
    _watchdog_restart()
    _mark_run_start()
    _step(f'Start; {World.map_state()}.')
    if not (yield from _travel_to_kaineng()):
        return False
    if not (yield from _skill_ai('Helden-Skill-KI fuer die Quest', _quest_skill_ai())):
        return False
    yield from _wait(1)
    px, py = Player.GetXY()
    if -1400.0 < px < -550.0 and -2000.0 < py < -1100.0:
        _step(f'Start unten links ({px:.0f}, {py:.0f}): erst Zwischenpunkt.')
        if not (yield from _move_to(*_KAINENG_DETOUR_XY, tolerance=150.0, waypoint_timeout_s=45.0)):
            return _fail('Zwischenpunkt nicht erreicht.')
    if not (yield from _move_to(*_MISSION_NPC_XY, tolerance=150.0, waypoint_timeout_s=45.0)):
        return _fail('Missions-NPC nicht erreicht.')
    yield from _wait(0.125)
    npc_id = Routines.Agents.GetNearestNPCXY(*_MISSION_NPC_XY, Range.Nearby.value)
    _step(f'NPC-Suche bei {_MISSION_NPC_XY} im Umkreis {Range.Nearby.value:.0f}: Agent {npc_id or "keiner"}.')
    if not npc_id:
        return _fail('kein NPC am Missionspunkt gefunden.')
    # Zeiten wie die BT-Knoten ChangeTarget (250 ms), InteractAgent (350 ms), SendDialog (300 ms).
    Player.ChangeTarget(npc_id)
    yield from _wait(0.25)
    Player.Interact(npc_id, False)
    yield from _wait(0.35)
    Player.SendDialog(_MISSION_DIALOG)
    _step(f'Dialog {hex(_MISSION_DIALOG)} an Agent {npc_id} gesendet.')
    yield from _wait(0.3)
    if not (yield from _wait_for_map(_A_CHANCE_ENCOUNTER, _MAP_LOAD_TIMEOUT_S)):
        return _fail('A Chance Encounter nicht geladen.')
    return True


def _in_mission() -> Step:
    if Map.GetMapID() != _A_CHANCE_ENCOUNTER:
        return _fail(f'nicht in A Chance Encounter (Map {Map.GetMapID()}).')
    yield from ()
    return True


def _place_party() -> Step:
    """Helden auf die Startpositionen flaggen, Spieler aufstellen, SoS-Held auf Guard."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    return _run([
        _in_mission,
        *[partial(_flag_hero, position, x, y) for position, x, y in _STARTING_POSITIONS],
        partial(_go, _PLAYER_HERO_SETUP_POSITION, 50.0),
        partial(_skill_ai, f'{sos}: Pre-Fight Behavior Guard', {}, {_HERO_SOS: 1}),
    ])


def _prepare_first_fight() -> Step:
    """Fallen und Geister in drei Positionen, dann Eroeffnung."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    hero = _hero_cast
    miku = lambda: int(_resolve_miku() or _MIKU_LEGACY_AGENT_ID)  # noqa: E731
    trapper_agent = partial(PartyHeroes.agent, _HERO_TRAPPER)
    sos_agent = partial(PartyHeroes.agent, _HERO_SOS)
    player = Player.GetAgentID
    return _run([
        # Bewegung und erste Fallenposition.
        partial(hero, _HERO_EARTH_ELE, 6, name=f'{earth_ele}: Fall Back'),
        partial(hero, _HERO_TRAPPER, 7, name=f"{trapper}: Serpent's Quickness"),
        partial(_pause, 0.5),
        partial(hero, _HERO_TRAPPER, 3, name=f'{trapper}: Dust Trap - Spot 1'),
        partial(hero, _HERO_SOS, 1, name=f'{sos}: Signet Of Spirits'),
        partial(hero, _HERO_BIP, 1, trapper_agent, name=f'{bip}: BiP On {trapper}'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 1, name=f'{trapper}: Spike Trap - Spot 1'),
        partial(hero, _HERO_SOS, 6, name=f'{sos}: Agony'),
        partial(hero, _HERO_BIP, 1, sos_agent, name=f'{bip}: BiP On {sos}'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 2, name=f'{trapper}: Flame Trap - Spot 1'),
        partial(hero, _HERO_BIP, 7, name=f'{bip}: Protective Was Kaolai'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 6, name=f'{trapper}: Destruction'),
        partial(hero, _HERO_SOS, 8, name=f'{sos}: Rejuvenation'),
        partial(_pause, 1.25),
        # Zweite Fallenposition.
        partial(_flag_hero, _HERO_FIRE_ELE, -6517.0, -5129.0),
        partial(_flag_hero, _HERO_TRAPPER, -6311.0, -5635.0),
        partial(_pause, 1.5),
        partial(hero, _HERO_TRAPPER, 4, name=f'{trapper}: Barbed Trap - Spot 2'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 5, name=f'{trapper}: Piercing Trap - Spot 2'),
        partial(hero, _HERO_ST, 5, name=f'{st}: Boon Of Creation'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 1, name=f'{trapper}: Spike Trap - Spot 2'),
        partial(hero, _HERO_ST, 4, name=f'{st}: Displacement'),
        partial(_pause, 2.5),
        # Dritte Fallenposition.
        partial(_flag_hero, _HERO_FIRE_ELE, -6480.0, -5258.0),
        partial(_flag_hero, _HERO_TRAPPER, -6503.0, -5937.0),
        partial(hero, _HERO_BIP, 2, name=f'{bip}: Recovery'),
        partial(hero, _HERO_ST, 1, name=f'{st}: Soul Twisting'),
        partial(_pause, 1.5),
        partial(hero, _HERO_TRAPPER, 2, name=f'{trapper}: Flame Trap - Spot 3'),
        partial(hero, _HERO_BIP, 8, name=f'{bip}: Life'),
        partial(hero, _HERO_ST, 2, name=f'{st}: Shelter'),
        partial(_pause, 2.5),
        partial(hero, _HERO_TRAPPER, 3, name=f'{trapper}: Dust Trap - Spot 3'),
        partial(hero, _HERO_ST, 3, name=f'{st}: Union'),
        partial(_pause, 1.25),
        partial(hero, _HERO_SOS, 2, miku, name=f'{sos}: Splinter Weapon On Miku'),
        partial(hero, _HERO_BIP, 1, sos_agent, name=f'{bip}: BiP On {sos} - Second'),
        partial(_pause, 1.5),
        partial(hero, _HERO_FIRE_ELE, 6, name=f'{fire_ele}: Fire Attunement'),
        partial(hero, _HERO_EARTH_ELE, 8, name=f'{earth_ele}: Earth Attunement'),
        partial(hero, _HERO_ST, 6, name=f'{st}: Earthbind'),
        # Pyre zurueck auf Position 2, Eroeffnung vorbereiten.
        partial(_flag_hero, _HERO_TRAPPER, -6311.0, -5635.0),
        partial(_flag_hero, _HERO_BIP, -5795.0, -4942.0),
        partial(_pause, 1.0),
        partial(_player_cast, 1, name='Spieler: Dwarven Stability / Feel No Pain'),
        partial(hero, _HERO_FIRE_ELE, 7, name=f'{fire_ele}: Glyph Of Sacrifice'),
        partial(hero, _HERO_TRAPPER, 4, name=f'{trapper}: Barbed Trap - Final'),
        partial(hero, _HERO_SOS, 7, name=f'{sos}: Recuperation'),
        partial(hero, _HERO_BIP, 1, trapper_agent, name=f'{bip}: BiP On {trapper} - Final'),
        partial(hero, _HERO_ST, 7, name=f'{st}: Armor Of Unfeeling'),
        partial(_pause, 1.5),
        partial(_flag_hero, _HERO_SOS, -5984.0, -5524.0),
        partial(_player_cast, 7, name='Spieler: Ebon Battle Standard Of Honor'),
        partial(_go, _PLAYER_TRAP_POSITION, 50.0),
        partial(
            hero, _HERO_FIRE_ELE, 8,
            lambda: Enemies.nearest(_PLAYER_TRAP_POSITION, _INITIAL_FOE_CAPTURE_RADIUS),
            name=f'{fire_ele}: Meteor Shower On Initial Group',
        ),
        partial(hero, _HERO_TRAPPER, 1, name=f'{trapper}: Spike Trap - Opening'),
        partial(hero, _HERO_SOS, 2, player, name=f'{sos}: Splinter Weapon On Player'),
        partial(hero, _HERO_ST, 8, player, name=f'{st}: Inspirational Speech On Player'),
        partial(_skill_ai, 'Helden-Skill-KI fuer den Kampf', {
            _HERO_EARTH_ELE: {7: True},
            _HERO_TRAPPER: {slot: True for slot in range(1, 8)},
            _HERO_PROT_MESMER: {1: True, 6: True},
            _HERO_BIP: {7: True, 8: True},
            _HERO_ST: {slot: True for slot in range(2, 8)},
        }),
    ])


def _initial_fight() -> Step:
    """Erster Kampf: >5 Gegner kaempfen, <=5 Helden umstellen + SoS erneuern, <=2 absetzen, <=1 weiter."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    reposition = {
        _HERO_EARTH_ELE: (-6531.0, -2888.0),
        _HERO_PROT_MESMER: (-6531.0, -2888.0),
        _HERO_SOS: (-6236.0, -5905.0),
        _HERO_BIP: (-6309.0, -5021.0),
        _HERO_ST: (-5974.0, -4869.0),
    }
    started = time.monotonic()
    last_action = 0.0
    next_status = started + _STATUS_INTERVAL_S
    seen: set[int] = set()
    medium_repositioned = sos_renewed = martyr_disabled = disengaged = False
    while True:
        now = time.monotonic()
        if _mission_failed():
            return _fail('Kampf: Spieler oder Miku tot.')
        elapsed = now - started
        if elapsed <= _INITIAL_FOE_CAPTURE_WINDOW_S or not seen:
            candidates = sorted(
                Enemies.near(_PLAYER_TRAP_POSITION, _INITIAL_FOE_CAPTURE_RADIUS),
                key=lambda agent_id: math.dist(Agent.GetXY(agent_id), _PLAYER_TRAP_POSITION),
            )[:_INITIAL_FOE_EXPECTED_COUNT]
            for agent_id in candidates:
                if len(seen) >= _INITIAL_FOE_EXPECTED_COUNT:
                    break
                seen.add(agent_id)
        alive = [a for a in seen if Agent.IsValid(a) and Agent.IsLiving(a) and not Agent.IsDead(a)]
        pack_established = len(seen) >= 8 or elapsed >= 20.0
        remaining = len(alive)
        if now >= next_status:
            _step(f'... Kampf seit {elapsed:.0f} s: Gruppe erkannt {len(seen)}, lebend {remaining}.')
            next_status = now + _STATUS_INTERVAL_S

        if pack_established and remaining <= 1:
            _step(f'Kampf: Uebergang, {remaining} Gegner der Startgruppe uebrig.')
            return True

        if pack_established and remaining <= 5:
            if not medium_repositioned:
                for position, (x, y) in reposition.items():
                    agent_id = PartyHeroes.agent(position)
                    if agent_id > 0:
                        Party.Heroes.FlagHero(agent_id, x, y)
                medium_repositioned = True
                _step(f'Kampf: mittlere Phase, Helden umgestellt; uebrig {remaining}.')
            if not sos_renewed:
                sos_id = PartyHeroes.agent(_HERO_SOS)
                if sos_id > 0 and math.dist(Agent.GetXY(sos_id), reposition[_HERO_SOS]) <= 150.0:
                    if PartyHeroes.skill_ready(_HERO_SOS, 1):
                        GLOBAL_CACHE.SkillBar.HeroUseSkill(0, 1, _HERO_SOS)
                        _step(f'Kampf: {sos} erneuert Signet Of Spirits.')
                    sos_renewed = True
            if not martyr_disabled:
                gwen_id = PartyHeroes.agent(_HERO_PROT_MESMER)
                if gwen_id > 0:
                    Party.Heroes.SetSkillAIEnabled(gwen_id, 1, False)
                martyr_disabled = True
                _step(f'Kampf: {prot_mesmer} Martyr-KI aus.')

        if pack_established and remaining <= 2:
            if not disengaged:
                disengaged = True
                _cast_player_now(3)
                _cast_player_now(5)
                Player.Move(_SAFE_SPOT[0], _SAFE_SPOT[1])
                _step(f'Kampf: {remaining} Gegner uebrig; Spieler setzt sich ab.')
            yield
            continue

        # Slot 1 halten, Adrenalin mit Slot 3, dann Hundred Blades (2) und Whirlwind Attack (4).
        target_id = min(alive, key=lambda a: math.dist(Agent.GetXY(a), _PLAYER_TRAP_POSITION)) if alive else 0
        if target_id and now - last_action >= 0.75:
            Player.ChangeTarget(target_id)
            Player.Interact(target_id, False)
            _cast_player_now(1)
            if PlayerState.skill_adrenaline(4) < 130:
                _cast_player_now(3)
            _cast_player_now(2)
            _cast_player_now(4, target_id)
            last_action = now

        if elapsed >= 120.0:
            return _fail('Kampf: 120-s-Timeout erreicht.')
        yield


def _wait_for_clear_area(x: float, y: float, radius: float, allowed_alive: int, stable_clear_s: float) -> Step:
    """BT.WaitForClearEnemiesInArea: naechsten Gegner im Gebiet angreifen, bis hoechstens allowed_alive uebrig (stabil)."""
    _step(f'warte auf freies Gebiet um ({x:.0f}, {y:.0f}) r={radius:.0f}, erlaubt {allowed_alive}.')
    clear_since = 0.0
    last_target = 0
    last_interact = 0.0
    next_status = time.monotonic() + _STATUS_INTERVAL_S
    while True:
        now = time.monotonic()
        if _mission_failed():
            return _fail('Gebiet freikaempfen: Spieler oder Miku tot.')
        player_xy = Player.GetXY()
        enemies = sorted(
            (a for a in AgentArray.GetEnemyArray()
             if a > 0 and Agent.IsValid(a) and Agent.IsAlive(a) and math.dist((x, y), Agent.GetXY(a)) <= radius),
            key=lambda a: math.dist(player_xy, Agent.GetXY(a)),
        )
        if now >= next_status:
            _step(f'... Gegner im Gebiet: {len(enemies)}.')
            next_status = now + _STATUS_INTERVAL_S
        if Routines.Checks.Player.IsCasting():
            yield
            continue
        if len(enemies) <= allowed_alive:
            last_target = 0
            if clear_since <= 0.0:
                clear_since = now
            if now - clear_since >= stable_clear_s:
                _step(f'Gebiet frei ({len(enemies)} Gegner uebrig).')
                return True
            yield
            continue
        clear_since = 0.0
        target_id = enemies[0]
        if target_id != last_target or now - last_interact >= 0.75:
            Player.ChangeTarget(target_id)
            Player.Interact(target_id, False)
            last_target = target_id
            last_interact = now
        yield


def _finish_initial_fight() -> Step:
    """Rest der ersten Gruppe abwarten, Helden fuer den Weg umstellen, zum Ausgang des Kampfplatzes."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    return _run([
        partial(_wait_for_clear_area, *_PLAYER_TRAP_POSITION, 8_000.0, 1, 0.5),
        partial(_optional_hero_cast, _HERO_EARTH_ELE, 6, name=f'{earth_ele}: Fall Back (optional)'),
        _speedboost,
        partial(_skill_ai, f'{sos}: Avoid fuer den Weg', {}, {_HERO_SOS: 2}),
        partial(_flag_hero, _HERO_SOS, -4770.0, -3330.0),
        partial(_flag_hero, _HERO_ST, -4770.0, -3330.0),
        partial(_skill_ai, 'Helden-Skill-KI fuer den Weg', {
            _HERO_SOS: {slot: False for slot in range(1, 9)},
            _HERO_ST: {slot: False for slot in range(1, 9)},
            _HERO_BIP: {7: False},
        }, {_HERO_SOS: 2}),
        partial(_go, _FIGHT_EXIT, 125.0),
    ])


def _run_to_stairs() -> Step:
    """Mit Miku und den Helden vom Kampfplatz zur Treppe laufen."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    hero = _hero_cast
    return _run([
        _in_mission,
        partial(_flag_all, -7047.0, -2651.0),
        partial(
            hero, _HERO_BIP, 1, partial(PartyHeroes.agent, _HERO_SOS),
            condition=lambda: Agent.GetHealth(PartyHeroes.agent(_HERO_BIP)) > 0.5,
            name=f'{bip}: BiP On {sos} Before Journey',
        ),
        partial(_flag_hero, _HERO_SOS, -2195.0, 33.0),
        partial(_flag_hero, _HERO_ST, -2195.0, 33.0),
        partial(hero, _HERO_SOS, 3, partial(PartyHeroes.agent, _HERO_ST), aftercast_ms=2_500, name=f'{sos}: Recall On {st}'),
        _speedboost,
        partial(_go, _FIGHT_EXIT, 150.0),
        partial(_wait_until, 'Miku am Ausgang', _miku_at_fight_exit, 40.0, 0.25, continue_on_timeout=False),
        partial(hero, _HERO_PROT_MESMER, 1, name=f'{prot_mesmer}: Martyr Before Journey'),
        _speedboost,
        partial(_go, _JOURNEY_MID_1, 125.0),
        *[partial(_go, point, 75.0) for point in _STAIR_PATH],
        partial(_go, _JOURNEY_MID_2, 125.0),
        partial(_flag_hero, _HERO_SOS, *_STAIRS_APPROACH),
        partial(_flag_hero, _HERO_ST, *_STAIRS_APPROACH),
        partial(_journey_gate, 'Journey Gate 1'),
        partial(_drop_hero_buff, _HERO_SOS, 3, f'{sos}: Drop Journey Recall'),
        _speedboost,
        partial(_go, _JOURNEY_MID_3, 125.0),
        partial(_go, _JOURNEY_MID_4, 125.0),
        partial(_flag_hero, _HERO_PROT_MESMER, -5606.0, -2916.0),
        partial(_flag_hero, _HERO_BIP, -5606.0, -2916.0),
        partial(_flag_hero, _HERO_SOS, -1605.0, -5676.0),
        partial(_flag_hero, _HERO_ST, *_XANDRA_SPIKE_SETUP_POSITION),
        partial(_journey_gate, 'Journey Gate 2'),
        _speedboost,
        partial(_go, _STAIRS_APPROACH, 100.0),
        partial(_go, _FARM_POSITION, 35.0),
        partial(hero, _HERO_BIP, 7, name=f'{bip}: Protective Was Kaolai At Farm'),
        partial(hero, _HERO_ST, 8, Player.GetAgentID, name=f'{st}: Inspirational Speech On Player At Farm'),
    ])


def _prepare_stairs_defense() -> Step:
    """Treppe: Geister setzen (PlaceSpirits 0-3)."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    hero = _hero_cast
    return _run([
        partial(_flag_hero, _HERO_ST, *_XANDRA_SPIKE_SETUP_POSITION),
        partial(
            _wait_until, f'{st} an der Spike-Position',
            partial(_hero_at, _HERO_ST, _XANDRA_SPIKE_SETUP_POSITION, 175.0), 15.0, 0.25, continue_on_timeout=False,
        ),
        partial(hero, _HERO_SOS, 8, name=f'{sos}: Rejuvenation At Farm'),
        partial(hero, _HERO_ST, 1, name=f'{st}: Soul Twisting At Farm'),
        partial(hero, _HERO_ST, 2, aftercast_ms=1_000, name=f'{st}: Shelter'),
        partial(_flag_hero, _HERO_SOS, -1605.0, -5676.0),
        partial(hero, _HERO_SOS, 3, partial(PartyHeroes.agent, _HERO_ST), aftercast_ms=2_500, name=f'{sos}: Recall On {st} At Farm'),
        partial(hero, _HERO_ST, 3, aftercast_ms=750, name=f'{st}: Union'),
        partial(hero, _HERO_ST, 4, aftercast_ms=750, name=f'{st}: Displacement'),
        partial(hero, _HERO_ST, 7, name=f'{st}: Armor Of Unfeeling'),
        partial(_flag_hero, _HERO_ST, *_XANDRA_RETREAT_POSITION),
        partial(hero, _HERO_SOS, 7, name=f'{sos}: Recuperation At Farm'),
        partial(_flag_hero, _HERO_PROT_MESMER, -7047.0, -2651.0),
        partial(_flag_hero, _HERO_BIP, -7047.0, -2651.0),
        partial(_flag_hero, _HERO_TRAPPER, -7047.0, -2651.0),
        partial(_flag_hero, _HERO_FIRE_ELE, -7047.0, -2651.0),
        partial(_flag_hero, _HERO_EARTH_ELE, -7047.0, -2651.0),
    ])


def _wait_for_purity_ball() -> Step:
    """Wellen-Tracker; Spike erst bei mindestens _min_foes_for_spike Gegnern in 1000."""
    defense: dict[str, float] = {'action_ms': 0.0}
    phase = 'arrival'
    phase_started = time.monotonic()
    last_new = phase_started
    seen: dict[int, list[int]] = {}  # Agent -> [touched_200 (0/1), dwell_ticks]
    next_status = phase_started + _STATUS_INTERVAL_S
    decide_since = short_since = 0.0  # seit wann "Welle komplett" mit genug bzw. zu wenig Gegnern gilt
    while True:
        if _mission_failed():
            return _fail('Welle: Spieler oder Miku tot.')
        now = time.monotonic()
        enemy_dist2 = Enemies.with_dist2(Player.GetXY())
        in_1000 = {a for a, d2 in enemy_dist2 if d2 <= 1000.0 * 1000.0}
        in_200 = {a for a, d2 in enemy_dist2 if d2 <= 200.0 * 200.0}
        _defensive_ball_tick(defense)

        if phase == 'arrival':
            if len(in_1000) >= 4 or now - phase_started >= 30.0:
                phase = 'gather'
                phase_started = last_new = now
                seen = {}
                _step(f'Welle: Tracker startet mit {len(in_1000)} Gegner(n) in 1000.')
            else:
                if now >= next_status:
                    _step(f'... Welle: warte auf Ankunft, {len(in_1000)} Gegner in 1000.')
                    next_status = now + _STATUS_INTERVAL_S
                yield
                continue

        for agent_id in in_1000:
            if agent_id not in seen and len(seen) < 60:
                seen[agent_id] = [0, 0]
                last_new = now
        for agent_id, foe in seen.items():
            if agent_id in in_200:
                foe[0] = 1
            foe[1] = foe[1] + 1 if agent_id in in_1000 and not foe[0] else 0
        resolved = sum(1 for a, foe in seen.items() if foe[0] or a not in in_1000 or foe[1] >= _WAVE_DWELL_TICKS)

        count_seen = len(seen)
        nearby = len(in_1000)
        no_arrivals = count_seen >= 60 or now - last_new >= 18.0
        enough = nearby >= _min_foes_for_spike
        if now >= next_status:
            _step(f'... Welle: in 1000 {nearby}/{_min_foes_for_spike}, gesehen {count_seen}, erledigt {resolved}.')
            next_status = now + _STATUS_INTERVAL_S
        # Entscheidung erst, wenn sie _WAVE_STABLE_S lang gilt: ein einzelner Frame ohne Gegner (Log 2026-11-06:
        # 57 in 1000, zwei Sekunden spaeter 0) machte sonst alle "erledigt" und die Welle "zu klein".
        complete = no_arrivals and resolved >= math.ceil(count_seen * 0.98)
        timed_out = now - phase_started >= 60.0
        if (complete or timed_out) and enough:
            decide_since = decide_since or now
            if now - decide_since >= _WAVE_STABLE_S:
                if complete:
                    _step(f'Welle komplett: in 1000 {nearby}, gesehen {count_seen}, erledigt {resolved}.')
                else:
                    _step(f'Welle: 60-s-Grenze erreicht, gesehen {count_seen}, erledigt {resolved}; weiter.')
                return True
            short_since = 0.0
        elif complete or timed_out:
            short_since = short_since or now
            if now - short_since >= _WAVE_STABLE_S:
                px, py = Player.GetXY()
                detail = (f'in 1000 {nearby}/{_min_foes_for_spike}, gesehen {count_seen}, '
                          f'Gegner gesamt {len(enemy_dist2)}, Spieler ({px:.0f}, {py:.0f})')
                if complete:
                    return _fail(f'Welle zu klein: {detail}.')
                return _fail(f'Welle: 60-s-Grenze mit zu wenigen Gegnern: {detail}.')
            decide_since = 0.0
        else:
            decide_since = short_since = 0.0
        yield


def _wait_for_allies_out_of_range(timeout_s: float) -> Step:
    """Alle Verbuendeten ausserhalb Kompass; Timeout -> trotzdem weiter."""
    defense: dict[str, float] = {'action_ms': 0.0}

    def _all_out() -> bool | None:
        if _mission_failed():
            return None
        _defensive_ball_tick(defense)
        return not World.allies_in_compass()

    if not (yield from _wait_until('Verbuendete ausser Reichweite', _all_out, timeout_s, 0.25, continue_on_timeout=True)):
        return False
    remaining = World.allies_in_compass()
    if remaining:
        _step(f'    noch im Kompass: {", ".join(remaining)}.')
    return True


def _wait_for_spike_resources(timeout_s: float) -> Step:
    """Energie > 15 und Adrenalin Slot 4 >= 130; Timeout -> trotzdem Spike."""
    defense: dict[str, float] = {'action_ms': 0.0}

    def _ready() -> bool | None:
        if _mission_failed():
            return None
        _defensive_ball_tick(defense)
        return PlayerState.energy() > _SPIKE_MIN_ENERGY and PlayerState.skill_adrenaline(4) >= 130

    return _wait_until('Ressourcen fuer den Spike', _ready, timeout_s, 0.1, continue_on_timeout=True)


def _spike_ministry_of_purity() -> Step:
    """Spike: Waffe auf Spieler, SoS-Held weg, Honor, Hundred Blades, Whirlwind auf Gegner in 200."""
    fire_ele, earth_ele, trapper, prot_mesmer, sos, bip, st = _hero_names()
    return _run([
        partial(_hero_cast, _HERO_SOS, 4, Player.GetAgentID, aftercast_ms=1_500, name=f'{sos}: Weapon Support On Player'),
        partial(_flag_hero, _HERO_SOS, -4950.0, -7955.0),
        partial(_drop_hero_buff, _HERO_SOS, 3, f'{sos}: Drop Farm Recall'),
        partial(_wait_for_allies_out_of_range, 15.0),
        partial(_wait_for_spike_resources, 15.0),
        partial(_player_cast, 7, name='Spieler: Ebon Battle Standard Of Honor'),
        partial(_player_cast, 2, name='Spieler: Hundred Blades'),
        partial(_pause, 0.25),
        lambda: _player_cast(4, lambda: Enemies.nearest(Player.GetXY(), 200.0), name='Spieler: Whirlwind Attack'),
        partial(_pause, 3.0),
    ])


def _wanted_loot(ground: list[GroundItem]) -> list[tuple[int, str]]:
    """(Agent, Beschriftung) der Items am Boden, die laut Loot-Filter aufgehoben werden; naechste zuerst."""
    wanted: list[tuple[int, str]] = []
    for item in ground:
        action, key = _LOOT_RULES.decide(item_keys(item.model_id, item.dye_color, item.item_type, item.rarity))
        if action == PICK:
            wanted.append((item.agent_id, f'{_LOOT_RULES.label(key)} (Model {item.model_id})'))
    return wanted


def _scan_unknown_loot() -> Generator[None, None, None]:
    """Scan 1: Namen unbekannter Items am Boden anfragen; Scan 2: Daten merken (_UNKNOWN_ITEMS, ohne Doppelte).

    Nach dem Loot traegt check_inventory_items sie in items.json ein."""
    first = [item for item in GroundItems.around(Player.GetXY(), _LOOT_RADIUS) if not is_known_model(item.model_id)]
    if not first:
        return
    for item in first:
        GroundItems.request_name(item.item_id)
    yield from _wait(_UNKNOWN_NAME_WAIT_S)
    map_name = Map.GetMapName()
    seen = new = 0
    for item in GroundItems.around(Player.GetXY(), _LOOT_RADIUS):
        if is_known_model(item.model_id):
            continue
        seen += 1
        new += _UNKNOWN_ITEMS.record(item.model_id, item.dye_color, item.item_type, item.rarity,
                                     GroundItems.details(item.item_id), map_name)
    if seen:
        _step(f'Unbekannte Items am Boden: {seen}, davon neu: {new}.')


def _record_picked(announced: set[int], ground: list[GroundItem], drop_keys: dict[int, str], gold_before: int,
                   item_ids: dict[int, int]) -> None:
    """Aufgehoben = angeklickt und nicht mehr am Boden. Ohne Gold nach _PICKED (Platz im Inventar).

    Gold wird in der Gruppe geteilt (Helden-Anteile verfallen); als Wert zaehlt das Plus im Inventar.
    """
    still_there = {item.agent_id for item in ground}
    gold_key = ''
    picked: dict[int, str] = {}  # Item-ID -> Schluessel in _DROPS
    for agent_id in announced - still_there:
        is_gold = False
        if agent_id in drop_keys:
            key = drop_keys[agent_id]
            _DROPS.picked(key)
            if _DROPS.entries[key].get('ItemType') == int(ItemType.Gold_Coin):
                gold_key = key
                is_gold = True
        if not is_gold and agent_id in item_ids:
            picked[item_ids[agent_id]] = drop_keys.get(agent_id, '')
    _PICKED.remember(picked)
    if gold_key:
        gained = int(GLOBAL_CACHE.Inventory.GetGoldOnCharacter()) - gold_before
        _DROPS.add_gold(gold_key, gained)
        _step(f'Gold: +{gained}.')


def _note_ground_file_ids(items: Sequence[GroundItem]) -> None:
    """ModelFileIDs der Items am Boden merken (fuer die Bilder aus dem Gw.dat), auch fremde und liegen gelassene."""
    for item in items:
        if item.model_file_id > 0:
            _ground_file_ids[item.model_id] = item.model_file_id


def _loot() -> Step:
    """Ohne Rueckreise (die macht Schritt 2): aufheben, was der Loot-Filter will.

    Fertig, wenn 1,5 s lang nichts Gewuenschtes mehr liegt; nach 15 s geht es trotzdem weiter.
    """
    yield from _wait(_LOOT_APPEAR_S)
    _note_ground_file_ids(GroundItems.around(Player.GetXY(), _LOOT_RADIUS))
    yield from _scan_unknown_loot()
    started = time.monotonic()
    clear_since = 0.0
    last_interact = 0.0
    announced: set[int] = set()
    drop_keys: dict[int, str] = {}  # Agent -> Schluessel in _DROPS, jedes Item einmal gezaehlt
    item_ids: dict[int, int] = {}  # Agent -> Item-ID, fuer _PICKED
    gold_before = int(GLOBAL_CACHE.Inventory.GetGoldOnCharacter())
    map_name = Map.GetMapName()
    while True:
        now = time.monotonic()
        ground = GroundItems.mine(Player.GetXY(), _LOOT_RADIUS)
        _note_ground_file_ids(ground)  # auch Items, die erst waehrend des Loots auftauchen
        for item in ground:
            item_ids.setdefault(item.agent_id, item.item_id)
            if item.agent_id not in drop_keys:
                drop_keys[item.agent_id] = _DROPS.seen(item.model_id, item.dye_color, item.item_type, item.rarity,
                                                       GroundItems.details(item.item_id), map_name)
        wanted = _wanted_loot(ground)
        if not wanted:
            clear_since = clear_since or now
            if now - clear_since >= _LOOT_CLEAR_S:
                _record_picked(announced, ground, drop_keys, gold_before, item_ids)
                _step(f'Alles aufgehoben ({len(announced)} Item(s)).')
                return True
        else:
            clear_since = 0.0
            if now - started >= _LOOT_TIMEOUT_S:
                _record_picked(announced, ground, drop_keys, gold_before, item_ids)
                _step(f'Loot nach {_LOOT_TIMEOUT_S:.0f} s abgebrochen, liegt noch: {", ".join(n for _a, n in wanted)}.')
                return True
            if now - last_interact >= _LOOT_INTERACT_S:
                agent_id, name = wanted[0]
                if agent_id not in announced:
                    announced.add(agent_id)
                    _step(f'Hebe auf: {name}.')
                Player.Interact(agent_id, False)
                last_interact = now
        yield


def _item_handling() -> Step:
    """Nur wenn Merchant, Salvage oder Identifikation an ist (Config, jedes fuer sich) und weniger Plaetze frei sind
    als "Schritt 12 unter X frei" (0 = immer), sonst uebersprungen. Am Ende: Inventar-Grenzen (Stop, Gold).

    Nach Loot: nach Kaineng, alle Haendler suchen, zum naechsten
    Kaufmann (nach Laufweg) gehen, ihn ansprechen, Gold und Werkzeuge ins Log, dann Aufgehobenes in der Reihenfolge
    Identifikation -> Salvage -> Merchant abarbeiten (_process_picked_items).

    Der Watchdog laeuft seit Enter A Chance Encounter weiter und wird hier nicht zurueckgesetzt.
    """
    if not _item_handling_active():
        _step('Merchant, Salvage und Identifikation in Config aus: Item Handling uebersprungen.')
        return (yield from _check_inventory_limits())
    free = _free_slots()
    if _handling_free_slots > 0 and free >= _handling_free_slots:
        _step(f'{free} freie Plaetze, nicht unter {_handling_free_slots}: Item Handling uebersprungen.')
        return (yield from _check_inventory_limits())
    if not (yield from _travel_to_kaineng()):
        return False
    traders = yield from Traders.find()
    if not traders:
        return _fail('keine Haendler gefunden.')
    px, py = Player.GetXY()

    def distance(agent_id: int) -> float:
        x, y = Agent.GetXY(agent_id)
        return math.hypot(px - x, py - y)

    traders.sort(key=lambda trader: distance(trader[0]))
    for agent_id, name in traders:
        x, y = Agent.GetXY(agent_id)
        _step(f'    Haendler: {name} (Agent {agent_id}) bei ({x:.0f}, {y:.0f}), Abstand {distance(agent_id):.0f}.')
    merchants = [(agent_id, name) for agent_id, name in traders if Traders.is_merchant(name)]
    if not merchants:
        return _fail(f'kein Kaufmann ([Kaufmann]/[Kauffrau]/[Merchant]) unter {len(traders)} Haendler(n).')
    # Naechster Kaufmann nach Laufweg (AutoPathing), nicht Luftlinie: in der Stadt liegen Mauern dazwischen.
    walks: list[tuple[float, int, str]] = []
    for agent_id, name in merchants:
        walk = yield from Traders.walk_distance(*Agent.GetXY(agent_id))
        walks.append((walk, agent_id, name))
        _step(f'    Kaufmann: {name} (Agent {agent_id}), Laufweg {walk:.0f}, Luftlinie {distance(agent_id):.0f}.')
    walks.sort()
    walk, agent_id, name = walks[0]
    x, y = Agent.GetXY(agent_id)
    others = ', '.join(f'{other} ({other_walk:.0f})' for other_walk, _id, other in walks[1:])
    _step(f'Naechster Kaufmann von ({px:.0f}, {py:.0f}): {name} (Agent {agent_id}) bei ({x:.0f}, {y:.0f}), '
          f'Laufweg {walk:.0f}' + (f'; weitere: {others}.' if others else '.'))
    if not (yield from _move_to(x, y, tolerance=_MERCHANT_TOLERANCE, waypoint_timeout_s=45.0)):
        return _fail(f'{name} nicht erreicht.')
    attempt = yield from Traders.open_window(agent_id)
    if not attempt:
        return _fail(f'Haendlerfenster von {name} nicht geoeffnet.')
    _step(f'{name} angesprochen, Haendlerfenster offen (Versuch {attempt}).')
    _log_inventory_status()
    yield from _process_picked_items()
    return (yield from _check_inventory_limits())


def _free_slots() -> int:
    """Freie Plaetze in den angehakten und vorhandenen Taschen (Config, neben Merchant)."""
    return Inventory.free_slots([bag for bag in _merchant_bags if _merchant_bag_active(bag)])


def _gold_limit_reason() -> str:
    """Mehr Gold im Inventar als Platin x 1000 + Gold (Config): Grund zum Stoppen, sonst ''."""
    gold = int(GLOBAL_CACHE.Inventory.GetGoldOnCharacter())
    max_gold = _max_platinum * 1000 + _max_gold
    if max_gold > 0 and gold > max_gold:
        return f'{Format.gold(gold)} im Inventar, mehr als {Format.gold(max_gold)}'
    return ''


def _inventory_limit_reason() -> str:
    """Grund zum Stoppen laut Config (freie Plaetze, Gold), sonst ''."""
    free = _free_slots()
    if _stop_free_slots > 0 and free <= _stop_free_slots:
        return f'nur noch {free} freie Plaetze (Stop bei {_stop_free_slots})'
    return _gold_limit_reason()


def _check_inventory_limits() -> Step:
    """Grenzen aus Config; ueberschritten: Stopp mit Meldung (main() fuehrt ihn im naechsten Frame aus)."""
    global _stop_request
    reason = _inventory_limit_reason()
    if not reason:
        _step(f'Inventar: {_free_slots()} freie Plaetze, '
              f'{Format.gold(Inventory.gold())}.')
        return True
    _stop_request = reason
    while True:
        yield


def _reset_stopping_to_town() -> None:
    global _stopping_to_town
    _stopping_to_town = False


def _travel_then_stop(reason: str) -> Generator[None, None, None]:
    """Nach Stop wegen freier Plaetze: nach Kaineng reisen, dann endet der Ablauf (main() raeumt auf)."""
    global _mission_step_name
    _mission_step_name = 'Reise nach Kaineng, dann Stop'
    yield from _travel_to_kaineng()
    _note_stop(reason)


def _stop_to_town(reason: str) -> None:
    """Lauf beenden (Fehlerliste), nach Kaineng reisen, dort mit Meldung stoppen."""
    global _mission_runner, _stopping_to_town
    _record_error(f'Gestoppt: {reason}')
    _end_run()
    Log.write(f'Mission: {reason}; reise nach Kaineng und stoppe dort.', PySystem.Console.MessageType.Warning,
              MODULE_NAME)
    _stopping_to_town = True
    _mission_runner = _travel_then_stop(reason)


def _process_free_slot_stop() -> None:
    """Gemeldeter Stop (Gold nach Loot) sofort; sonst jede Sekunde (Map geladen): freie Plaetze <= "Stop bei X
    frei" -> Lauf beenden, nach Kaineng, stoppen. Nicht in Item Handling (Schritt 12): der ist schon auf dem Weg in
    die Stadt und schafft gerade Platz; dort prueft das Ende des Schritts."""
    global _free_slot_polled, _town_stop_request
    if _town_stop_request:
        reason, _town_stop_request = _town_stop_request, ''
        if _mission_runner is not None and not _stopping_to_town:
            _stop_to_town(reason)
        return
    if _mission_runner is None or _stopping_to_town or _stop_free_slots <= 0:
        return
    if _mission_step_index == _ITEM_HANDLING_INDEX:
        return
    now = time.monotonic()
    if now - _free_slot_polled < _FREE_SLOT_POLL_S or not Map.IsMapReady():
        return
    _free_slot_polled = now
    free = _free_slots()
    if free > _stop_free_slots:
        return
    _stop_to_town(f'nur noch {free} freie Plaetze (Stop bei {_stop_free_slots})')


def _process_stop_request() -> None:
    """Stopp, den ein Schritt angefordert hat (z. B. Inventar-Grenzen): wie beim Logout mit Meldung."""
    global _stop_request
    if not _stop_request:
        return
    reason, _stop_request = _stop_request, ''
    if _mission_runner is None:
        return
    _record_error(f'Gestoppt: {reason}')
    _end_run()
    _note_stop(reason)


def _process_picked_items() -> Generator[None, None, None]:
    """Vom Bot aufgehobene Items in der Reihenfolge Identifikation -> Salvage -> Merchant bearbeiten.

    Identifikation: Haken Identifizieren in Items > Item-Info, noch nicht identifiziert. Salvage: Haken in
    Items > Salvage, laut Spiel
    wiederverwertbar, nicht angepasst. Merchant: Haken in Items > Merchant, aus angehakten Taschen, verkaeuflich
    (ItemActions.sellable, Haendlerwert > 0). Zerlegtes und Verkauftes faellt aus Items > Drops > Aufgehoben.
    """
    picked = _PICKED.current()
    if not picked:
        _step('Keine aufgehobenen Items zu bearbeiten.')
        return
    _step(f'Aufgehobene Items: {len(picked)}.')
    usage = GLOBAL_CACHE.Item.Usage
    if _identify_enabled:
        ids = [item_id for item_id in picked if not usage.IsIdentified(item_id)
               and _IDENTIFY_RULES.wants(inventory_item_keys(item_id))]
        if ids:
            _log_items('Identifiziere', ids)
            yield from _pause_before('Identifizieren')
            yield from ItemActions.identify(ids, _step, item_label)
            _step(f'Identifiziert: {sum(1 for item_id in ids if usage.IsIdentified(item_id))} von {len(ids)}.')
        else:
            _step('Identifizieren: nichts laut Items > Item-Info.')
    if _salvage_enabled:
        picked = _PICKED.current()
        ids = [item_id for item_id in picked if _SALVAGE_RULES.wants(inventory_item_keys(item_id))
               and usage.IsSalvageable(item_id) and not GLOBAL_CACHE.Item.Properties.IsCustomized(item_id)]
        if ids:
            _log_items('Zerlege', ids)
            yield from _pause_before('Zerlegen')
            salvaged = yield from ItemActions.salvage(ids, _step, item_label)
            for item_id in salvaged:
                if picked[item_id]:
                    _DROPS.salvaged(picked[item_id])
            _step(f'Zerlegt: {len(salvaged)} von {len(ids)}.')
        else:
            _step('Zerlegen: nichts laut Items > Salvage.')
    if not _merchant_enabled:
        return
    picked = _PICKED.current()
    allowed = Inventory.item_ids([bag for bag in _merchant_bags if _merchant_bag_active(bag)])
    ids = [item_id for item_id in picked if item_id in allowed
           and _MERCHANT_RULES.wants(inventory_item_keys(item_id)) and ItemActions.sellable(item_id)
           and int(GLOBAL_CACHE.Item.Properties.GetValue(item_id) or 0) > 0]
    if not ids:
        _step('Verkaufen: nichts laut Items > Merchant (und angehakten Taschen).')
        return
    _log_items('Verkaufe', ids)
    yield from _pause_before('Verkaufen')
    gold_before = Inventory.gold()
    sold = yield from ItemActions.sell(ids)
    for item_id in sold:
        if picked[item_id]:
            _DROPS.sold(picked[item_id])
    _step(f'Verkauft: {len(sold)} von {len(ids)}, Gold +{Inventory.gold() - gold_before}.')


def _pause_before(action: str) -> Generator[None, None, None]:
    """Mit Pausen (Config) vor Identifizieren, Zerlegen und Verkaufen anhalten; die Liste steht schon im Log.
    WEITER (neben STOP) setzt fort, STOP bricht ab. Der Watchdog steht waehrend der Pause."""
    global _item_handling_paused
    if not _item_handling_pauses:
        return
    _item_handling_paused = True
    _step(f'PAUSE vor {action}: WEITER setzt fort, STOP bricht ab.')
    while _item_handling_paused and _item_handling_pauses:  # Haken in Config weg: sofort weiter
        yield
    _item_handling_paused = False
    _step(f'Weiter mit {action}.')


def _log_items(action: str, item_ids: list[int]) -> None:
    _step(f'{action} {len(item_ids)} Item(s):')
    for item_id in item_ids:
        _step(f'    {item_label(item_id)}')


def _log_inventory_status() -> None:
    """Beim Kaufmann: Gold im Inventar; Identifizierungs- bzw. Wiederverwertungswerkzeuge mit Restnutzungen, nur
    wenn Identifikation bzw. Salvage in Config an ist."""
    _step(f'Gold im Inventar: {Format.gold(Inventory.gold())}.')
    if _identify_enabled:
        _log_kits('Identifizierungswerkzeug', Kits.id_kits())
    if _salvage_enabled:
        _log_kits('Wiederverwertungswerkzeug', Kits.salvage_kits())


def _log_kits(label: str, kits: list[tuple[int, str]]) -> None:
    """Anzahl und Restnutzungen je Werkzeug ins Log; (Item-ID, Art oder '')."""
    if not kits:
        _step(f'{label}: keins im Inventar.')
        return
    uses = [int(GLOBAL_CACHE.Item.Usage.GetUses(item_id)) for item_id, _kind in kits]
    _step(f'{label}: {len(kits)} Stueck, zusammen {sum(uses)} Nutzungen.')
    for (item_id, kind), count in zip(kits, uses):
        model_id = int(GLOBAL_CACHE.Item.GetModelID(item_id))
        _step(f'    {label}{f" ({kind})" if kind else ""}: Model {model_id}, noch {count} Nutzungen.')


_MISSION_STEPS: tuple[tuple[str, Callable[[], Step]], ...] = (
    ('Preparation', _prepare_party),
    ('Enter A Chance Encounter', _enter_mission),
    ('Place Player And Heroes', _place_party),
    ('Prepare First Fight', _prepare_first_fight),
    ('Fight Initial Group', _initial_fight),
    ('Finish Initial Fight', _finish_initial_fight),
    ('Run To Stairs', _run_to_stairs),
    ('Prepare Stairs Defense', _prepare_stairs_defense),
    ('Wait For Purity Ball', _wait_for_purity_ball),
    ('Spike Ministry Of Purity', _spike_ministry_of_purity),
    ('Loot', _loot),
    ('Item Handling', _item_handling),
)
_LOOP_START_INDEX = 1  # nach Item Handling weiter mit Enter A Chance Encounter (reist bei Bedarf nach Kaineng)
_LOOT_INDEX = 10  # nach Loot (Schritt 11) wird der Lauf gezaehlt; Item Handling gehoert nicht mehr dazu
# Tod-Check und Survivor nur von Place Player And Heroes (Schritt 3) bis Loot (Schritt 11), nicht in Item Handling.
_DEATH_CHECK_FROM_INDEX = 2
_DEATH_CHECK_TO_INDEX = _LOOT_INDEX
_ITEM_HANDLING_INDEX = _LOOT_INDEX + 1
_RETRY_PAUSE_S = 3.0  # Pause vor dem Neustart nach einem gescheiterten Schritt
# Gestoppt wird nur mit STOP, beim Logout (Charakterauswahl) oder wenn so lange keine Map geladen ist.
_OFFLINE_TIMEOUT_S = 120.0


def _death_check_active() -> bool:
    return _DEATH_CHECK_FROM_INDEX <= _mission_step_index <= _DEATH_CHECK_TO_INDEX


def _restart_index(step_index: int) -> int:
    """Neustart nach einem Fehler: in Preparation wieder Preparation, sonst ab Schritt 2."""
    return 0 if step_index <= 0 else _LOOP_START_INDEX


def _run_mission(start_index: int, delay_s: float = 0.0) -> Generator[None, None, None]:
    """Schritte ab start_index nacheinander, nach dem letzten wieder ab Schritt 2; endet nie von selbst.

    Tod (Spieler oder Miku) in Schritt 3 bis 11: sofort weiter mit Schritt 2. Jeder andere gescheiterte
    Schritt: nach kurzer Pause Neustart (Preparation wieder ab Preparation, sonst ab Schritt 2).
    """
    global _mission_step_name, _mission_step_index, _run_elapsed_s, _death_restart_armed, _last_fail_reason
    global _town_stop_request, _stop_after_run
    total = len(_MISSION_STEPS)
    if delay_s > 0.0:
        _mission_step_name = f'Neustart ab {_MISSION_STEPS[start_index][0]} in {delay_s:.0f} s'
        yield from _wait(delay_s)
    while True:
        restart: int | None = None
        pause = 0.0
        for number, (name, step) in enumerate(_MISSION_STEPS[start_index:], start_index + 1):
            _mission_step_name = f'{number}/{total} {name}'
            _mission_step_index = number - 1
            Log.write(
                f'Mission: === Schritt {number}/{total}: {name} ===', PySystem.Console.MessageType.Info, MODULE_NAME
            )
            started = time.monotonic()
            _last_fail_reason = ''
            if not (yield from step()):
                dead = _dead_party_member() if _death_check_active() else ''
                restart = _restart_index(_mission_step_index)
                _record_error(f'{dead} tot' if dead else _last_fail_reason or 'Schritt gescheitert')
                if dead:
                    _death_restart_armed = False
                    _log_death_restart(dead)
                else:
                    pause = _RETRY_PAUSE_S
                    Log.write(
                        f'Mission: Schritt {number}/{total} "{name}" gescheitert; '
                        f'Neustart ab {_MISSION_STEPS[restart][0]} in {pause:.0f} s.',
                        PySystem.Console.MessageType.Error, MODULE_NAME,
                    )
                break
            _step(f'Schritt {number}/{total} "{name}" fertig nach {time.monotonic() - started:.1f} s.')
            if _mission_step_index == _LOOT_INDEX:
                _record_run()
                # Jeder Lauf (Schritt 12 laeuft meist nicht): fehlende Angaben in items.json aus den Taschen, die
                # ModelFileIDs vom Boden und unbekannte Items ergaenzen, in einem Schreibvorgang.
                _step(check_inventory_items(MODULE_NAME, _ground_file_ids, _UNKNOWN_ITEMS))
                _ground_file_ids.clear()
                for new_item in _UNKNOWN_ITEMS.take_written():
                    _record_error(f'{new_item} in items.json eingetragen', count=False)
                # Beim Loot kommt Gold dazu: Gold-Grenze schon hier, dann nach Kaineng und stoppen (main()).
                _town_stop_request = _gold_limit_reason()
                while _town_stop_request:
                    yield
        if _stop_after_run:
            # Lauf zu Ende (fertig oder gescheitert): kein Neustart, nach Kaineng und stoppen; zaehlt nicht als Fehler.
            _stop_after_run = False
            _mission_step_index = -1
            _mission_step_name = 'Reise nach Kaineng, dann Stop'
            yield from _travel_to_kaineng()
            _note_stop('nach dem Lauf (STOP NACH LAUF)', PySystem.Console.MessageType.Warning)
            return
        if restart is not None:
            _mission_step_index = -1
            if pause > 0.0:
                _mission_step_name = f'Neustart ab {_MISSION_STEPS[restart][0]} in {pause:.0f} s'
                yield from _wait(pause)
            start_index = restart
            _run_elapsed_s = 0.0
            continue
        start_index = _LOOP_START_INDEX


def _start_mission(start_index: int, delay_s: float = 0.0) -> None:
    global _mission_runner
    if not Party.IsPartyLeader():
        Log.write('Mission nur als Gruppenleiter.', PySystem.Console.MessageType.Warning, MODULE_NAME)
        return
    global _run_elapsed_s, _timer_last_tick, _last_stop_reason
    _run_elapsed_s = 0.0
    _timer_last_tick = 0.0
    _last_stop_reason = ''
    _mission_runner = _run_mission(start_index, delay_s)


def _end_run() -> None:
    """Ablauf beenden (STOP, Logout/offline oder vor einem Neustart)."""
    global _mission_runner, _mission_step_name, _mission_step_index, _timer_last_tick, _watchdog_active
    if _mission_runner is not None:
        _mission_runner.close()
    _mission_runner = None
    _mission_step_name = ''
    _mission_step_index = -1
    _timer_last_tick = 0.0
    _watchdog_active = False
    _resume_item_handling()  # eine Pause endet mit dem Ablauf
    _reset_stopping_to_town()


def _note_stop(reason: str, message_type: PySystem.MessageType = PySystem.MessageType.Error) -> None:
    """Stopp ins Log und als letzten Stoppgrund unter START (Reiter Main) merken; START loescht ihn."""
    global _last_stop_reason
    _last_stop_reason = f'{datetime.now():%H:%M:%S} {reason}'
    Log.write(f'Mission gestoppt: {reason}.', message_type, MODULE_NAME)


def _stop_mission() -> None:
    global _stop_after_run
    _stop_after_run = False
    _end_run()
    _note_stop('von Hand (STOP)', PySystem.Console.MessageType.Warning)


def _toggle_stop_after_run() -> None:
    global _stop_after_run
    _stop_after_run = not _stop_after_run
    Log.write('Mission: Stop nach diesem Lauf ' + ('vorgemerkt.' if _stop_after_run else 'zurueckgenommen.'),
              PySystem.Console.MessageType.Info, MODULE_NAME)


_REQUIRED_WIDGETS = ('Enemy Tracker', 'Environment Upkeeper')
# Stoeren den Ablauf: HeroAI steuert sonst auch den Spieler (Targeting/Combat) und greift z. B. an der Treppe an.
_FORBIDDEN_WIDGETS = ('HeroAI',)


def _ensure_required_widgets() -> bool:
    """Bei START: benoetigte Widgets einschalten, stoerende ausschalten; geht das nicht, startet der Bot nicht
    (Grund unter START)."""
    switched_on, errors = WidgetCheck.ensure_enabled(_REQUIRED_WIDGETS)
    switched_off, off_errors = WidgetCheck.ensure_disabled(_FORBIDDEN_WIDGETS)
    errors += off_errors
    for name in switched_on:
        Log.write(f"Widget '{name}' war aus und wurde aktiviert.", PySystem.Console.MessageType.Info, MODULE_NAME)
    for name in switched_off:
        Log.write(f"Widget '{name}' war an und wurde deaktiviert.", PySystem.Console.MessageType.Info, MODULE_NAME)
    if errors:
        _note_stop('; '.join(errors))
        return False
    return True


def _watchdog_restart() -> None:
    """Am Anfang von Enter A Chance Encounter: Watchdog starten bzw. zuruecksetzen."""
    global _watchdog_active, _watchdog_elapsed_s
    _step('Watchdog zurueckgesetzt.' if _watchdog_active else 'Watchdog gestartet.')
    _watchdog_active = True
    _watchdog_elapsed_s = 0.0


def _process_watchdog() -> None:
    """Laufzeit und Watchdog hochzaehlen (dt max. 1 s); abgelaufener Watchdog stoppt den Ablauf."""
    global _run_elapsed_s, _watchdog_elapsed_s, _timer_last_tick
    if _mission_runner is None:
        return
    now = time.monotonic()
    dt = min(now - _timer_last_tick, 1.0) if _timer_last_tick > 0.0 else 0.0
    _timer_last_tick = now
    _run_elapsed_s += dt
    if not _watchdog_active or _item_handling_paused:  # in der Pause steht der Watchdog
        return
    _watchdog_elapsed_s += dt
    if _watchdog_minutes > 0 and _watchdog_elapsed_s >= _watchdog_minutes * 60.0:
        step = _mission_step_name
        Log.write(
            f'Watchdog: Ablauf dauert laenger als {_watchdog_minutes} Min (Schritt {step}, Map {Map.GetMapID()}); '
            f'Neustart ab {_MISSION_STEPS[0][0]}.',
            PySystem.Console.MessageType.Error, MODULE_NAME,
        )
        _record_error(f'Watchdog: laenger als {_watchdog_minutes} Min')
        # Neuer Lauf ab Schritt 1: Preparation reist nach Kaineng und laedt die Party neu; Enter setzt den Watchdog zurueck.
        _end_run()
        _start_mission(0)


def _log_death_restart(dead: str) -> None:
    Log.write(
        f'{dead} tot (Schritt {_mission_step_name}, Map {Map.GetMapID()}); '
        f'Neustart ab {_MISSION_STEPS[_LOOP_START_INDEX][0]}.',
        PySystem.Console.MessageType.Error, MODULE_NAME,
    )


def _process_death() -> None:
    """Spieler oder Miku tot in Schritt 3 bis 11 (jeden Frame geprueft): sofort Neustart ab Schritt 2.

    Bis die Reise nach Kaineng greift, liegen die Toten noch ein paar Frames im Explorable;
    deshalb erst wieder scharf, wenn beide einmal lebend gesehen wurden.
    """
    global _death_restart_armed
    if _mission_runner is None or not _death_check_active():
        return
    if not Map.IsMapReady() or not Map.IsExplorable() or not int(Player.GetAgentID() or 0):
        return
    dead = _dead_party_member()
    if not dead:
        _death_restart_armed = True
        return
    if not _death_restart_armed:
        return
    _death_restart_armed = False
    _log_death_restart(dead)
    _record_error(f'{dead} tot')
    # Schritt 2 reist nach Kaineng und setzt den Watchdog zurueck; die Party bleibt geladen.
    _end_run()
    _start_mission(_LOOP_START_INDEX)


def _process_survivor() -> None:
    """Survivor in Schritt 3 bis 11 (jeden Frame): HP unter min HP -> sofort Neustart ab Schritt 2."""
    health = _SURVIVOR.check(active=_mission_runner is not None and _death_check_active())
    if health is None:
        return
    Log.write(
        f'Survivor: {_SURVIVOR.describe(health)} (Schritt {_mission_step_name}, Map {Map.GetMapID()}); '
        f'Neustart ab {_MISSION_STEPS[_LOOP_START_INDEX][0]}.',
        PySystem.Console.MessageType.Error, MODULE_NAME,
    )
    _record_error(f'Survivor: HP unter {_SURVIVOR.percent} %')
    # Wie beim Tod: Schritt 2 reist nach Kaineng; bis Schritt 3 ist der Check aus.
    _end_run()
    _start_mission(_LOOP_START_INDEX)


def _watchdog_remaining() -> float | None:
    """Restzeit in Sekunden; None, wenn der Watchdog aus ist oder nicht laeuft."""
    if _watchdog_minutes <= 0 or not _watchdog_active or _mission_runner is None:
        return None
    return max(0.0, _watchdog_minutes * 60.0 - _watchdog_elapsed_s)


def _commendation_count() -> int:
    return int(GLOBAL_CACHE.Inventory.GetModelCount(int(ModelID.Ministerial_Commendation)))


def _mark_run_start() -> None:
    """Am Anfang von Enter A Chance Encounter: Laufzeit neu, Auszeichnungen im Inventar merken."""
    global _run_start_commendations, _run_elapsed_s
    _run_elapsed_s = 0.0
    _run_start_commendations = _commendation_count()
    _step(f'Statistik: {_run_start_commendations} Auszeichnung(en) im Inventar.')


def _drop_rate(stats: dict[str, float]) -> str:
    """Auszeichnungen je Lauf in Prozent; mehr als eine pro Lauf ergibt mehr als 100 %."""
    return f'{stats["commendations"] / stats["runs"] * 100.0:.1f}%' if stats['runs'] else '-'


def _per_run(stats: dict[str, float]) -> str:
    return f'{stats["commendations"] / stats["runs"]:.2f}' if stats['runs'] else '-'


def _avg_time(stats: dict[str, float]) -> str:
    return Format.duration(stats['run_seconds'] / stats['runs']) if stats['runs'] else '-'


def _save_total_stats() -> None:
    for key in _STATS_KEYS:
        _SETTINGS.set_float(_STATS_SECTION, key, _total_stats[key])


def _record_run() -> None:
    """Nach Loot: Lauf zaehlen (Auszeichnungen = Inventar jetzt minus Lauf-Anfang), Gesamt speichern."""
    global _run_start_commendations, _last_run_commendations, _last_run_s, _run_elapsed_s
    gained = max(0, _commendation_count() - _run_start_commendations) if _run_start_commendations >= 0 else 0
    duration = _run_elapsed_s
    for stats in (_session_stats, _total_stats):
        stats['runs'] += 1
        stats['commendations'] += gained
        stats['drop_runs'] += 1 if gained else 0
        stats['run_seconds'] += duration
    _save_total_stats()
    _last_run_commendations = gained
    _last_run_s = duration
    _run_start_commendations = -1
    _run_elapsed_s = 0.0
    Log.write(
        f'Mission: Lauf fertig nach {Format.duration(duration)}; Auszeichnungen {gained}, '
        f'gesamt {int(_total_stats["commendations"])}, Drop-Rate {_drop_rate(_total_stats)}; '
        f'weiter mit {_MISSION_STEPS[_LOOT_INDEX + 1][0]}.',
        PySystem.Console.MessageType.Success, MODULE_NAME,
    )


def _record_error(reason: str, count: bool = True) -> None:
    """Lauf nicht sauber zu Ende: zaehlen und in die Liste der Sitzung. count=False: nur ein Hinweis in der Liste
    (z. B. neues Item in items.json), zaehlt nicht als Fehler und nicht in die Fehlerquote."""
    global _error_count
    if count:
        _error_count += 1
    entry = (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), _mission_step_name or '-', ' '.join(reason.split()))
    _errors.append(entry)
    del _errors[:-_ERROR_LIST_MAX]


def _draw_errors() -> None:
    """Fehler der Sitzung: Anzahl, Anteil an allen beendeten Laeufen, Liste (neueste oben)."""
    PyImGui.text_colored('Fehler (Sitzung)', _STAT_CYAN)
    finished = _session_stats['runs'] + _error_count
    rate = f'{_error_count / finished * 100.0:.1f}%' if finished else '-'
    _draw_stat_table('##woc_error_stats', ('Errors', 'Clean', 'Rate'), (
        str(_error_count), str(int(_session_stats['runs'])), rate,
    ), {0: _STAT_RED} if _error_count else None)
    if not _errors:
        PyImGui.text_disabled('Noch keine Fehler.')
    else:
        _draw_error_list()
        if PyImGui.button('FEHLER-LOG SPEICHERN##WoCErrorExport'):
            _get_error_dialog().open_save(_ERROR_EXPORT_TITLE, valid_types='.txt', start_path=_error_export_dir)
    _draw_error_export()


def _draw_error_list() -> None:
    if len(_errors) < _error_count:
        PyImGui.text_disabled(f'Liste zeigt die letzten {len(_errors)}.')
    if PyImGui.begin_child('##woc_error_list', (0, 200), True):
        if PyImGui.begin_table('##woc_error_table', 3, _TABLE_FLAGS):
            for title in ('Time', 'Step', 'Reason'):
                PyImGui.table_setup_column(title)
            PyImGui.table_headers_row()
            for when, step, reason in reversed(_errors):
                PyImGui.table_next_row()
                PyImGui.table_next_column()
                PyImGui.text(when)
                PyImGui.table_next_column()
                PyImGui.text(step)
                PyImGui.table_next_column()
                PyImGui.text(reason)
            PyImGui.end_table()
    PyImGui.end_child()


def _get_error_dialog() -> FileDialog:
    global _error_dialog
    if _error_dialog is None:
        _error_dialog = FileDialog()
    return _error_dialog


def _export_errors(path: str) -> str:
    """Fehlerliste der Sitzung als Text (Tab-getrennt); ohne Dateiname bzw. Endung gilt <Bot>_error_log.txt."""
    global _error_export_dir
    if not os.path.basename(path) or os.path.isdir(path):
        path = os.path.join(path, _ERROR_EXPORT_NAME)
    if not os.path.splitext(path)[1]:
        path += '.txt'
    lines = ['Time\tStep\tReason', *('\t'.join(entry) for entry in _errors)]
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
    except OSError as exc:
        Log.write(f'Fehler-Log nicht gespeichert ({exc}).', PySystem.Console.MessageType.Error, MODULE_NAME)
        return f'Nicht gespeichert: {exc}'
    _error_export_dir = os.path.dirname(path)
    return f'Gespeichert: {path} ({len(_errors)} Fehler)'


def _draw_error_export() -> None:
    """Explorer jeden Frame zeichnen, solange er offen ist; liefert den Pfad einmal nach dem Bestaetigen."""
    global _error_export_message
    if _error_dialog is not None:
        path = _error_dialog.draw()
        if path:
            _error_export_message = _export_errors(path)
    if _error_export_message:
        PyImGui.text_disabled(_error_export_message)


def _reset_total_stats() -> None:
    _total_stats.update(dict.fromkeys(_STATS_KEYS, 0.0))
    _save_total_stats()
    Log.write('Gesamtstatistik zurueckgesetzt.', PySystem.Console.MessageType.Success, MODULE_NAME)


def _draw_stat_table(table_id: str, labels: tuple[str, ...], values: tuple[str, ...],
                     colors: dict[int, tuple[float, float, float, float]] | None = None) -> None:
    """Eine Zeile Kopf (dunkel hinterlegt), eine Zeile Werte; Spalten 82 px breit."""
    if not PyImGui.begin_table(table_id, len(labels), _TABLE_FLAGS):
        return
    for label in labels:
        PyImGui.table_setup_column(label, PyImGui.TableColumnFlags.WidthFixed, 82.0)
    PyImGui.table_next_row(0, 22.0)
    PyImGui.table_set_bg_color(2, _STAT_HEADER_BG, -1)
    for index, label in enumerate(labels):
        PyImGui.table_set_column_index(index)
        PyImGui.text(label)
    PyImGui.table_next_row(0, 22.0)
    for index, value in enumerate(values):
        PyImGui.table_set_column_index(index)
        PyImGui.text_colored(value, (colors or {}).get(index, _STAT_WHITE))
    PyImGui.end_table()


def _draw_statistics_tab() -> None:
    """Sitzung, Gesamt und Laufzeit; Watchdog-Restzeit weiss > 30 s, gelb 15-30 s, rot < 15 s."""
    PyImGui.spacing()
    PyImGui.text_colored('Ministeriumsauszeichnungen', COLOR_ELITE)
    PyImGui.separator()
    PyImGui.spacing()
    session, total = _session_stats, _total_stats
    PyImGui.text_colored('Sitzung', _STAT_CYAN)
    _draw_stat_table('##woc_session_stats', ('Runs', 'Last', 'Drops', 'Avg', 'Rate'), (
        str(int(session['runs'])), str(_last_run_commendations), str(int(session['commendations'])),
        _per_run(session), _drop_rate(session),
    ))
    PyImGui.spacing()
    PyImGui.text_colored('Gesamt', _STAT_CYAN)
    _draw_stat_table('##woc_total_stats', ('Runs', 'Drops', 'Drop Runs', 'Avg', 'Rate'), (
        str(int(total['runs'])), str(int(total['commendations'])), str(int(total['drop_runs'])),
        _per_run(total), _drop_rate(total),
    ))
    PyImGui.spacing()
    PyImGui.text_colored('Laufzeit (m:ss.mmm)', _STAT_CYAN)
    remaining = _watchdog_remaining()
    if remaining is None:
        watchdog_text, watchdog_color = '-', _STAT_WHITE
    else:
        watchdog_text = Format.duration(remaining)
        watchdog_color = _STAT_WHITE if remaining > 30.0 else _STAT_YELLOW if remaining >= 15.0 else _STAT_RED
    _draw_stat_table('##woc_time_stats', ('Current', 'Last', 'Avg Sess.', 'Avg Total', 'Watchdog'), (
        Format.duration(_run_elapsed_s) if _mission_runner is not None else '-',
        Format.duration(_last_run_s) if _last_run_s > 0.0 else '-',
        _avg_time(session), _avg_time(total), watchdog_text,
    ), {4: watchdog_color})
    PyImGui.spacing()
    _draw_stats_reset()
    PyImGui.spacing()
    _draw_errors()


def _draw_stats_reset() -> None:
    """GESAMT ZURUECKSETZEN mit Rueckfrage; betrifft nur die gespeicherten Gesamtwerte."""
    global _stats_reset_pending
    if not _stats_reset_pending:
        if PyImGui.button('GESAMT ZURUECKSETZEN##WoCStatsReset'):
            _stats_reset_pending = True
        return
    PyImGui.text_colored('Gesamtstatistik wirklich zuruecksetzen?', COLOR_ELITE)
    if PyImGui.button('JA##WoCStatsResetYes'):
        _reset_total_stats()
        _stats_reset_pending = False
    PyImGui.same_line(0, 8)
    if PyImGui.button('ABBRECHEN##WoCStatsResetNo'):
        _stats_reset_pending = False


def _resume_item_handling() -> None:
    global _item_handling_paused
    _item_handling_paused = False


def _draw_mission_controls() -> None:
    """STOP und STOP NACH LAUF waehrend des Ablaufs; sonst START: erst pruefen, nur wenn alles da ist, ab Schritt 1.

    STOP NACH LAUF schaltet um: vorgemerkt heisst der Knopf WEITERLAUFEN und nimmt es zurueck."""
    global _stop_after_run
    if _mission_runner is not None:
        if PyImGui.button('    STOP##WoCMissionStop'):
            _stop_mission()
            return
        if not _stopping_to_town and _mission_step_index >= 0:
            PyImGui.same_line(0, 10)
            label = 'WEITERLAUFEN' if _stop_after_run else 'STOP NACH LAUF'
            if PyImGui.button(f'{label}##WoCStopAfterRun'):
                _toggle_stop_after_run()
        if _item_handling_paused:
            PyImGui.same_line(0, 10)
            if PyImGui.button('WEITER##WoCItemHandlingResume'):
                _resume_item_handling()
        PyImGui.same_line(0, 10)
        PyImGui.text(f'Schritt {_mission_step_name}' + (' (PAUSE)' if _item_handling_paused else '')
                     + (' (Stop nach Lauf)' if _stop_after_run else ''))
        return
    if PyImGui.button('    START##WoCMissionStart') and _check_requirements() and _ensure_required_widgets():
        _stop_after_run = False
        _start_mission(0)
    if _last_stop_reason and _mission_runner is None:
        PyImGui.text_colored(f'Gestoppt {_last_stop_reason}', COLOR_WARN)


def _process_mission_runner() -> None:
    global _mission_runner
    if _mission_runner is None:
        return
    try:
        next(_mission_runner)
    except StopIteration:
        _end_run()
    except Exception as exc:
        # Sonst bricht main() jeden Frame ab und der Ablauf "haengt" ohne Meldung; danach wie ein gescheiterter Schritt.
        restart = _restart_index(_mission_step_index)
        Log.write(
            f'Mission: Fehler {exc!r}; Neustart ab {_MISSION_STEPS[restart][0]} in {_RETRY_PAUSE_S:.0f} s.\n'
            f'{traceback.format_exc()}',
            PySystem.Console.MessageType.Error, MODULE_NAME,
        )
        _record_error(f'Programmfehler {exc!r}')
        _mission_runner = None
        _end_run()
        _start_mission(restart, _RETRY_PAUSE_S)


def _process_connection() -> None:
    """Stoppt den Ablauf bei Logout (Charakterauswahl) oder wenn zu lange keine Map geladen ist (Verbindung weg)."""
    global _no_map_since
    if _mission_runner is None:
        _no_map_since = 0.0
        return
    if Map.Pregame.InCharacterSelectScreen():
        reason = 'Charakterauswahl (ausgeloggt)'
    elif Map.IsMapReady():
        _no_map_since = 0.0
        return
    else:
        now = time.monotonic()
        _no_map_since = _no_map_since or now
        if now - _no_map_since < _OFFLINE_TIMEOUT_S:
            return
        reason = f'seit {_OFFLINE_TIMEOUT_S:.0f} s keine Map geladen (Verbindung verloren?)'
    _no_map_since = 0.0
    _record_error(f'Gestoppt: {reason}')
    _end_run()
    _note_stop(reason)


def _draw_missing_by_profession() -> None:
    # Nur Klassen mit fehlenden Skills, Spielreihenfolge, klassenlose zuletzt; ohne Fehlendes entfaellt die Tabelle.
    counts = SkillData.count_by_profession(_overview.missing_skills())
    if not counts:
        return
    PyImGui.text('Fehlende Skills je Klasse')
    if not PyImGui.begin_table('##woc_missing_by_profession', 3, _TABLE_FLAGS):
        return
    for label in ('Klasse', 'Elite', 'Normal'):
        PyImGui.table_setup_column(label)
    PyImGui.table_headers_row()
    for profession, elite, normal in counts:
        color = _PROFESSION_COLORS.get(profession)
        if color is not None:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, color)
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        if profession:
            _draw_profession(profession)
        else:
            _draw_icon_slot(None, PyImGui.get_text_line_height())
            PyImGui.text('klassenlos')
        for count in (elite, normal):
            PyImGui.table_next_column()
            PyImGui.text(str(count) if count else '-')
        if color is not None:
            PyImGui.pop_style_color(1)
    PyImGui.end_table()


def _draw_info_tab() -> None:
    PyImGui.spacing()
    _draw_missing_by_profession()
    _draw_missing_skills()
    _draw_trainer_offers()
    PyImGui.spacing()
    _draw_all_heroes()


def _draw_build(label: str, build: SkillBuild | None, available: dict[int, bool] | None = None) -> None:
    if not PyImGui.tree_node(label):
        return
    if build is None:
        PyImGui.text_colored('Template ungueltig', COLOR_MISSING)
    else:
        PyImGui.text(f'Klassen: {Names.profession(build.primary)}/{Names.profession(build.secondary)}')
        attributes = ', '.join(f'{Names.attribute(attr)} {value}' for attr, value in build.attributes)
        PyImGui.text_wrapped(f'Attribute: {attributes}')
        icon_size = PyImGui.get_text_line_height()
        for slot, skill_id in enumerate(build.skills, 1):
            PyImGui.text(f'{slot}.')
            PyImGui.same_line(0, 4)
            _draw_icon_slot(Icons.skill(skill_id), icon_size)
            PyImGui.text(SkillData.name(skill_id))
            if available is not None and skill_id:
                PyImGui.same_line(0, 10)
                _draw_status(available.get(skill_id, False), 'OK', 'fehlt')
    PyImGui.tree_pop()


def _draw_builds_tab() -> None:
    PyImGui.spacing()
    if PyImGui.collapsing_header('Helden-Builds##WoCHeroBuilds'):
        if _overview.unlocked_skills is None:
            PyImGui.text_disabled('Freischaltungen und Zuordnung erst nach START im Reiter Main.')
        assigned = {entry.role: entry.hero for entry in _overview.assignments}
        for index, entry in enumerate(HERO_BUILDS):
            hero_row = assigned.get(entry.role)
            hero_label = hero_row.name if hero_row else 'kein Held'
            _draw_build(f'{entry.role} - {hero_label}##hero_build_{index}', entry.build, _overview.unlocked_skills)

    if PyImGui.collapsing_header('Spieler-Build##WoCPlayerBuilds'):
        primary = Skills.player_primary()
        if primary == 0:
            PyImGui.text_colored('Primaerklasse des Spielers nicht lesbar (eingeloggt?).', COLOR_MISSING)
            return
        if _overview.learnt_skills is None:
            PyImGui.text_disabled('Gelernte Skills erst nach START im Reiter Main.')
        build = Builds.player_build_for(primary, PLAYER_BUILDS)
        if build is None:
            PyImGui.text_colored(f'Kein gueltiges Template fuer Primaerklasse {Names.profession(primary)}.', COLOR_MISSING)
            return
        _draw_build(f'{Names.profession(primary)}##player_build_{primary}', build, _overview.learnt_skills)


def _item_handling_active() -> bool:
    """Item Handling (Schritt 12) laeuft, wenn Merchant, Salvage oder Identifikation an ist; jedes fuer sich."""
    return _merchant_enabled or _salvage_enabled or _identify_enabled


def _merchant_bag_active(bag: Bags) -> bool:
    """Merchant darf aus dieser Tasche verkaufen: Haken gesetzt und Tasche beim aktuellen Char vorhanden."""
    return _merchant_bags.get(bag, False) and Inventory.bag_present(bag)


def _draw_inventory_limits() -> None:
    """Inventar-Einstellungen (0 = aus): Schritt 12 unter X frei, Stop bei X frei, Gold max. (Platin, Gold)."""
    global _handling_free_slots, _stop_free_slots, _max_platinum, _max_gold
    PyImGui.push_item_width(90)
    raw = PyImGui.input_int('Schritt 12 unter X frei##WoCMinFreeSlots', _handling_free_slots, 1, 5)
    value = min(_MAX_FREE_SLOTS, max(0, int(raw)))
    if value != _handling_free_slots:
        _handling_free_slots = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'min_free_slots', value)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Item Handling (Schritt 12) nur, wenn in den angehakten Taschen weniger Plaetze frei sind;\n'
                            f'sonst uebersprungen (jetzt frei: {_free_slots()}). 0 = immer.')
    PyImGui.same_line(0, 20)
    raw = PyImGui.input_int('Stop bei X frei##WoCStopFreeSlots', _stop_free_slots, 1, 5)
    value = min(_MAX_FREE_SLOTS, max(0, int(raw)))
    if value != _stop_free_slots:
        _stop_free_slots = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'stop_free_slots', value)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Sind in den angehakten Taschen so wenige oder weniger Plaetze frei, beendet der Bot den\n'
                            'Lauf (egal in welchem Schritt), reist nach Kaineng und stoppt. In Schritt 12 erst an\n'
                            f'dessen Ende (jetzt frei: {_free_slots()}). 0 = aus.')
    raw = PyImGui.input_int('Platin##WoCMaxPlatinum', _max_platinum, 1, 10)
    value = min(100, max(0, int(raw)))
    if value != _max_platinum:
        _max_platinum = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'max_platinum', value)
    tooltip = ('Hoechstens so viel Gold im Inventar (Platin x 1000 + Gold). Ist es nach dem Loot oder nach\n'
               'Item Handling mehr, reist der Bot nach Kaineng und stoppt\n'
               f'(jetzt: {Format.gold(Inventory.gold())}). 0 = aus.')
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip(tooltip)
    PyImGui.same_line(0, 10)
    raw = PyImGui.input_int('Gold max.##WoCMaxGold', _max_gold, 1, 100)
    value = min(999, max(0, int(raw)))
    if value != _max_gold:
        _max_gold = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'max_gold', value)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip(tooltip)
    PyImGui.pop_item_width()


def _draw_config_tab() -> None:
    global _watchdog_minutes, _min_foes_for_spike, _merchant_enabled, _salvage_enabled, _identify_enabled
    global _item_handling_pauses, _log_casts
    PyImGui.spacing()
    # Ein Schalter fuer alle Logs (WoC und shared_data), gehalten in shared_data.common.
    enabled = PyImGui.checkbox('Log (Fehler erscheinen immer)##WoCLog', Log.is_enabled())
    if enabled != Log.is_enabled():
        Log.set_enabled(enabled)
        _SETTINGS.set_bool(_CONFIG_SECTION, 'log', enabled)
    enabled = PyImGui.checkbox('Kampf-Casts loggen##WoCLogCasts', _log_casts)
    if enabled != _log_casts:
        _log_casts = enabled
        _SETTINGS.set_bool(_CONFIG_SECTION, 'log_casts', enabled)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Jeden schnellen Spieler-Cast in den Kampfschleifen ins Log (Schritt 5, 9 und die\n'
                            'Wartezeiten in 10): Skill, Ziel, HP und Energie direkt davor.\n'
                            'Nur mit Log an. Zur Fehlersuche; sonst aus lassen, es wird viel.')
    PyImGui.spacing()
    enabled = PyImGui.checkbox('Merchant##WoCMerchant', _merchant_enabled)
    if enabled != _merchant_enabled:
        _merchant_enabled = enabled
        _SETTINGS.set_bool(_CONFIG_SECTION, 'merchant', enabled)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Aufgehobene Items laut Items > Merchant verkaufen (Schritt 12).')
    for bag, checked in _merchant_bags.items():
        PyImGui.same_line(0, 12)
        # Fehlende Tasche (Groesse 0, auch ohne geladene Map): ausgegraut und ohne Haken. Die Sicherung bleibt,
        # sonst loescht jeder Ladebildschirm alle Haken; ein Char mit der Tasche zeigt den Haken wieder.
        missing = not Inventory.bag_present(bag)
        PyImGui.begin_disabled(missing)
        value = PyImGui.checkbox(f'{_BAG_NAMES.get(bag, bag.name)}##WoCMerchantBag{int(bag)}', checked and not missing)
        PyImGui.end_disabled()
        if value != checked and not missing:
            _merchant_bags[bag] = value
            _SETTINGS.set_bool(_CONFIG_SECTION, f'merchant_bag_{int(bag)}', value)
        if PyImGui.is_item_hovered(PyImGui.HoveredFlags.AllowWhenDisabled):
            PyImGui.set_tooltip('Tasche nicht vorhanden.' if missing
                                else 'Merchant verkauft nur aus angehakten Taschen.')
    _draw_inventory_limits()
    # Merchant, Salvage und Identifikation sind unabhaengig; Item Handling (Schritt 12) laeuft, wenn eins an ist.
    enabled = PyImGui.checkbox('Salvage##WoCSalvage', _salvage_enabled)
    if enabled != _salvage_enabled:
        _salvage_enabled = enabled
        _SETTINGS.set_bool(_CONFIG_SECTION, 'salvage', enabled)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Aufgehobene Items laut Items > Salvage zerlegen (Schritt 12).')
    enabled = PyImGui.checkbox('Identifikation##WoCIdentify', _identify_enabled)
    if enabled != _identify_enabled:
        _identify_enabled = enabled
        _SETTINGS.set_bool(_CONFIG_SECTION, 'identify', enabled)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Aufgehobene Items laut Items > Item-Info (Identifizieren) identifizieren,\n'
                            'vor Salvage und Merchant (Schritt 12).')
    enabled = PyImGui.checkbox('Pause vor jeder Aktion##WoCItemHandlingPauses', _item_handling_pauses)
    if enabled != _item_handling_pauses:
        _item_handling_pauses = enabled
        _SETTINGS.set_bool(_CONFIG_SECTION, 'item_handling_pauses', enabled)
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Schritt 12 haelt vor Identifizieren, Zerlegen und Verkaufen an; die Liste steht im Log.\n'
                            'WEITER (neben STOP) setzt fort. Ohne Haken laeuft Schritt 12 durch.')
    PyImGui.spacing()
    PyImGui.text('Watchdog')
    raw = PyImGui.slider_int('Abbruch nach X Min (0 = aus)##WoCWatchdog', _watchdog_minutes, 0, _WATCHDOG_MAX_MINUTES)
    value = min(_WATCHDOG_MAX_MINUTES, max(0, int(raw)))
    if value != _watchdog_minutes:
        _watchdog_minutes = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'watchdog_minutes', value)
    PyImGui.spacing()
    PyImGui.text('Spike')
    raw = PyImGui.slider_int(
        'Mindestens X Gegner in 1000##WoCMinFoes', _min_foes_for_spike, _MIN_FOES_MIN, _MIN_FOES_MAX
    )
    value = min(_MIN_FOES_MAX, max(_MIN_FOES_MIN, int(raw)))
    if value != _min_foes_for_spike:
        _min_foes_for_spike = value
        _SETTINGS.set_int(_CONFIG_SECTION, 'min_foes_for_spike', value)
    PyImGui.spacing()
    PyImGui.text('Survivor')
    raw = PyImGui.slider_int('min HP (0 = aus)##WoCMinHp', _SURVIVOR.percent, 0, 100, '%d%%')
    _SURVIVOR.set_percent(int(raw))
    if PyImGui.is_item_hovered():
        PyImGui.set_tooltip('Ab Schritt 3: faellt die Spieler-HP darunter, Neustart ab Schritt 2.')


def DrawWindow() -> None:
    # Groesse frei ziehbar: Startgroesse nur beim allerersten Oeffnen, danach merkt sich ImGui die Groesse.
    # Breite Tabellen bekommen bei schmalem Fenster eine horizontale Scrollleiste statt abgeschnitten zu werden.
    PyImGui.set_next_window_size(620, 720, PyImGui.ImGuiCond.FirstUseEver)
    PyImGui.set_next_window_size_constraints((360, 240), (4096, 4096))
    if ImGui.begin(MODULE_NAME, None, PyImGui.WindowFlags.HorizontalScrollbar):
        ImGui.DrawTexture(TEXTURE, 64, 64)
        PyImGui.same_line(0, 10)
        PyImGui.text_wrapped(MODULE_DESCRIPTION)
        PyImGui.separator()
        if PyImGui.begin_tab_bar('WoCTabBar'):
            if PyImGui.begin_tab_item('Main'):
                _draw_main_tab()
                PyImGui.end_tab_item()
            if PyImGui.begin_tab_item('Statistik'):
                _draw_statistics_tab()
                PyImGui.end_tab_item()
            if PyImGui.begin_tab_item('Items'):
                # Merchant/Salvage/Identifizieren nur, wenn die Aktion in Config an ist.
                draw_rules_tab(_LOOT_RULES, 'woc_loot', MODULE_NAME, _DROPS,
                               merchant=_MERCHANT_RULES if _merchant_enabled else None,
                               salvage=_SALVAGE_RULES if _salvage_enabled else None,
                               identify=_IDENTIFY_RULES if _identify_enabled else None)
                PyImGui.end_tab_item()
            # Info nur nach einer Pruefung (START), bei der etwas fehlt.
            if _overview.heroes and not _requirements_ok and PyImGui.begin_tab_item('Info'):
                _draw_info_tab()
                PyImGui.end_tab_item()
            if PyImGui.begin_tab_item('Builds'):
                _draw_builds_tab()
                PyImGui.end_tab_item()
            if PyImGui.begin_tab_item('Config'):
                _draw_config_tab()
                PyImGui.end_tab_item()
            PyImGui.end_tab_bar()
    ImGui.end()


def main() -> None:
    _process_connection()  # zuerst: offline bzw. ausgeloggt stoppt, statt neu zu starten
    _process_stop_request()
    _process_free_slot_stop()
    _process_watchdog()
    _process_death()  # vor dem Ablauf, damit kein Schritt am Tod scheitert und stoppt
    _process_survivor()
    _process_mission_runner()
    watch_items_json(MODULE_NAME)
    DrawWindow()


if __name__ == '__main__':
    main()
