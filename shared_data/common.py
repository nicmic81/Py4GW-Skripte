"""Gemeinsame Werte fuer die Bots in Bots/custom (nur Werte, keine GUI).

Je Thema eine Klasse mit statischen Methoden:

    Log        ein Schalter und eine Funktion fuer alle Log-Ausgaben
    Names      deutsche/lesbare Namen fuer Klassen, Helden, Attribute
    Heroes     freigeschaltete Helden aus WorldContext.hero_info_array
    Builds     Skill-Templates decodieren und Helden zuordnen
    SkillData  Skill-Namen (englisch/deutsch), Sortierung, Zaehlung je Klasse
    Trainers   wo man fehlende Skills kaufen kann
    Skills     Laufzeitabfragen: freigeschaltet, gelernt, Primaerklasse
    Icons      Pfade zu Skill-, Klassen- und Elite-Icons
    Locations  deutsche Ortsnamen -> Aussenposten-ID, Freischaltung
    Maps       Map-IDs nach Namen aus maps.json (Quelle: BotsHub GWA2_ID_Maps.au3)
    Overview   Gesamtauswertung fuer die Pruefung bei START (Datenklasse mit Overview.read)
    PartyHeroes  Helden in der Gruppe nach Partyposition: Agent, Name, Skillleiste
    PlayerState  Energie, Skill bereit/Adrenalin, Effekt aktiv
    Enemies      lebende Gegner um einen Punkt
    World        Kartenzustand, Verbuendete im Kompass
    Survivor     Spieler-HP gegen min HP (Titel Ueberlebender); den Regler zeichnet der Bot
    Inventory    Taschen, Plaetze, freie Plaetze, Gold
    PickedItems  vom Bot aufgehobene Items, gemerkt nach Platz (Item-IDs aendern sich beim Kartenwechsel)
    Traders      Haendler finden (Titel im Namen), Laufweg, Haendlerfenster oeffnen
    Kits         Identifizierungs- und Wiederverwertungswerkzeuge: bestes waehlen, kaufen
    ItemActions  identifizieren, zerlegen, verkaufen (mit den Py4GWCoreLib-Routinen)
    WidgetCheck  benoetigte Py4GW-Widgets pruefen und einschalten, stoerende ausschalten
    Format       Zeit- und Goldangaben

Die Templates selbst gibt der jeweilige Bot vor und reicht sie als Parameter herein.
"""

import ctypes
import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from ctypes import c_uint8, c_uint32
from dataclasses import dataclass

import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import AutoPathing
from Py4GWCoreLib import Item
from Py4GWCoreLib import Map
from Py4GWCoreLib import Party
from Py4GWCoreLib import Player
from Py4GWCoreLib import Routines
from Py4GWCoreLib import SkillBar
from Py4GWCoreLib.Context import GWContext
from Py4GWCoreLib.enums_src.GameData_enums import Attribute, DyeColor, Profession, Range
from Py4GWCoreLib.enums_src.Hero_enums import HeroType
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_BAGS, INVENTORY_WITH_EQUIPMENT_BAGS
from Py4GWCoreLib.enums_src.Item_enums import ItemType, Rarity, SalvageMode
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.FrameTree import Frame, FrameId
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.routines_src.BehaviourTrees import BT as RoutinesBT
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import get_widget_handler


_DATA_DIR = os.path.dirname(__file__)


# --- Log -------------------------------------------------------------------------------------------

class Log:
    SOURCE = 'shared_data'  # Absender im Log; der Bot gibt seinen MODULE_NAME mit
    enabled = True

    @staticmethod
    def is_enabled() -> bool:
        return Log.enabled

    @staticmethod
    def set_enabled(enabled: bool) -> None:
        """Ein Schalter fuer alle Log-Ausgaben ueber Log.write (Bot und shared_data); Fehler erscheinen immer."""
        Log.enabled = bool(enabled)

    @staticmethod
    def write(message: str, message_type=PySystem.Console.MessageType.Info, source: str = SOURCE) -> None:
        """source = Absender im Log; Bots geben ihren MODULE_NAME mit. Error kommt auch bei ausgeschaltetem Log."""
        if Log.enabled or message_type == PySystem.Console.MessageType.Error:
            PySystem.Console.Log(source, message, message_type)


# --- Names -----------------------------------------------------------------------------------------

class Names:
    _PROFESSIONS_DE: dict[int, str] = {
        Profession.Warrior: 'Krieger',
        Profession.Ranger: 'Waldlaeufer',
        Profession.Monk: 'Moench',
        Profession.Necromancer: 'Nekromant',
        Profession.Mesmer: 'Mesmer',
        Profession.Elementalist: 'Elementarmagier',
        Profession.Assassin: 'Assassine',
        Profession.Ritualist: 'Ritualist',
        Profession.Paragon: 'Paragon',
        Profession.Dervish: 'Derwisch',
    }

    @staticmethod
    def readable(enum_name: str) -> str:
        """Enum-Namen lesbar machen: "MasterOfWhispers" -> "Master Of Whispers"."""
        return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', enum_name)

    @staticmethod
    def profession(value: int) -> str:
        if value == 0:
            return '-'
        return Names._PROFESSIONS_DE.get(value, f'unbekannt ({value})')

    @staticmethod
    def hero(hero_id: int) -> str:
        try:
            return Names.readable(HeroType(int(hero_id)).name)
        except ValueError:
            return f'unbekannt ({hero_id})'

    @staticmethod
    def attribute(attribute_id: int) -> str:
        try:
            return Names.readable(Attribute(attribute_id).name)
        except ValueError:
            return f'Attribut {attribute_id}'


# --- Heroes ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class HeroRow:
    hero_id: int
    name: str
    level: int
    primary_id: int
    primary: str
    secondary: str
    agent_id: int


class _HeroInfo(ctypes.Structure):
    # Eigenes Layout statt WorldContext.HeroInfoStruct: dessen 0x78-Groesse ist veraltet und
    # verschiebt jeden Eintrag nach dem ersten. 0x9C per Rohdump im Client verifiziert (2026-10-20).
    _pack_ = 1
    _fields_ = [
        ("hero_id", c_uint32),        # +h0000
        ("agent_id", c_uint32),       # +h0004
        ("level", c_uint32),          # +h0008
        ("primary", c_uint32),        # +h000C
        ("secondary", c_uint32),      # +h0010
        ("hero_file_id", c_uint32),   # +h0014
        ("model_file_id", c_uint32),  # +h0018
        ("h001C", c_uint8 * 128),     # +h001C unbekannt, Namensfeld nicht verifiziert
    ]


assert ctypes.sizeof(_HeroInfo) == 0x9C


class Heroes:
    _MAX_HEROES = 64  # Plausibilitaetsgrenze gegen kaputte Array-Header

    @staticmethod
    def _read_infos() -> list[_HeroInfo]:
        world = GWContext.World.GetContext()
        if world is None:
            raise RuntimeError('World-Context nicht verfuegbar (eingeloggt und Karte geladen?).')
        arr = world.hero_info_array
        if not arr.m_buffer or not arr.m_size:
            return []
        if arr.m_size > Heroes._MAX_HEROES or arr.m_size > arr.m_capacity:
            raise RuntimeError(f'Unplausibler Array-Header: size={arr.m_size} capacity={arr.m_capacity}')
        base = ctypes.cast(arr.m_buffer, ctypes.POINTER(_HeroInfo))
        return [base[i] for i in range(arr.m_size)]

    @staticmethod
    def read() -> list[HeroRow]:
        """Alle freigeschalteten Helden, nach Namen sortiert. Wirft RuntimeError ohne World-Context."""
        heroes = [
            HeroRow(
                hero_id=int(info.hero_id),
                name=Names.hero(int(info.hero_id)),
                level=int(info.level),
                primary_id=int(info.primary),
                primary=Names.profession(int(info.primary)),
                secondary=Names.profession(int(info.secondary)),
                agent_id=int(info.agent_id),
            )
            for info in Heroes._read_infos()
        ]
        heroes.sort(key=lambda row: row.name.casefold())
        return heroes


# --- Builds ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillBuild:
    primary: int
    secondary: int
    attributes: tuple[tuple[int, int], ...]
    skills: tuple[int, ...]


@dataclass(frozen=True)
class HeroBuild:
    role: str
    build: SkillBuild | None
    preferred_hero_id: int  # Default-Held des Bots; 0 = keiner


@dataclass(frozen=True)
class BuildAssignment:
    role: str
    build: SkillBuild | None
    hero: HeroRow | None
    missing_skills: tuple[int, ...]
    is_preferred: bool  # True = Default-Held, False = Ersatz oder kein Held


# Decodierte Builds, wie sie die Methoden unten erwarten; Spieler: (Primaerklasse, Build).
HeroBuilds = Sequence[HeroBuild]
PlayerBuilds = Sequence[tuple[int, SkillBuild | None]]


class Builds:
    _TEMPLATE_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

    @staticmethod
    def decode_template(template: str) -> SkillBuild:
        """Decodiert einen GW-Skill-Template-Code (Base64, Bits LSB-first)."""
        bits = ''.join(format(Builds._TEMPLATE_ALPHABET.index(char), '06b')[::-1] for char in template)
        pos = 0

        def take(count: int) -> int:
            nonlocal pos
            chunk = bits[pos:pos + count]
            if len(chunk) < count:
                raise ValueError('Template zu kurz')
            pos += count
            return int(chunk[::-1], 2)

        if take(4) == 14:  # Typ "Skill-Template"; danach folgt die Version. Aeltere Codes beginnen direkt mit der Version.
            take(4)
        profession_bits = take(2) * 2 + 4
        primary = take(profession_bits)
        secondary = take(profession_bits)
        attribute_count = take(4)
        attribute_bits = take(4) + 4
        attributes = tuple((take(attribute_bits), take(4)) for _ in range(attribute_count))
        skill_bits = take(4) + 8
        skills = tuple(take(skill_bits) for _ in range(8))
        return SkillBuild(primary, secondary, attributes, skills)

    @staticmethod
    def decode_or_none(template: str) -> SkillBuild | None:
        """Wie decode_template, aber None statt Exception bei ungueltigem Code."""
        try:
            return Builds.decode_template(template)
        except ValueError:
            return None

    @staticmethod
    def decode_hero_builds(templates: Iterable[tuple[int, str, str]]) -> list[HeroBuild]:
        """(Default-Held-ID, Rolle, Template) -> HeroBuild."""
        return [HeroBuild(role, Builds.decode_or_none(code), int(hero_id)) for hero_id, role, code in templates]

    @staticmethod
    def decode_player_builds(templates: Iterable[tuple[int, str]]) -> list[tuple[int, SkillBuild | None]]:
        return [(int(profession), Builds.decode_or_none(code)) for profession, code in templates]

    @staticmethod
    def required_primaries(hero_builds: HeroBuilds) -> dict[int, int]:
        """Benoetigte Helden je Primaerklasse (der Zweitberuf ist frei waehlbar)."""
        return dict(Counter(entry.build.primary for entry in hero_builds if entry.build is not None))

    @staticmethod
    def missing_primaries(required: dict[int, int], heroes: Iterable[HeroRow]) -> list[tuple[int, int, int]]:
        """(Klasse, benoetigt, vorhanden) fuer jede Primaerklasse mit zu wenigen freigeschalteten Helden."""
        available = Counter(row.primary_id for row in heroes)
        return [(prof, count, available[prof]) for prof, count in required.items() if available[prof] < count]

    @staticmethod
    def player_build_for(primary: int, player_builds: PlayerBuilds) -> SkillBuild | None:
        for profession, build in player_builds:
            if profession == primary:
                return build
        return None

    @staticmethod
    def assign(heroes: list[HeroRow], unlocked: dict[int, bool] | None, hero_builds: HeroBuilds) -> list[BuildAssignment]:
        """Ordnet jedem Helden-Build einen freigeschalteten Helden mit passender Primaerklasse zu.

        Default-Helden haben Vorrang und werden zuerst vergeben, damit kein Ersatz sie einem anderen
        Build wegnimmt. Freie Builds bekommen danach den passenden Helden mit der hoechsten Stufe.
        """
        by_id = {row.hero_id: row for row in heroes}
        chosen: dict[int, HeroRow] = {}
        for index, entry in enumerate(hero_builds):
            row = by_id.get(entry.preferred_hero_id)
            if entry.build is not None and row is not None and row.primary_id == entry.build.primary:
                chosen[index] = row
        preferred_indices = set(chosen)
        used = {row.hero_id for row in chosen.values()}
        for index, entry in enumerate(hero_builds):
            if index in chosen or entry.build is None:
                continue
            # Hoechste Stufe zuerst, bei Gleichstand alphabetisch; jeder Held nur einmal.
            candidates = sorted(
                (row for row in heroes if row.primary_id == entry.build.primary and row.hero_id not in used),
                key=lambda row: (-row.level, row.name.casefold()),
            )
            if candidates:
                chosen[index] = candidates[0]
                used.add(candidates[0].hero_id)

        result: list[BuildAssignment] = []
        for index, entry in enumerate(hero_builds):
            missing: tuple[int, ...] = ()
            if entry.build is not None and unlocked is not None:
                missing = tuple(s for s in entry.build.skills if s and not unlocked.get(s, False))
            result.append(BuildAssignment(entry.role, entry.build, chosen.get(index), missing, index in preferred_indices))
        return result


# --- SkillData -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillInfoDe:
    name: str  # leer, wenn unbekannt
    elite: bool
    profession: int  # Profession-ID, 0 = klassenlos/unbekannt
    attribute: str  # deutsch, z. B. "Mystik"; leer = kein Attribut/unbekannt
    sources: tuple[tuple[str, tuple[str, ...]], ...]


class SkillData:
    _NAMES_PATH = os.path.join(PySystem.Console.get_projects_path(), 'Py4GWCoreLib', 'skill_descriptions.json')
    # Gemeinsame Daten fuer mehrere Bots: shared_data/skills_de.json (Quelle: guildwiki.de).
    _SKILLS_DE_PATH = os.path.join(_DATA_DIR, 'skills_de.json')
    _UNKNOWN = SkillInfoDe('', False, 0, '', ())
    _names: dict[int, str] | None = None
    _skills_de: dict[int, SkillInfoDe] | None = None

    @staticmethod
    def name(skill_id: int) -> str:
        """Englischer Name aus Py4GWCoreLib/skill_descriptions.json."""
        if skill_id == 0:
            return '(leer)'
        if SkillData._names is None:
            try:
                with open(SkillData._NAMES_PATH, encoding='utf-8') as handle:
                    data = json.load(handle)
                SkillData._names = {int(key): str(entry['name']) for key, entry in data.items() if 'name' in entry}
            except (OSError, ValueError, AttributeError) as exc:
                Log.write(f'Skill-Namen nicht ladbar ({exc}); zeige IDs.', PySystem.Console.MessageType.Warning)
                SkillData._names = {}
        return SkillData._names.get(skill_id, f'Skill {skill_id}')

    @staticmethod
    def info_de(skill_id: int) -> SkillInfoDe:
        """Deutscher Name, Elite-Merkmal und Bezugsquellen; leerer Eintrag wenn unbekannt oder Datei fehlt."""
        if SkillData._skills_de is None:
            try:
                with open(SkillData._SKILLS_DE_PATH, encoding='utf-8') as handle:
                    data = json.load(handle)['skills']
                SkillData._skills_de = {
                    int(key): SkillInfoDe(
                        name=str(entry['de']),
                        elite=bool(entry.get('elite', False)),
                        profession=int(entry.get('profession', 0)),
                        attribute=str(entry.get('attribute', '')),
                        sources=tuple((str(cat), tuple(str(i) for i in items)) for cat, items in entry['sources']),
                    )
                    for key, entry in data.items()
                }
            except (OSError, ValueError, KeyError, TypeError) as exc:
                Log.write(f'Deutsche Skill-Daten nicht ladbar ({exc}).', PySystem.Console.MessageType.Warning)
                SkillData._skills_de = {}
        return SkillData._skills_de.get(skill_id, SkillData._UNKNOWN)

    @staticmethod
    def label(skill_id: int) -> str:
        """'Deutsch (Englisch)', oder nur Englisch, wenn kein deutscher Name bekannt ist."""
        name_de, name_en = SkillData.info_de(skill_id).name, SkillData.name(skill_id)
        return f'{name_de} ({name_en})' if name_de and name_de != name_en else name_en

    @staticmethod
    def _profession_order(profession: int) -> int:
        """Spielreihenfolge der Klassen (Krieger ... Derwisch), klassenlose zuletzt."""
        return profession or 99

    @staticmethod
    def sort_ids(skill_ids: Iterable[int]) -> list[int]:
        """Elite-Skills zuerst alphabetisch, danach normale nach Klasse und deutschem (sonst englischem) Namen."""
        def key(skill_id: int) -> tuple[bool, int, str]:
            info = SkillData.info_de(skill_id)
            name = info.name or SkillData.name(skill_id)
            return (not info.elite, 0 if info.elite else SkillData._profession_order(info.profession), name.casefold())
        return sorted(skill_ids, key=key)

    @staticmethod
    def count_by_profession(skill_ids: Iterable[int]) -> list[tuple[int, int, int]]:
        """(Klasse, Anzahl Elite, Anzahl normal) je Klasse mit mindestens einem Skill; Klasse 0 = klassenlos."""
        counts: dict[int, list[int]] = {}
        for skill_id in skill_ids:
            info = SkillData.info_de(skill_id)
            counts.setdefault(info.profession, [0, 0])[0 if info.elite else 1] += 1
        return [
            (prof, elite, normal)
            for prof, (elite, normal) in sorted(counts.items(), key=lambda item: SkillData._profession_order(item[0]))
        ]


# --- Trainers --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TrainerOffer:
    trainer: str
    location: str
    kind: str
    skill_ids: tuple[int, ...]


class Trainers:
    _KINDS = {'Fertigkeitstrainer': 'Trainer', 'Helden-Fertigkeitstrainer': 'Helden-Trainer'}
    # "Factions: Michiko (Zentrum von Kaineng)"; Freitext/Regionen ("alle", "Istan", ...) passen bewusst nicht.
    _ENTRY = re.compile(
        r'^(?:(?:Prophecies|Factions|Nightfall|Eye of the North|Cantha|Tyria|Elona|Basis): )?'
        r'([^():]+?) \(([^()]*(?:\([^()]*\))?[^()]*)\)$'
    )

    @staticmethod
    def location(category: str, item: str) -> tuple[str, str] | None:
        """(Trainer, Ort), wenn der Eintrag ein konkreter (Helden-)Fertigkeitstrainer ist, sonst None."""
        if category not in Trainers._KINDS:
            return None
        match = Trainers._ENTRY.match(item)
        return (match[1], match[2].strip()) if match else None

    @staticmethod
    def offers(skill_ids: Iterable[int]) -> list[TrainerOffer]:
        """Nicht-Elite-Skills gruppiert nach Trainer, meiste Skills zuerst."""
        groups: dict[tuple[str, str, str], set[int]] = {}
        for skill_id in skill_ids:
            info = SkillData.info_de(skill_id)
            if info.elite:
                continue
            for category, items in info.sources:
                kind = Trainers._KINDS.get(category)
                if kind is None:
                    continue
                for item in items:
                    match = Trainers._ENTRY.match(item)
                    if match:
                        groups.setdefault((match[1], match[2], kind), set()).add(skill_id)
        offers = [TrainerOffer(t, loc, kind, tuple(sorted(ids))) for (t, loc, kind), ids in groups.items()]
        offers.sort(key=lambda offer: (-len(offer.skill_ids), offer.location.casefold(), offer.trainer.casefold()))
        return offers


# --- Skills (Laufzeit) -----------------------------------------------------------------------------

class Skills:
    @staticmethod
    def _query(builds: list[SkillBuild | None], query: Callable[[int], bool], label: str) -> dict[int, bool] | None:
        skill_ids = {s for build in builds if build for s in build.skills if s}
        try:
            return {skill_id: bool(query(skill_id)) for skill_id in skill_ids}
        except Exception as exc:
            Log.write(f'{label} nicht abfragbar: {exc}', PySystem.Console.MessageType.Warning)
            return None

    @staticmethod
    def hero_unlocks(hero_builds: HeroBuilds) -> dict[int, bool] | None:
        """Helden nutzen Account-Freischaltungen (IsSkillUnlocked)."""
        return Skills._query([entry.build for entry in hero_builds], SkillBar.IsSkillUnlocked, 'Skill-Freischaltungen')

    @staticmethod
    def player_learnt(player_builds: PlayerBuilds) -> dict[int, bool] | None:
        """Der Spieler nutzt nur selbst gelernte Skills (IsSkillLearnt)."""
        return Skills._query([build for _prof, build in player_builds], SkillBar.IsSkillLearnt, 'Gelernte Skills')

    @staticmethod
    def player_primary() -> int:
        """Primaerklasse des eigenen Charakters, 0 wenn nicht lesbar."""
        try:
            return int(Agent.GetProfessionIDs(Player.GetAgentID())[0])
        except Exception:
            return 0


# --- Icons -----------------------------------------------------------------------------------------

class Icons:
    _TEXTURES_DIR = os.path.join(PySystem.Console.get_projects_path(), 'Assets', 'Textures')
    _SKILL_ICON_DIR = os.path.join(_TEXTURES_DIR, 'Skill_Icons')
    # Elite-Symbol: Skill-Icon "Siegel der Erbeutung".
    _ELITE_ICON_PATH = os.path.join(_SKILL_ICON_DIR, '[3] - Signet of Capture.jpg')
    _ITEM_ICON_DIR = os.path.join(_TEXTURES_DIR, 'Item Models')
    _DYE_ICON_DIR = os.path.join(_TEXTURES_DIR, 'Dyes')
    _skill_paths: dict[int, str] | None = None
    _item_paths: dict[int, str] | None = None
    _profession_paths: dict[int, str] | None = None

    @staticmethod
    def skill(skill_id: int) -> str | None:
        """Skill-Icon nach Skill-ID ("[3] - Signet of Capture.jpg" -> 3); None, wenn keins vorhanden."""
        if Icons._skill_paths is None:
            try:
                files = os.listdir(Icons._SKILL_ICON_DIR)
            except OSError:
                files = []
            Icons._skill_paths = {
                int(match[1]): os.path.join(Icons._SKILL_ICON_DIR, name)
                for name in files
                if (match := re.match(r'^\[(\d+)\] - ', name))
            }
        return Icons._skill_paths.get(skill_id)

    @staticmethod
    def profession(profession: int) -> str | None:
        """Klassen-Icon (Schema wie Agent.py: Profession_Icons/[1] - Warrior.png); None fuer 0 oder fehlende Datei."""
        if Icons._profession_paths is None:
            Icons._profession_paths = {
                int(prof): path
                for prof in Profession
                if int(prof) and os.path.exists(
                    path := os.path.join(Icons._TEXTURES_DIR, 'Profession_Icons', f'[{int(prof)}] - {prof.name}.png')
                )
            }
        return Icons._profession_paths.get(profession)

    @staticmethod
    def item(model_id: int) -> str | None:
        """Item-Bild nach Model-ID ("00146-Vial_Of_dye.png" -> 146); bei mehreren Dateien die erste nach Name."""
        if Icons._item_paths is None:
            try:
                files = sorted(os.listdir(Icons._ITEM_ICON_DIR))
            except OSError:
                files = []
            paths: dict[int, str] = {}
            for name in files:
                if match := re.match(r'^(\d+)-', name):
                    paths.setdefault(int(match[1]), os.path.join(Icons._ITEM_ICON_DIR, name))
            Icons._item_paths = paths
        return Icons._item_paths.get(model_id)

    @staticmethod
    def dye(color: int) -> str | None:
        """Farbstoff-Bild nach Farbe (DyeColor, z. B. 10 -> Dyes/Black.png); None, wenn keins vorhanden."""
        try:
            path = os.path.join(Icons._DYE_ICON_DIR, f'{DyeColor(color).name}.png')
        except ValueError:
            return None
        return path if os.path.exists(path) else None

    @staticmethod
    def elite() -> str | None:
        """Elite-Symbol; None, wenn die Datei fehlt."""
        return Icons._ELITE_ICON_PATH if os.path.exists(Icons._ELITE_ICON_PATH) else None


# --- Maps ------------------------------------------------------------------------------------------

class Maps:
    """Map-IDs nach BotsHub-Namen ohne $ID_, z. B. Maps.id('KAINENG_CENTER_DEFAULT') -> 194."""

    _PATH = os.path.join(_DATA_DIR, 'maps.json')
    _ids: dict[str, int] | None = None

    @staticmethod
    def id(name: str) -> int:
        """Wirft KeyError mit Hinweis, wenn der Name fehlt (Tippfehler sollen sofort auffallen, nicht als Map 0)."""
        if Maps._ids is None:
            try:
                with open(Maps._PATH, encoding='utf-8') as handle:
                    Maps._ids = {str(key): int(value) for key, value in json.load(handle)['maps'].items()}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                Log.write(f'Map-IDs nicht ladbar ({exc}).', PySystem.Console.MessageType.Error)
                Maps._ids = {}
        try:
            return Maps._ids[name]
        except KeyError:
            raise KeyError(f'Map {name!r} nicht in {os.path.basename(Maps._PATH)}') from None


# --- Locations -------------------------------------------------------------------------------------

class Locations:
    """Trainer-Orte (deutsch) -> Py4GW-Aussenposten-ID aus locations_de.json, und Freischaltstatus."""

    _PATH = os.path.join(_DATA_DIR, 'locations_de.json')
    _map_ids: dict[str, int | None] | None = None

    @staticmethod
    def travel_map_id(location_de: str) -> int | None:
        """Aussenposten-ID zum deutschen Ortsnamen; None, wenn unbekannt, mehrdeutig oder kein Aussenposten."""
        if Locations._map_ids is None:
            try:
                with open(Locations._PATH, encoding='utf-8') as handle:
                    data = json.load(handle)['locations']
                Locations._map_ids = {
                    name.strip().casefold(): (int(entry['map_id']) if entry['map_id'] is not None else None)
                    for name, entry in data.items()
                }
            except (OSError, ValueError, KeyError, TypeError) as exc:
                Log.write(f'Ortsdaten nicht ladbar ({exc}).', PySystem.Console.MessageType.Warning)
                Locations._map_ids = {}
        return Locations._map_ids.get(location_de.strip().casefold())

    @staticmethod
    def is_map_unlocked(map_id: int) -> bool | None:
        """True, wenn der eingeloggte Charakter den Aussenposten freigeschaltet hat; None, wenn nicht abfragbar."""
        try:
            return bool(Map.IsMapUnlocked(map_id))
        except Exception as exc:
            Log.write(f'Freischaltung von Map {map_id} nicht abfragbar ({exc}).', PySystem.Console.MessageType.Warning)
            return None

    @staticmethod
    def unlocked(location_de: str) -> bool | None:
        """Freischaltstatus per deutschem Ortsnamen; None, wenn Ort ohne eindeutige ID oder nicht abfragbar."""
        map_id = Locations.travel_map_id(location_de)
        return Locations.is_map_unlocked(map_id) if map_id is not None else None


# --- Overview --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Overview:
    """Gesamtauswertung fuer die Pruefung bei START: Helden, Freischaltungen, Zuordnung und fehlende Skills."""

    status: str
    error: str = ''  # Grund, falls die Heldenliste nicht gelesen werden konnte; leer = kein Lesefehler
    heroes: tuple[HeroRow, ...] = ()
    assignments: tuple[BuildAssignment, ...] = ()
    unlocked_skills: dict[int, bool] | None = None  # None = noch nicht/nicht abfragbar
    learnt_skills: dict[int, bool] | None = None
    player_missing_skills: tuple[int, ...] = ()
    player_primary: int = 0  # Primaerklasse des Spielers beim Einlesen; 0 = nicht lesbar (z. B. Ladebildschirm)

    def missing_skills(self) -> set[int]:
        """Fehlende Skills von Helden-Builds und Spieler-Build, ohne Doppelte."""
        missing = {skill_id for entry in self.assignments for skill_id in entry.missing_skills}
        missing.update(self.player_missing_skills)
        return missing

    @staticmethod
    def _player_missing_skills(primary: int, learnt: dict[int, bool] | None,
                               player_builds: PlayerBuilds) -> tuple[int, ...]:
        """Nicht gelernte Skills des Spieler-Builds zur Primaerklasse primary."""
        build = Builds.player_build_for(primary, player_builds)
        if build is None or learnt is None:
            return ()
        return tuple(s for s in build.skills if s and not learnt.get(s, False))

    @staticmethod
    def read(hero_builds: HeroBuilds, player_builds: PlayerBuilds) -> 'Overview':
        """Liest alles neu ein; bei Fehlern ein Overview ohne Helden mit Fehlermeldung als Status.

        hero_builds/player_builds sind die vom Bot vorgegebenen, decodierten Templates.
        """
        try:
            heroes = Heroes.read()
        except Exception as exc:
            status = f'Lesen fehlgeschlagen: {exc}'
            Log.write(status, PySystem.Console.MessageType.Error)
            return Overview(status=status, error=f'Heldenliste: {exc}')

        unlocked = Skills.hero_unlocks(hero_builds)
        learnt = Skills.player_learnt(player_builds)
        primary = Skills.player_primary()
        overview = Overview(
            status=f'{len(heroes)} Held(en) gelesen.',
            heroes=tuple(heroes),
            assignments=tuple(Builds.assign(heroes, unlocked, hero_builds)),
            unlocked_skills=unlocked,
            learnt_skills=learnt,
            player_missing_skills=Overview._player_missing_skills(primary, learnt, player_builds),
            player_primary=primary,
        )
        Log.write(overview.status, PySystem.Console.MessageType.Success)
        for row in heroes:
            Log.write(
                f'{row.hero_id:>3} {row.name:<22} Stufe {row.level:>2}  '
                f'{row.primary}/{row.secondary}  agent={row.agent_id}'
            )
        return overview


EMPTY_OVERVIEW = Overview(status='START prueft Helden und Skills und startet, wenn alles da ist.')


# --- PartyHeroes -----------------------------------------------------------------------------------

class PartyHeroes:
    """Helden in der aktuellen Gruppe, angesprochen ueber die Partyposition (1 = erster eingeladener Held)."""

    @staticmethod
    def agent(position: int) -> int:
        return int(Party.Heroes.GetHeroAgentIDByPartyPosition(position) or 0)

    @staticmethod
    def label(position: int) -> str:
        """Name des Helden, der gerade auf der Partyposition steht; 'Held n', wenn keiner da ist."""
        agent_id = PartyHeroes.agent(position)
        hero_id = int(Party.Heroes.GetHeroIDByAgentID(agent_id) or 0) if agent_id else 0
        return Names.hero(hero_id) if hero_id else f'Held {position}'

    @staticmethod
    def skill_ready(position: int, slot: int) -> bool:
        try:
            skillbar = GLOBAL_CACHE.SkillBar.GetHeroSkillbar(position)
            if slot < 1 or slot > len(skillbar):
                return False
            data = skillbar[slot - 1]
            skill_id = int(getattr(getattr(data, 'id', None), 'id', 0) or 0)
            recharge = getattr(data, 'get_recharge', 0)
            if callable(recharge):
                recharge = recharge()
            try:
                recharge = float(recharge) if isinstance(recharge, (int, float, str)) else 0.0
            except (TypeError, ValueError):
                recharge = 0.0
            return bool(skill_id and recharge <= 0.0)
        except Exception:
            return False

    @staticmethod
    def skill_id(position: int, slot: int) -> int:
        try:
            skillbar = GLOBAL_CACHE.SkillBar.GetHeroSkillbar(position)
            if slot < 1 or slot > len(skillbar):
                return 0
            return int(getattr(getattr(skillbar[slot - 1], 'id', None), 'id', 0) or 0)
        except Exception:
            return 0


# --- PlayerState -----------------------------------------------------------------------------------

class PlayerState:
    @staticmethod
    def energy() -> float:
        player_id = int(Player.GetAgentID() or 0)
        return float(Agent.GetEnergy(player_id) or 0.0) * float(Agent.GetMaxEnergy(player_id) or 0)

    @staticmethod
    def skill_ready(slot: int) -> bool:
        try:
            data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
            return bool(data is not None and int(getattr(data, 'recharge', 0) or 0) == 0)
        except Exception:
            return False

    @staticmethod
    def skill_adrenaline(slot: int) -> int:
        try:
            data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
            return int(getattr(data, 'adrenaline_a', 0) or 0) if data is not None else 0
        except Exception:
            return 0

    @staticmethod
    def has_effect_for_slot(slot: int) -> bool:
        """True, wenn der Skill im Slot gerade als Effekt auf dem Spieler liegt."""
        try:
            skill_id = int(GLOBAL_CACHE.SkillBar.GetSkillIDBySlot(slot) or 0)
            return bool(skill_id and GLOBAL_CACHE.Effects.HasEffect(Player.GetAgentID(), skill_id))
        except Exception:
            return False


# --- Enemies ---------------------------------------------------------------------------------------

class Enemies:
    @staticmethod
    def with_dist2(position: tuple[float, float]) -> list[tuple[int, float]]:
        """(Agent, Abstand zum Quadrat) aller lebenden Gegner."""
        px, py = position
        result: list[tuple[int, float]] = []
        for agent_id in AgentArray.GetEnemyArray():
            if not Agent.IsLiving(agent_id) or Agent.IsDead(agent_id):
                continue
            x, y = Agent.GetXY(agent_id)
            result.append((agent_id, (x - px) ** 2 + (y - py) ** 2))
        return result

    @staticmethod
    def near(position: tuple[float, float], radius: float) -> list[int]:
        return [agent_id for agent_id, d2 in Enemies.with_dist2(position) if d2 <= radius * radius]

    @staticmethod
    def nearest(position: tuple[float, float], radius: float | None = None) -> int:
        """Naechster lebender Gegner (optional nur im Radius); 0, wenn keiner."""
        enemies = Enemies.with_dist2(position)
        if radius is not None:
            enemies = [entry for entry in enemies if entry[1] <= radius * radius]
        return min(enemies, key=lambda entry: entry[1])[0] if enemies else 0


# --- Items am Boden -------------------------------------------------------------------------------

@dataclass(frozen=True)
class GroundItem:
    agent_id: int
    item_id: int
    model_id: int
    dye_color: int
    item_type: int
    rarity: int
    dist2: float
    model_file_id: int  # Datei im Gw.dat (Item-Bild); 0, wenn das Spiel keine liefert


class GroundItems:
    @staticmethod
    def mine(position: tuple[float, float], radius: float) -> list[GroundItem]:
        """Items im Radius, die der Spieler aufheben darf (Besitzer 0 oder er, wie LootFilters); naechste zuerst."""
        return GroundItems._collect(position, radius, own_only=True)

    @staticmethod
    def around(position: tuple[float, float], radius: float) -> list[GroundItem]:
        """Alle Items im Radius, egal wem sie gehoeren; naechste zuerst."""
        return GroundItems._collect(position, radius, own_only=False)

    @staticmethod
    def _collect(position: tuple[float, float], radius: float, own_only: bool) -> list[GroundItem]:
        px, py = position
        me = int(Player.GetAgentID() or 0)
        result: list[GroundItem] = []
        for agent_id in AgentArray.GetItemArray():
            if own_only and Agent.GetItemAgentOwnerID(agent_id) not in (0, me):
                continue
            x, y = Agent.GetXY(agent_id)
            dist2 = (x - px) ** 2 + (y - py) ** 2
            item_id = Agent.GetItemAgentItemID(agent_id)
            if dist2 > radius * radius or not item_id:
                continue
            result.append(GroundItem(
                agent_id, item_id, int(Item.GetModelID(item_id)), int(Item.GetDyeColor(item_id)),
                int(Item.GetItemType(item_id)[0]), int(Item.Rarity.GetRarity(item_id)[0]), dist2,
                int(Item.GetModelFileID(item_id) or 0),
            ))
        return sorted(result, key=lambda item: item.dist2)

    @staticmethod
    def request_name(item_id: int) -> None:
        """Namen beim Spiel anfragen; er ist erst einige Frames spaeter lesbar (details)."""
        Item.RequestName(item_id)

    @staticmethod
    def details(item_id: int) -> dict[str, str | int | bool | list[int]]:
        """Weitere Daten eines Items; Name nur, wenn das Spiel ihn schon geliefert hat (sonst leer)."""
        instance = Item.item_instance(item_id)
        name = str(Item.GetName(item_id) or '') if Item.IsNameReady(item_id) else ''
        return {
            'name': name,
            'name_enc': [int(c) for c in instance.GetNameEnc() or ()],
            'item_type_name': str(Item.GetItemType(item_id)[1]),
            'rarity_name': str(Item.Rarity.GetRarity(item_id)[1]),
            'model_file_id': int(Item.GetModelFileID(item_id) or 0),
            'value': int(Item.Properties.GetValue(item_id) or 0),
            'quantity': int(Item.Properties.GetQuantity(item_id) or 0),
            'profession': int(Item.Properties.GetProfession(item_id) or 0),
            'stackable': bool(Item.Properties.IsStackable(item_id)),
        }


# --- Survivor --------------------------------------------------------------------------------------

class Survivor:
    """min HP in Prozent (0 = aus), gespeichert ueber die Settings des Bots.

    Survivor sagt nur, ob die Grenze unterschritten ist; was dann passiert (Neustart, Abbruch), entscheidet
    der Bot. Das Spiel liefert die HP als Anteil 0..1 (0,5 = halbe HP), der Wert hier ist in Prozent.
    """

    def __init__(self, settings: Settings, section: str, key: str = 'min_hp_percent') -> None:
        self._settings = settings
        self._section = section
        self._key = key
        self.percent = min(100, max(0, settings.get_int(section, key, 0)))

    @property
    def enabled(self) -> bool:
        return self.percent > 0

    def set_percent(self, percent: int) -> None:
        """Auf 0..100 begrenzen; nur bei Aenderung speichern."""
        value = min(100, max(0, int(percent)))
        if value != self.percent:
            self.percent = value
            self._settings.set_int(self._section, self._key, value)

    def check(self, active: bool = True) -> float | None:
        """HP-Anteil (0..1), wenn er unter min HP liegt; sonst None.

        Fragt nichts ab bei 0 %, wenn der Bot active=False sagt, bei Ladebildschirm/Reise (Map nicht bereit
        oder keine Explorable) und ohne Spieler-Agent. HP 0 = tot zaehlt nicht; das ist Sache des Tod-Checks.
        """
        if not active or not self.enabled:
            return None
        if not Map.IsMapReady() or not Map.IsExplorable():
            return None
        agent_id = int(Player.GetAgentID() or 0)
        if not agent_id:
            return None
        health = float(Agent.GetHealth(agent_id))
        if health <= 0.0 or health >= self.percent / 100.0:
            return None
        return health

    def describe(self, health: float) -> str:
        return f'HP {health * 100:.0f} % unter min HP {self.percent} %'


# --- Inventory -------------------------------------------------------------------------------------

LogFn = Callable[[str], None]  # Log-Funktion des Bots (z. B. mit Prefix "Mission: ")
LabelFn = Callable[[int], str]  # Item-ID -> Beschriftung fuers Log (z. B. shared_data.items.item_label)


class Inventory:
    """Taschen und Plaetze des Spielers. Bags: Werte aus Py4GWCoreLib Bags (1 Backpack ... 5 Equipment Pack)."""

    @staticmethod
    def item_ids(bags: Iterable[int]) -> set[int]:
        bag_list = GLOBAL_CACHE.ItemArray.CreateBagList(*(int(bag) for bag in bags))
        return {int(item_id) for item_id in GLOBAL_CACHE.ItemArray.GetItemArray(bag_list)}

    @staticmethod
    def slots(bags: Iterable[int] = INVENTORY_WITH_EQUIPMENT_BAGS) -> dict[tuple[int, int], int]:
        """(Tasche, Platz) -> Item-ID."""
        slots: dict[tuple[int, int], int] = {}
        for bag in bags:
            for item_id in Inventory.item_ids([bag]):
                slots[(int(bag), int(GLOBAL_CACHE.Item.GetSlot(item_id)))] = item_id
        return slots

    @staticmethod
    def bag_present(bag: int) -> bool:
        """Groesse > 0; ohne geladene Map melden alle Taschen 0."""
        return int(GLOBAL_CACHE.Inventory.GetBagSize(int(bag))) > 0

    @staticmethod
    def free_slots(bags: Iterable[int]) -> int:
        return sum(int(GLOBAL_CACHE.Inventory.GetBagSize(int(bag))) - len(Inventory.item_ids([bag])) for bag in bags)

    @staticmethod
    def gold() -> int:
        return int(GLOBAL_CACHE.Inventory.GetGoldOnCharacter())


class PickedItems:
    """Vom Bot aufgehobene Items, je mit einem Schluessel des Bots (z. B. fuer DropLog).

    Gemerkt nach (Tasche, Platz) und Model, nicht nach Item-ID: das Spiel vergibt die IDs nach einem Kartenwechsel
    neu, Tasche und Platz bleiben. Nur im Speicher.
    """

    def __init__(self) -> None:
        self.slots: dict[tuple[int, int], tuple[int, str]] = {}  # (Tasche, Platz) -> (Model-ID, Schluessel)

    def remember(self, picked: Mapping[int, str]) -> None:
        """Direkt nach dem Aufheben (gleiche Karte, IDs gueltig): Item-ID -> Schluessel. Was sich auf einen vorhandenen
        Stapel gelegt hat, hat keine eigene ID mehr im Inventar und wird nicht gemerkt."""
        positions = {item_id: slot for slot, item_id in Inventory.slots().items()}
        for item_id, key in picked.items():
            if item_id in positions:
                self.slots[positions[item_id]] = (int(GLOBAL_CACHE.Item.GetModelID(item_id)), key)

    def current(self) -> dict[int, str]:
        """Aktuelle Item-ID -> Schluessel. Plaetze, auf denen nicht mehr dasselbe Model liegt (verkauft, zerlegt,
        verschoben), fallen heraus."""
        current = Inventory.slots()
        picked: dict[int, str] = {}
        for slot, (model_id, key) in list(self.slots.items()):
            item_id = current.get(slot, 0)
            if item_id and int(GLOBAL_CACHE.Item.GetModelID(item_id)) == model_id:
                picked[item_id] = key
            else:
                del self.slots[slot]
        return picked


# --- Traders ---------------------------------------------------------------------------------------

class Traders:
    """Haendler am Titel in Klammern erkennen ("Ryukichi [Kaufmann]"); Namen kommen in der Client-Sprache.

    Deutsche Titel aus Kaineng (Log 2026-10-29): [Kaufmann]/[Kauffrau], [Materialien], [Seltene Materialien],
    [Material], [Farbstoffe], [Runen], [Waffenhaendler], [Bonus-Haendler]; englisch [Merchant], [... Trader].
    """
    _RX_TITLE = re.compile(r'\[([^\]]+)\]\s*$')
    MERCHANT_TITLES = frozenset({'kaufmann', 'kauffrau', 'merchant'})
    _TRADER_WORDS = (*MERCHANT_TITLES, 'h\u00e4ndler', 'haendler', 'material', 'farbstoff', 'rune', 'trader')

    @staticmethod
    def title(name: str) -> str:
        """Titel in Klammern am Ende des Namens, klein geschrieben; sonst ''."""
        match = Traders._RX_TITLE.search(name)
        return match.group(1).strip().casefold() if match else ''

    @staticmethod
    def is_merchant(name: str) -> bool:
        return Traders.title(name) in Traders.MERCHANT_TITLES

    @staticmethod
    def find(name_wait_s: float = 3.0) -> Generator[None, None, list[tuple[int, str]]]:
        """(Agent, Name) aller Haendler in Reichweite. Namen dekodiert das Spiel im Hintergrund: so lange erneut
        abfragen, bis alle da sind, hoechstens name_wait_s."""
        deadline = time.monotonic() + name_wait_s
        while True:
            names = {int(agent_id): Agent.GetNameByID(int(agent_id)) for agent_id in AgentArray.GetNPCMinipetArray()}
            if all(names.values()) or time.monotonic() >= deadline:
                break
            yield
        return [(agent_id, name) for agent_id, name in names.items()
                if any(word in Traders.title(name) for word in Traders._TRADER_WORDS)]

    @staticmethod
    def walk_distance(x: float, y: float) -> Generator[None, None, float]:
        """Laenge des Laufwegs vom Spieler zu (x, y) ueber AutoPathing; ohne Weg die Luftlinie."""
        px, py = Player.GetXY()
        path = list((yield from AutoPathing().get_path_to(x, y, margin=250)) or [])
        if not path:
            return math.hypot(px - x, py - y)
        points = [(px, py), *((float(p[0]), float(p[1])) for p in path)]
        return sum(math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(points, points[1:]))

    @staticmethod
    def window_open() -> bool:
        return Frame(FrameId.Merchant).exists

    @staticmethod
    def open_window(agent_id: int, timeout_s: float = 3.0, tries: int = 2) -> Generator[None, None, int]:
        """Haendler ansprechen (Ziel, 250 ms, Interact) und warten, bis das Haendlerfenster offen ist. Gibt den
        erfolgreichen Versuch zurueck (1, 2, ...), 0 = nicht geoeffnet."""
        for attempt in range(1, tries + 1):
            Player.ChangeTarget(agent_id)
            wait_until = time.monotonic() + 0.25
            while time.monotonic() < wait_until:
                yield
            Player.Interact(agent_id, False)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if Traders.window_open():
                    return attempt
                yield
        return 0


# --- Kits ------------------------------------------------------------------------------------------

class Kits:
    """Identifizierungs- und Wiederverwertungswerkzeuge in den Taschen 1-4 (wie Py4GWCoreLib), bestes zuerst."""
    ID_MODELS = (int(ModelID.Superior_Identification_Kit), int(ModelID.Identification_Kit))
    EXPERT_SALVAGE_MODELS = (int(ModelID.Superior_Salvage_Kit), int(ModelID.Expert_Salvage_Kit))
    LESSER_SALVAGE_MODELS = (int(ModelID.Salvage_Kit), int(ModelID.Salvage_Kit_preSearing))
    # Kaufen wie Py4GWCoreLib BuyIDKits/BuySalvageKits.
    BUY_ID_MODEL = int(ModelID.Superior_Identification_Kit)
    BUY_SALVAGE_MODEL = int(ModelID.Salvage_Kit)
    BUY_CONFIRM_TIMEOUT_S = 5.0

    @staticmethod
    def ids(is_kit: Callable[[int], bool]) -> list[int]:
        """Werkzeuge, die is_kit erfuellen und noch Nutzungen haben."""
        return [item_id for item_id in Inventory.item_ids(INVENTORY_BAGS)
                if is_kit(item_id) and int(GLOBAL_CACHE.Item.Usage.GetUses(item_id)) > 0]

    @staticmethod
    def best(kit_ids: list[int], preferred_models: tuple[int, ...]) -> int:
        """Zuerst nach preferred_models (Reihenfolge = Rang), dann das mit den wenigsten Nutzungen, damit angebrochene
        zuerst leer werden. 0 = keins."""
        def rank(item_id: int) -> tuple[int, int]:
            model_id = int(GLOBAL_CACHE.Item.GetModelID(item_id))
            place = preferred_models.index(model_id) if model_id in preferred_models else len(preferred_models)
            return place, int(GLOBAL_CACHE.Item.Usage.GetUses(item_id))
        return min(kit_ids, key=rank) if kit_ids else 0

    @staticmethod
    def best_id() -> int:
        return Kits.best(Kits.ids(GLOBAL_CACHE.Item.Usage.IsIDKit), Kits.ID_MODELS)

    @staticmethod
    def best_salvage(rare: bool) -> tuple[int, SalvageMode]:
        """(Werkzeug, Modus). rare (Lila/Gold): Experten-/Superior-Werkzeug fuer seltene Materialien, sonst einfaches.
        Sonst einfaches, ohne einfaches ein Experten-Werkzeug. Perfekt nutzt der BT-Knoten nur fuer Upgrades. Erkannt
        an der Model-ID wie im BT-Knoten SalvageItem, damit er das gewaehlte Werkzeug auch annimmt."""
        def model_in(models: tuple[int, ...]) -> Callable[[int], bool]:
            return lambda item_id: int(GLOBAL_CACHE.Item.GetModelID(item_id)) in models
        experts = Kits.ids(model_in(Kits.EXPERT_SALVAGE_MODELS))
        lessers = Kits.ids(model_in(Kits.LESSER_SALVAGE_MODELS))
        if rare and experts:
            return Kits.best(experts, Kits.EXPERT_SALVAGE_MODELS), SalvageMode.RareCraftingMaterials
        if lessers:
            return Kits.best(lessers, ()), SalvageMode.LesserCraftingMaterials
        if experts:
            return Kits.best(experts, Kits.EXPERT_SALVAGE_MODELS), SalvageMode.LesserCraftingMaterials
        return 0, SalvageMode.LesserCraftingMaterials

    @staticmethod
    def id_kits() -> list[tuple[int, str]]:
        """(Item-ID, Art) aller Identifizierungswerkzeuge; Art leer."""
        return [(item_id, '') for item_id in Inventory.item_ids(INVENTORY_BAGS)
                if GLOBAL_CACHE.Item.Usage.IsIDKit(item_id)]

    @staticmethod
    def salvage_kits() -> list[tuple[int, str]]:
        """(Item-ID, Art) aller Wiederverwertungswerkzeuge; Art Perfekt/Experte/Einfach."""
        usage = GLOBAL_CACHE.Item.Usage
        kits: list[tuple[int, str]] = []
        for item_id in Inventory.item_ids(INVENTORY_BAGS):
            if not usage.IsSalvageKit(item_id):
                continue
            if usage.IsPerfectSalvageKit(item_id):
                kits.append((item_id, 'Perfekt'))
            elif usage.IsExpertSalvageKit(item_id):
                kits.append((item_id, 'Experte'))
            else:
                kits.append((item_id, 'Einfach'))
        return kits

    @staticmethod
    def buy(model_id: int, label: str, has_kit: Callable[[], bool], log: LogFn) -> Generator[None, None, bool]:
        """Ein Werkzeug beim offenen Haendler kaufen, wenn er es anbietet und das Gold reicht (Preis wie
        Py4GWCoreLib: Haendlerwert x 2); wartet, bis has_kit() wahr ist."""
        offered = [int(item_id) for item_id in GLOBAL_CACHE.Trading.Merchant.GetOfferedItems()
                   if int(GLOBAL_CACHE.Item.GetModelID(item_id)) == model_id]
        if not offered:
            log(f'Kaufen: Kaufmann bietet kein {label} an.')
            return False
        price = int(GLOBAL_CACHE.Item.Properties.GetValue(offered[0]) or 0) * 2
        gold = Inventory.gold()
        if price <= 0 or gold < price:
            log(f'Kaufen: {label} kostet {price}, Gold {gold}: reicht nicht.')
            return False
        log(f'Kaufe {label} fuer {price} Gold (Gold {gold}).')
        GLOBAL_CACHE.Trading.Merchant.BuyItem(offered[0], price)
        deadline = time.monotonic() + Kits.BUY_CONFIRM_TIMEOUT_S
        while not has_kit():
            if time.monotonic() >= deadline:
                log(f'Kaufen: {label} nach {Kits.BUY_CONFIRM_TIMEOUT_S:.0f} s nicht im Inventar.')
                return False
            yield
        return True


# --- ItemActions -----------------------------------------------------------------------------------

class ItemActions:
    """Identifizieren, Zerlegen, Verkaufen von Items im Inventar; fehlende Werkzeuge kaufen (Haendlerfenster offen)."""
    ACTION_TIMEOUT_S = 3.0  # je Item fuer Identifizieren; Zerlegen das Dreifache (Dialoge)
    SELL_CONFIRM_TIMEOUT_S = 5.0

    @staticmethod
    def sellable(item_id: int) -> bool:
        """Gold und gruene Items (Rarity Green) sind unverkaeuflich."""
        if GLOBAL_CACHE.Item.GetItemType(item_id)[0] == int(ItemType.Gold_Coin):
            return False
        return GLOBAL_CACHE.Item.Rarity.GetRarity(item_id)[0] != int(Rarity.Green)

    @staticmethod
    def identify(item_ids: list[int], log: LogFn, label: LabelFn) -> Generator[None, None, None]:
        """Wie Py4GWCoreLib IdentifyItemsAndVerify, aber mit dem besten Werkzeug (Superior zuerst); ohne Werkzeug eins
        kaufen, wenn das Gold reicht."""
        usage = GLOBAL_CACHE.Item.Usage
        for item_id in item_ids:
            if usage.IsIdentified(item_id):
                continue
            kit_id = Kits.best_id()
            if not kit_id:
                if not (yield from Kits.buy(Kits.BUY_ID_MODEL, 'Identifizierungswerkzeug',
                                            lambda: bool(Kits.best_id()), log)):
                    log('Identifizieren abgebrochen: kein Werkzeug.')
                    return
                kit_id = Kits.best_id()
            GLOBAL_CACHE.Inventory.IdentifyItem(item_id, kit_id)
            deadline = time.monotonic() + ItemActions.ACTION_TIMEOUT_S
            while not usage.IsIdentified(item_id) and time.monotonic() < deadline:
                yield
            if not usage.IsIdentified(item_id):
                log(f'    nicht identifiziert nach {ItemActions.ACTION_TIMEOUT_S:.0f} s: {label(item_id)}')

    @staticmethod
    def salvage(item_ids: list[int], log: LogFn, label: LabelFn) -> Generator[None, None, list[int]]:
        """Je Item der Salvage-Knoten von Py4GWCoreLib (bedient auch die Dialoge) mit dem besten Werkzeug; ohne
        Werkzeug ein einfaches kaufen, wenn das Gold reicht. Gibt die zerlegten Item-IDs zurueck."""
        salvaged: list[int] = []
        for item_id in item_ids:
            if item_id not in Inventory.item_ids(INVENTORY_WITH_EQUIPMENT_BAGS):
                continue
            rare = int(GLOBAL_CACHE.Item.Rarity.GetRarity(item_id)[0]) in (int(Rarity.Purple), int(Rarity.Gold))
            kit_id, mode = Kits.best_salvage(rare)
            if not kit_id:
                bought = yield from Kits.buy(Kits.BUY_SALVAGE_MODEL, 'Wiederverwertungswerkzeug',
                                             lambda: bool(Kits.best_salvage(False)[0]), log)
                if not bought:
                    log('Zerlegen abgebrochen: kein Werkzeug.')
                    return salvaged
                kit_id, mode = Kits.best_salvage(rare)
            log(f'    Werkzeug Model {GLOBAL_CACHE.Item.GetModelID(kit_id)} ({mode.name}) fuer {label(item_id)}')
            node = RoutinesBT.Items.SalvageItem(item_id, salvage_mode=mode, preferred_kit_id=kit_id,
                                                allow_expert_for_common_materials=True,
                                                state_key=f'shared_salvage_{item_id}')
            deadline = time.monotonic() + ItemActions.ACTION_TIMEOUT_S * 3
            state = node.tick()
            while state == BehaviorTree.NodeState.RUNNING and time.monotonic() < deadline:
                yield
                state = node.tick()
            if state == BehaviorTree.NodeState.SUCCESS:
                salvaged.append(item_id)
            else:
                log(f'    nicht zerlegt ({state.name}): {label(item_id)}')
        return salvaged

    @staticmethod
    def sell(item_ids: list[int]) -> Generator[None, None, list[int]]:
        """Beim offenen Haendler verkaufen (Py4GWCoreLib SellItems); wartet, bis sie aus den Taschen sind (hoechstens
        SELL_CONFIRM_TIMEOUT_S). Gibt die verkauften Item-IDs zurueck."""
        yield from Routines.Yield.Merchant.SellItems(item_ids)
        deadline = time.monotonic() + ItemActions.SELL_CONFIRM_TIMEOUT_S
        left = Inventory.item_ids(INVENTORY_WITH_EQUIPMENT_BAGS)
        while any(item_id in left for item_id in item_ids) and time.monotonic() < deadline:
            yield
            left = Inventory.item_ids(INVENTORY_WITH_EQUIPMENT_BAGS)
        return [item_id for item_id in item_ids if item_id not in left]


# --- World -----------------------------------------------------------------------------------------

class World:
    @staticmethod
    def map_state() -> str:
        return f'Map {Map.GetMapID()}, bereit={Map.IsMapReady()}, Gruppe geladen={Party.IsPartyLoaded()}'

    @staticmethod
    def allies_in_compass() -> list[str]:
        """Namen aller lebenden Verbuendeten (ausser dem Spieler) im Kompass-Radius."""
        player_id = Player.GetAgentID()
        player_xy = Player.GetXY()
        return [
            Agent.GetNameByID(a) or f'Agent {a}' for a in AgentArray.GetAllyArray()
            if a != player_id and not Agent.IsDead(a) and math.dist(Agent.GetXY(a), player_xy) <= Range.Compass.value
        ]


# --- WidgetCheck -----------------------------------------------------------------------------------

class WidgetCheck:
    @staticmethod
    def ensure_enabled(names: Iterable[str]) -> tuple[list[str], list[str]]:
        """Schaltet ausgeschaltete Widgets ein (Name = Dateiname ohne .py); liefert (eingeschaltet, Fehler).

        enable_widget laedt das Modul sofort; scheitert das Laden (z. B. fehlender Import), bleibt das Widget aus.
        """
        handler = get_widget_handler()
        switched_on: list[str] = []
        errors: list[str] = []
        for name in names:
            try:
                if handler.is_widget_enabled(name):
                    continue
                if handler.get_widget_info(name) is None:
                    errors.append(f"Widget '{name}' nicht gefunden")
                    continue
                handler.enable_widget(name)
                if handler.is_widget_enabled(name):
                    switched_on.append(name)
                else:
                    errors.append(f"Widget '{name}' laesst sich nicht aktivieren (Ladefehler im Log)")
            except Exception as exc:
                errors.append(f"Widget '{name}': Fehler {exc!r}")
        return switched_on, errors

    @staticmethod
    def ensure_disabled(names: Iterable[str]) -> tuple[list[str], list[str]]:
        """Schaltet eingeschaltete Widgets aus; liefert (ausgeschaltet, Fehler). Nicht vorhanden zaehlt als aus."""
        handler = get_widget_handler()
        switched_off: list[str] = []
        errors: list[str] = []
        for name in names:
            try:
                if not handler.is_widget_enabled(name):
                    continue
                handler.disable_widget(name)
                if handler.is_widget_enabled(name):
                    errors.append(f"Widget '{name}' laesst sich nicht deaktivieren")
                else:
                    switched_off.append(name)
            except Exception as exc:
                errors.append(f"Widget '{name}': Fehler {exc!r}")
        return switched_off, errors


# --- Format ----------------------------------------------------------------------------------------

class Format:
    @staticmethod
    def duration(seconds: float) -> str:
        """Dauer als m:ss.mmm."""
        total_ms = int(round(max(0.0, seconds) * 1000.0))
        return f'{total_ms // 60000}:{(total_ms // 1000) % 60:02d}.{total_ms % 1000:03d}'

    @staticmethod
    def gold(amount: int) -> str:
        """Wie im Spiel: 12345 -> '12 Platin 345 Gold'."""
        platinum, gold = divmod(max(0, amount), 1000)
        return f'{platinum} Platin {gold} Gold' if platinum else f'{gold} Gold'
