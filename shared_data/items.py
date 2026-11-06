"""Items: Regeln fuer Loot, Verkaufen und Zerlegen; Angaben aus items.json.

Regeln: anlegen, aendern, abfragen, in einer JSON-Datei speichern und laden (je Zweck eine Datei, z. B. Loot,
Merchant, Salvage). items.json liefert ausserdem Salvage-Status, Sellable und Namen (item_flags); die
Spielpruefung check_inventory_items ergaenzt fehlende Angaben direkt in der Datei. Item-Bilder kommen ueber die
ModelFileID aus dem Gw.dat des Spiels (gwdat://), sonst aus Assets/Textures/Item Models.

Ausnahme in shared_data: dieses Modul hat auch eine GUI (draw_rules_tab), die ein Bot als Reiter einbindet.
Sie zeigt den Katalog aus items.json (gleicher Ordner), setzt per Haken Einzelregeln auf Aufheben
und listet im Unterreiter Item-Info, was ausgewaehlt ist, mit Haken fuer Verkaufen/Zerlegen/Identifizieren;
Merchant/Salvage haken aus dieser Auswahl an, was verkauft bzw. zerlegt wird; Drops zeigt, was beim Loot lag.
Gruppen "Ober / Unter" (Feld Categories) werden zwei Ebenen; Obergruppen in items.json
meta.catalog.hidden_groups blendet der Katalog aus.

Eine Regel haengt an einem Schluessel und sagt 'pick' (aufheben) oder 'ignore' (liegen lassen):

    model:28434         ein Item ueber seine Model-ID
    model:146:color:6   Farbstoffe teilen sich Model 146, deshalb zusaetzlich die Farbe (6 = Gelb)
    type:10             eine Gruppe ueber den Item-Typ (10 = Farbstoffe)
    rarity:0            eine Seltenheit (0 = Weiss)

Wer fragt, gibt die Schluessel vom Einzelnen zum Allgemeinen herein; die erste gesetzte Regel gewinnt.

Datei: {"rules": {"model:28434": {"action": "pick", "label": "Suesses-oder-Saures-Tasche", ...}}}
Neben action und label darf ein Eintrag beliebige Zusatzangaben tragen (z. B. model_id, name); sie bleiben erhalten.
"""

import json
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import PyImGui
import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import ImGui
from Py4GWCoreLib import Map
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_WITH_EQUIPMENT_BAGS, ItemType, Rarity
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.enums_src.UI_enums import ImguiFonts
from Py4GWCoreLib.py4gwcorelib_src.Color import ColorPalette

from .common import Icons, Log


PICK = 'pick'
IGNORE = 'ignore'

_DYE_MODEL_ID = 146

RuleEntry = dict[str, str | int]

DYE_COLORS = {
    2: 'Blau', 3: 'Gruen', 4: 'Lila', 5: 'Rot', 6: 'Gelb', 7: 'Braun',
    8: 'Orange', 9: 'Silber', 10: 'Schwarz', 11: 'Grau', 12: 'Weiss', 13: 'Rosa',
}
RARITIES = {0: 'Weiss', 1: 'Blau', 2: 'Lila', 3: 'Gold', 4: 'Gruen'}
ITEM_TYPES = {
    int(ItemType.Salvage): 'Bergungsgut', int(ItemType.Axe): 'Aexte', int(ItemType.Bag): 'Taschen',
    int(ItemType.Boots): 'Stiefel', int(ItemType.Bow): 'Boegen', int(ItemType.Bundle): 'Buendel',
    int(ItemType.Chestpiece): 'Brustteile', int(ItemType.Rune_Mod): 'Runen/Mods',
    int(ItemType.Usable): 'Verbrauchsgueter', int(ItemType.Dye): 'Farbstoffe',
    int(ItemType.Materials_Zcoins): 'Materialien', int(ItemType.Offhand): 'Fokusgegenstaende',
    int(ItemType.Gloves): 'Handschuhe', int(ItemType.Hammer): 'Haemmer', int(ItemType.Headpiece): 'Kopfteile',
    int(ItemType.CC_Shards): 'Splitter', int(ItemType.Key): 'Schluessel', int(ItemType.Leggings): 'Beinlinge',
    int(ItemType.Gold_Coin): 'Gold', int(ItemType.Quest_Item): 'Quest-Items', int(ItemType.Wand): 'Zauberstaebe',
    int(ItemType.Shield): 'Schilde', int(ItemType.Staff): 'Staebe', int(ItemType.Sword): 'Schwerter',
    int(ItemType.Kit): 'Kits', int(ItemType.Trophy): 'Trophaeen', int(ItemType.Scroll): 'Schriftrollen',
    int(ItemType.Daggers): 'Dolche', int(ItemType.Present): 'Geschenke', int(ItemType.Minipet): 'Minipets',
    int(ItemType.Scythe): 'Sensen', int(ItemType.Spear): 'Speere', int(ItemType.Storybook): 'Buecher',
    int(ItemType.Costume): 'Kostueme', int(ItemType.Costume_Headpiece): 'Kostuem-Kopfteile',
}


def model_name(model_id: int) -> str:
    """Englischer Name aus dem ModelID-Enum; leer, wenn unbekannt."""
    try:
        return ModelID(model_id).name.replace('_', ' ')
    except ValueError:
        return ''


def model_key(model_id: int) -> str:
    return f'model:{model_id}'


def dye_key(color: int) -> str:
    return f'model:{_DYE_MODEL_ID}:color:{color}'


def type_key(item_type: int) -> str:
    return f'type:{item_type}'


def rarity_key(rarity: int) -> str:
    return f'rarity:{rarity}'


def item_keys(model_id: int, dye_color: int, item_type: int, rarity: int) -> list[str]:
    """Schluessel eines Items vom Einzelnen zum Allgemeinen, fuer LootRules.decide/wants.

    Die Seltenheit gilt nur fuer Waffen und Ruestungen (Core: WEAPON_TYPES/ARMOR_TYPES, inkl. Salvage);
    Farbstoffe, Muenzen usw. folgen nur ihrer eigenen Regel.
    """
    keys = [dye_key(dye_color)] if model_id == _DYE_MODEL_ID and dye_color else []
    keys += [model_key(model_id), type_key(item_type)]
    if _rarity_applies(item_type):
        keys.append(rarity_key(rarity))
    return keys


def _rarity_applies(item_type: int) -> bool:
    try:
        kind = ItemType(item_type)
    except ValueError:
        return False
    return kind.is_weapon_type() or kind.is_armor_type()


def default_rules_path(bot_name: str) -> str:
    """Settings/Global/Widgets/Config/<Bot>_loot.json im Py4GW-Projekt (fuer alle Accounts)."""
    return os.path.join(
        PySystem.Console.get_projects_path(), 'Settings', 'Global', 'Widgets', 'Config', f'{bot_name}_loot.json'
    )


class LootRules:
    """Regeln einer Datei; load() beim Anlegen, jede Aenderung wird sofort gespeichert."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.rules: dict[str, RuleEntry] = {}
        self.load()

    def load(self) -> None:
        """Liest die Datei; fehlt sie, gibt es keine Regeln. Ungueltige Eintraege werden uebersprungen."""
        try:
            with open(self.path, encoding='utf-8') as handle:
                data = json.load(handle)
            self.rules = {
                str(key): {str(name): value for name, value in entry.items() if isinstance(value, (str, int))}
                for key, entry in data.get('rules', {}).items()
                if isinstance(entry, dict) and entry.get('action') in (PICK, IGNORE)
            }
        except FileNotFoundError:
            self.rules = {}
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            Log.write(f'Loot-Regeln nicht ladbar ({exc}); starte leer.', PySystem.Console.MessageType.Error)
            self.rules = {}

    def save(self) -> None:
        """Schreibt erst eine .tmp-Datei und ersetzt dann die alte, damit ein Abbruch keine halbe Datei hinterlaesst."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temp = self.path + '.tmp'
            with open(temp, 'w', encoding='utf-8') as handle:
                json.dump({'rules': self.rules}, handle, indent=2, ensure_ascii=False, sort_keys=True)
            os.replace(temp, self.path)
        except OSError as exc:
            Log.write(f'Loot-Regeln nicht speicherbar ({exc}).', PySystem.Console.MessageType.Error)

    def action(self, key: str) -> str | None:
        """PICK, IGNORE oder None (keine Regel)."""
        entry = self.rules.get(key)
        return str(entry['action']) if entry else None

    def label(self, key: str) -> str:
        entry = self.rules.get(key)
        return str(entry.get('label', key)) if entry else key

    def set(self, key: str, action: str | None, label: str = '', info: Mapping[str, str | int] | None = None,
            save: bool = True) -> None:
        """Setzt PICK/IGNORE (mit Beschriftung und Zusatzangaben) oder loescht die Regel bei None; speichert.

        save=False fuer viele Aenderungen am Stueck; danach einmal save() aufrufen.
        """
        if action is None:
            if self.rules.pop(key, None) is not None and save:
                self.save()
            return
        if action not in (PICK, IGNORE):
            raise ValueError(f'Unbekannte Loot-Aktion {action!r}')
        entry: RuleEntry = dict(self.rules.get(key, {}))
        entry.update(info or {})
        if label:
            entry['label'] = label
        entry.setdefault('label', key)
        entry['action'] = action
        if entry != self.rules.get(key):
            self.rules[key] = entry
            if save:
                self.save()

    def decide(self, keys: Iterable[str]) -> tuple[str | None, str]:
        """(Aktion, Schluessel) der ersten gesetzten Regel; (None, '') ohne Regel."""
        for key in keys:
            action = self.action(key)
            if action is not None:
                return action, key
        return None, ''

    def seed_rarities(self, rarities: Iterable[int]) -> None:
        """Startwerte fuer eine neue Regeldatei: diese Seltenheiten als Haken. Gibt es die Datei schon, nichts."""
        if self.rules or os.path.exists(self.path):
            return
        for rarity in rarities:
            name = RARITIES[rarity]
            self.set(rarity_key(rarity), PICK, f'Seltenheit {name}', {'rarity_id': rarity, 'rarity': name}, save=False)
        self.save()

    def wants(self, keys: Iterable[str]) -> bool:
        """Nur ausdruecklich auf Aufheben gesetzte Items; ohne Regel nicht."""
        return self.decide(keys)[0] == PICK


# --- GUI: Reiter Items mit dem Katalog aus items.json (wird vom Bot innerhalb von begin_tab_item gezeichnet) ---

_TABLE_FLAGS = (
    PyImGui.TableFlags.Borders
    | PyImGui.TableFlags.RowBg
    | PyImGui.TableFlags.SizingFixedFit
    | PyImGui.TableFlags.NoHostExtendX
)
_COLOR_IGNORE = (1.0, 0.25, 0.25, 1.0)
# Seltenheitsfarben aus der Core-Palette (ColorPalette.GwWhite, GwBlue, ...); einzige Quelle im Bot.
RGBA = tuple[float, float, float, float]


def _palette_rgba(name: str) -> RGBA:
    color = ColorPalette.GetColor(name)
    return color.r / 255, color.g / 255, color.b / 255, color.a / 255


_RARITY_COLORS: dict[int, RGBA] = {int(r): _palette_rgba(f'Gw{r.name}') for r in Rarity}


def rarity_code(rarity: object) -> int | None:
    """Seltenheit als Zahl aus Zahl, Spielname (White, Purple, ...) oder deutschem Namen (RARITIES)."""
    if isinstance(rarity, int):
        return rarity if rarity in _RARITY_COLORS else None
    text = str(rarity)
    if text in Rarity.__members__:
        return int(Rarity[text])
    return next((code for code, name in RARITIES.items() if name == text), None)


def rarity_color(rarity: object) -> RGBA | None:
    """Farbe der Seltenheit (siehe rarity_code); None, wenn keine erkennbar."""
    code = rarity_code(rarity)
    return None if code is None else _RARITY_COLORS[code]

_ITEMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'items.json')
_NO_TYPE = 'Sonstige'
_NO_CATEGORY = 'Ohne Kategorie'
_GROUP_SEP = ' / '
_RARITY_GROUP = 'Seltenheit'  # oberste Gruppe im Katalog, vor allen Gruppen aus items.json
_CATALOG_RARITIES = (0, 1, 2, 3, 4)  # Weiss, Blau, Lila, Gold, Gruen
_SEARCH_LIMIT = 300
_SELECTED_FONT_SCALE = 0.8  # kleinere Schrift in der Tabelle Item-Info
_SORT_UMLAUTS = str.maketrans({'\u00e4': 'a', '\u00f6': 'o', '\u00fc': 'u', '\u00df': 'ss'})


@dataclass(frozen=True)
class CatalogItem:
    key: str
    model_id: int
    name: str
    english: str
    type_group: str
    categories: tuple[str, ...]
    item_type: int | None
    note: str
    icon: str | None
    extra_keys: tuple[str, ...] = ()  # weitere Model-IDs desselben Items (AlsoModelIDs); Haken gilt fuer alle
    rarity: int | None = None  # Textfarbe; nur wenn fest (Rarity im Eintrag oder Gruppe "(einzigartig)"), sonst normal


_catalog: list[CatalogItem] | None = None  # nur sichtbare Gruppen
_catalog_by_key: dict[str, CatalogItem] = {}  # alle Items, auch ausgeblendete (fuer den Unterreiter Item-Info)
# Zustand der Katalog-Ansicht (immediate mode).
_view: dict[str, int | str | bool] = {}  # Suchtext je Liste: 'search_<id_prefix>'


def _sort_key(name: str) -> str:
    """Deutsch sortieren: Umlaute wie Grundbuchstaben, fuehrende Zeichen wie '-' oder '"' zaehlen nicht."""
    return name.casefold().translate(_SORT_UMLAUTS).lstrip(' -"\'.([')


def _type_group(type_name: str) -> tuple[str, int | None]:
    try:
        item_type = int(ItemType[type_name])
    except KeyError:
        return _NO_TYPE, None
    return ITEM_TYPES.get(item_type, _NO_TYPE), item_type


def _top_group(category: str) -> str:
    return category.split(_GROUP_SEP, 1)[0]


def _entry_icon(model_ids: list[int], entry: Mapping[str, object]) -> str | None:
    """Bild aus dem Gw.dat ueber ModelFileID, sonst aus Assets/Textures/Item Models (ueber alle Model-IDs).

    gwdat:// laedt das Spiel asynchron; das Bild erscheint nach ein paar Frames.
    """
    file_id = _entry_file_id(entry)
    if file_id:
        return f'gwdat://{file_id}'
    for model_id in model_ids:
        path = Icons.item(model_id)
        if path:
            return path
    return None


def _entry_file_id(entry: Mapping[str, object]) -> int:
    """ModelFileID des Eintrags (Datei im Gw.dat); 0 ohne gueltige Angabe."""
    file_id = entry.get('ModelFileID')
    return file_id if isinstance(file_id, int) and file_id > 0 else 0


def _entry_rarity(entry: Mapping[str, object]) -> int | None:
    """Feste Seltenheit eines Eintrags: Rarity (vom Spiel gesehen), sonst Gruen in einer Gruppe "(einzigartig)".

    Eine Model-ID faellt sonst in mehreren Seltenheiten (Waffen) oder ist ohnehin weiss; dann keine eigene Farbe.
    """
    code = rarity_code(entry.get('Rarity')) if entry.get('Rarity') not in (None, '') else None
    if code is not None:
        return code
    categories = entry.get('Categories') or ()
    if isinstance(categories, list) and any(str(c).endswith(_UNIQUE_SUFFIX) for c in categories):
        return int(Rarity.Green)
    return None


def _load_catalog() -> tuple[list[CatalogItem], frozenset[str]]:
    """(alle Items, ausgeblendete Obergruppen) aus items.json; Name deutsch, sonst englisch.

    Farbstoff 146 kommt zusaetzlich je Farbe.
    """
    try:
        with open(_ITEMS_PATH, encoding='utf-8') as handle:
            data = json.load(handle)
        items = data['items']
        hidden = frozenset(str(g) for g in (data.get('meta') or {}).get('catalog', {}).get('hidden_groups') or ())
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        Log.write(f'items.json nicht ladbar ({exc}).', PySystem.Console.MessageType.Error)
        return [], frozenset()
    catalog: list[CatalogItem] = []
    for type_name, entries in items.items():
        group, item_type = _type_group(type_name)
        for model_text, entry in entries.items():
            model_id = int(model_text)
            names = entry.get('Names') or {}
            english = str(names.get('English') or model_name(model_id) or f'Model {model_id}')
            categories = tuple(str(c) for c in entry.get('Categories') or ())
            note = 'Doppelt belegt, Name unsicher.' if 'Duplicate' in entry else ''
            also = [int(m) for m in entry.get('AlsoModelIDs') or ()]
            icon = _entry_icon([model_id, *also], entry)
            extra = tuple(model_key(m) for m in also)
            if model_id == _DYE_MODEL_ID:
                catalog.append(CatalogItem(model_key(model_id), model_id, 'Farbstoff (alle Farben)',
                                           'Vial of Dye (all colors)', group, categories, item_type, note, icon, extra))
                for color, color_name in DYE_COLORS.items():
                    catalog.append(CatalogItem(dye_key(color), model_id, f'Farbstoff {color_name}',
                                               f'Vial of Dye, color {color}', group, categories, item_type, '',
                                               Icons.dye(color) or icon))
                continue
            catalog.append(CatalogItem(model_key(model_id), model_id, str(names.get('German') or english), english,
                                       group, categories, item_type, note, icon, extra, _entry_rarity(entry)))
    catalog.sort(key=lambda item: _sort_key(item.name))
    note = 'Nur Waffen und Ruestungen ohne eigene Regel; alles andere nach seiner eigenen Regel.'
    catalog[:0] = [
        CatalogItem(rarity_key(r), 0, RARITIES[r], f'Rarity {RARITIES[r]}', '', (_RARITY_GROUP,), None, note, None)
        for r in _CATALOG_RARITIES
    ]
    return catalog, hidden


def _catalog_items() -> list[CatalogItem]:
    """Sichtbare Items: ausgeblendet ist ein Item, wenn alle seine Obergruppen ausgeblendet sind."""
    global _catalog, _catalog_by_key
    if _catalog is None:
        everything, hidden = _load_catalog()
        _catalog_by_key = {key: item for item in everything for key in (item.key, *item.extra_keys)}
        _catalog = [item for item in everything
                    if not item.categories or any(_top_group(c) not in hidden for c in item.categories)]
    return _catalog


def _groups(items: list[CatalogItem]) -> list[tuple[str, list[tuple[str, list[CatalogItem]]]]]:
    """Obergruppen alphabetisch ("Ohne Kategorie" zuletzt), darin Untergruppen; '' = Items direkt in der Obergruppe."""
    grouped: dict[str, dict[str, list[CatalogItem]]] = {}
    for item in items:
        for category in item.categories or (_NO_CATEGORY,):
            top, _sep, sub = category.partition(_GROUP_SEP)
            grouped.setdefault(top, {}).setdefault(sub, []).append(item)

    def order(group: tuple[str, dict[str, list[CatalogItem]]]) -> tuple[bool, bool, str]:
        return group[0] != _RARITY_GROUP, group[0] == _NO_CATEGORY, _sort_key(group[0])

    return [(top, sorted(subs.items(), key=lambda sub: (sub[0] != '', _sort_key(sub[0]))))
            for top, subs in sorted(grouped.items(), key=order)]


def _set_pick(rules: LootRules, item: CatalogItem, pick: bool, save: bool = True) -> None:
    """Haken setzen/entfernen, fuer den Hauptschluessel und alle weiteren Model-IDs des Items; speichert einmal."""
    for key in (item.key, *item.extra_keys):
        if not pick:
            rules.set(key, None, save=False)
        elif key.startswith('rarity:'):
            rarity = int(key.split(':', 1)[1])
            rules.set(key, PICK, f'Seltenheit {item.name}', {'rarity_id': rarity, 'rarity': item.name}, save=False)
        else:
            model_id = int(key.split(':')[1])
            info: dict[str, str | int] = {'model_id': model_id, 'model_name': item.english}
            if ':color:' in key:
                info['dye_color'] = int(key.rsplit(':', 1)[1])
            rules.set(key, PICK, item.name, info, save=False)
    if save:
        rules.save()


# --- Angaben aus items.json fuer Verkaufen/Zerlegen: Salvage-Status, Sellable, Name; Spielpruefung ---------------

# Platzhalter statt Material in CommonSalvage/RareSalvage (vereinheitlicht): 'Nicht wiederverwertbar',
# 'Keine weiteren' (keine seltenen Materialien), 'Unbekannt'.
SALVAGE_YES = 'yes'
SALVAGE_NO = 'no'
SALVAGE_UNKNOWN = 'unknown'
_SALVAGE_UNKNOWN_NAMES = frozenset({'unbekannt'})
_SALVAGE_PLACEHOLDERS = _SALVAGE_UNKNOWN_NAMES | frozenset({'nicht wiederverwertbar', 'keine weiteren'})
_SALVAGE_TYPES = frozenset({ItemType.Trophy, ItemType.Salvage})  # neben Waffen und Ruestungen; leer = Wiki-Luecke
ItemFlags = tuple[str, bool | None, str]  # (Salvage-Status, Sellable oder None = ungeprueft, Name oder '')
_item_flags_by_model: dict[int, ItemFlags] | None = None  # einmal aus items.json; nach Aenderung neu
# items.json wird einmal pro Sekunde auf Aenderungen geprueft (auch von aussen), siehe watch_items_json.
_ITEMS_JSON_POLL_S = 1.0
_items_json_watch: dict[str, float] = {'polled': 0.0, 'mtime': -1.0}


def _read_items_json() -> dict[str, dict[str, dict[str, object]]]:
    """Abschnitt items (Typ -> Model-ID -> Eintrag); wirft bei Lese- oder Formatfehler."""
    with open(_ITEMS_PATH, encoding='utf-8') as handle:
        data = json.load(handle)
    return data['items']


def _salvage_type(type_name: str) -> bool:
    """Typ, der zerlegt werden kann (Waffen, Ruestungen, Trophaeen, Salvage); leere Angabe ist dort eine Wiki-Luecke."""
    try:
        kind = ItemType[type_name]
    except KeyError:
        return False
    return kind.is_weapon_type() or kind.is_armor_type() or kind in _SALVAGE_TYPES


def _entry_salvage(entry: Mapping[str, object], salvage_type: bool) -> str:
    """SALVAGE_YES/NO/UNKNOWN eines Eintrags.

    Salvageable (aus der Spielpruefung) gilt zuerst. Sonst CommonSalvage/RareSalvage: Ja bei mindestens einem echten
    Material; Nein bei nur Platzhaltern wie "Nicht wiederverwertbar" oder leer bei einem Typ, der nie zerlegt wird
    (Runen, Minis, Schluessel ...); Unbekannt bei leer in einem Salvage-Typ oder nur "Unbekannt".
    """
    checked = entry.get('Salvageable')
    if isinstance(checked, bool):
        return SALVAGE_YES if checked else SALVAGE_NO
    names: list[str] = []
    for field in ('CommonSalvage', 'RareSalvage'):
        value = entry.get(field)
        if isinstance(value, dict):
            names += [str(name).strip().casefold() for name in value]
    if any(name not in _SALVAGE_PLACEHOLDERS for name in names):
        return SALVAGE_YES
    if any(name not in _SALVAGE_UNKNOWN_NAMES for name in names) or not salvage_type:
        return SALVAGE_NO
    return SALVAGE_UNKNOWN


def _entry_model_ids(model_text: str, entry: Mapping[str, object]) -> list[int]:
    """Model-ID des Eintrags und seine AlsoModelIDs."""
    model_ids = [int(model_text)]
    also = entry.get('AlsoModelIDs')
    if isinstance(also, list):
        model_ids += [model_id for model_id in also if isinstance(model_id, int)]
    return model_ids


def _entry_name(entry: Mapping[str, object]) -> str:
    """Name deutsch, sonst englisch; '' ohne Namen."""
    names = entry.get('Names')
    if isinstance(names, dict):
        return str(names.get('German') or names.get('English') or '')
    return ''


def _load_item_flags() -> dict[int, ItemFlags]:
    try:
        entries_by_type = _read_items_json()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        Log.write(f'items.json nicht ladbar ({exc}); Merchant/Salvage zeigen alles.', PySystem.Console.MessageType.Error)
        return {}
    flags: dict[int, ItemFlags] = {}
    for type_name, entries in entries_by_type.items():
        salvage_type = _salvage_type(type_name)
        for model_text, entry in entries.items():
            sellable = entry.get('Sellable')
            value = (_entry_salvage(entry, salvage_type), sellable if isinstance(sellable, bool) else None,
                     _entry_name(entry))
            for model_id in _entry_model_ids(model_text, entry):
                flags[model_id] = value
    return flags


def item_flags(model_id: int) -> ItemFlags:
    """(Salvage-Status, Sellable oder None = ungeprueft, Name deutsch/englisch oder '') eines Models."""
    global _item_flags_by_model
    if _item_flags_by_model is None:
        _item_flags_by_model = _load_item_flags()
    return _item_flags_by_model.get(model_id, (SALVAGE_UNKNOWN, None, ''))


def salvage_status(item: CatalogItem) -> str:
    if item.key.startswith('rarity:'):
        return SALVAGE_YES  # Seltenheit gilt nur fuer Waffen und Ruestungen
    return item_flags(item.model_id)[0]


def merchant_listed(item: CatalogItem) -> bool:
    """Merchant-Liste ohne Gold, ohne die Seltenheit Gruen und ohne laut Spielpruefung Unverkaeufliches. Gruene
    Einzelitems erkennt erst der Verkauf am Item (common.ItemActions.sellable)."""
    if item.item_type == int(ItemType.Gold_Coin):
        return False
    if item.key.startswith('rarity:'):
        return item.key != rarity_key(int(Rarity.Green))
    return item_flags(item.model_id)[1] is not False


def inventory_item_keys(item_id: int) -> list[str]:
    """Filterschluessel eines Items im Inventar wie beim Loot (Model, Farbe, Typ, Seltenheit)."""
    item = GLOBAL_CACHE.Item
    return item_keys(int(item.GetModelID(item_id)), int(item.GetDyeColor(item_id)), int(item.GetItemType(item_id)[0]),
                     int(item.Rarity.GetRarity(item_id)[0]))


def item_label(item_id: int) -> str:
    """Name aus items.json, sonst aus dem Spiel (kommt verzoegert), sonst die Model-ID; dazu Seltenheit und ID."""
    model_id = int(GLOBAL_CACHE.Item.GetModelID(item_id))
    name = item_flags(model_id)[2] or clean_game_name(GLOBAL_CACHE.Item.GetName(item_id) or '')
    rarity = GLOBAL_CACHE.Item.Rarity.GetRarity(item_id)[1]
    return f'{name or f"Model {model_id}"} ({rarity}, Item {item_id})'


def _items_json_mtime() -> float:
    try:
        return os.path.getmtime(_ITEMS_PATH)
    except OSError:
        return 0.0


def _reload_items_json() -> None:
    """Nach eigener Aenderung an items.json: Katalog und Salvage/Merchant-Angaben beim naechsten Zugriff neu lesen."""
    global _catalog, _catalog_by_key, _item_flags_by_model
    _catalog = None
    _catalog_by_key = {}
    _item_flags_by_model = None
    _items_json_watch['mtime'] = _items_json_mtime()  # eigene Aenderung; watch_items_json meldet sie nicht noch einmal


def check_inventory_items(log_source: str = 'shared_data', ground_file_ids: Mapping[int, int] | None = None,
                          unknown: 'UnknownItems | None' = None) -> str:
    """Spielpruefung: Items in den Taschen, deren Eintrag in items.json noch keine Angabe hat, im Spiel pruefen.

    Schreibt Salvageable (nur wo der Salvage-Status unbekannt ist), Sellable (Haendlerwert > 0, nur wo es fehlt),
    ModelFileID (fuer das Bild aus dem Gw.dat, nur wo sie fehlt und nur von der Haupt-Model-ID) und GameChecked
    (Datum) direkt in items.json; jede Aenderung ins Log. Angepasste Items zaehlen fuer Salvage/Sellable nicht (dort
    sperrt das Spiel das Zerlegen). ground_file_ids (Model-ID -> ModelFileID, beim Loot am Boden gelesen) ergaenzt
    fehlende ModelFileIDs auch fuer Items, die nicht in den Taschen sind. unknown: unbekannte Items mit Namen
    kommen als neue Eintraege dazu (_add_unknown_entries). Alles in einem Schreibvorgang.
    Gibt die Zusammenfassung zurueck.
    """
    if not Map.IsMapReady():
        return 'Erst pruefen, wenn die Map geladen ist.'
    try:
        entries_by_type = _read_items_json()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f'items.json nicht ladbar ({exc}).'
    index: dict[int, tuple[dict[str, object], bool]] = {}
    for type_name, entries in entries_by_type.items():
        salvage_type = _salvage_type(type_name)
        for model_text, entry in entries.items():
            for model_id in _entry_model_ids(model_text, entry):
                index.setdefault(model_id, (entry, salvage_type))
    bags = GLOBAL_CACHE.ItemArray.CreateBagList(*(int(bag) for bag in INVENTORY_WITH_EQUIPMENT_BAGS))
    salvage_set = sellable_set = file_set = not_in_json = 0
    changes: list[str] = []
    today = datetime.now().strftime('%Y-%m-%d')
    for item_id in GLOBAL_CACHE.ItemArray.GetItemArray(bags):
        model_id = int(GLOBAL_CACHE.Item.GetModelID(item_id))
        found = index.get(model_id)
        if found is None:
            not_in_json += 1
            continue
        entry, salvage_type = found
        written: list[str] = []
        # Nur von der Haupt-Model-ID: eine AlsoModelID hat eine eigene Datei.
        if not _entry_file_id(entry) and model_id == entry.get('ModelID'):
            file_id = int(GLOBAL_CACHE.Item.GetModelFileID(item_id) or 0)
            if file_id > 0:
                entry['ModelFileID'] = file_id
                entry['ModelFileIDSource'] = 'Spiel (Inventar)'
                file_set += 1
                written.append(f'ModelFileID={file_id}')
        if not GLOBAL_CACHE.Item.Properties.IsCustomized(item_id):
            if _entry_salvage(entry, salvage_type) == SALVAGE_UNKNOWN:
                entry['Salvageable'] = bool(GLOBAL_CACHE.Item.Usage.IsSalvageable(item_id))
                salvage_set += 1
                written.append(f"Salvageable={'ja' if entry['Salvageable'] else 'nein'}")
            if not isinstance(entry.get('Sellable'), bool):
                entry['Sellable'] = int(GLOBAL_CACHE.Item.Properties.GetValue(item_id) or 0) > 0
                sellable_set += 1
                written.append(f"Sellable={'ja' if entry['Sellable'] else 'nein'}")
        if written:
            entry['GameChecked'] = today
            changes.append(f'{_entry_name(entry) or "?"} ({entry.get("ModelID", "?")}): {", ".join(written)}')
    for model_id, file_id in (ground_file_ids or {}).items():
        found = index.get(model_id)
        if found is None or file_id <= 0:
            continue
        entry = found[0]
        if _entry_file_id(entry) or model_id != entry.get('ModelID'):
            continue
        entry['ModelFileID'] = file_id
        entry['ModelFileIDSource'] = 'Spiel (am Boden)'
        entry['GameChecked'] = today
        file_set += 1
        changes.append(f'{_entry_name(entry) or "?"} ({model_id}): ModelFileID={file_id} (am Boden)')
    ready = unknown.ready() if unknown is not None else []
    new_items = _add_unknown_entries(entries_by_type, ready)
    if not salvage_set and not sellable_set and not file_set and not new_items:
        return f'Nichts zu pruefen: alle Items im Inventar haben schon Angaben ({not_in_json} nicht in items.json).'
    try:
        with open(_ITEMS_PATH, encoding='utf-8') as handle:
            data = json.load(handle)
        data['items'] = entries_by_type
        # Erst .tmp, dann ersetzen: ein Abbruch hinterlaesst keine halbe Datei. Format wie in der Datei.
        temp = _ITEMS_PATH + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(data, indent=1, ensure_ascii=False))
        os.replace(temp, _ITEMS_PATH)
    except (OSError, ValueError, TypeError) as exc:
        return f'items.json nicht speicherbar ({exc}).'
    _reload_items_json()  # auch der Katalog: neue ModelFileIDs und Items zeigen sich sofort
    if unknown is not None:
        unknown._mark_written(ready, new_items)
    for change in changes:
        Log.write(f'items.json geaendert: {change}', PySystem.Console.MessageType.Info, log_source)
    for new_item in new_items:
        Log.write(f'items.json neues Item: {new_item}', PySystem.Console.MessageType.Info, log_source)
    return (f'items.json ergaenzt: {len(new_items)}x neues Item, {salvage_set}x Salvageable, {sellable_set}x Sellable,'
            f' {file_set}x ModelFileID ({not_in_json} Items nicht in items.json).')


def watch_items_json(log_source: str = 'shared_data') -> None:
    """Jeden Frame aufrufen; prueft einmal pro Sekunde, ob items.json von aussen geaendert wurde (Editor, anderes
    Skript), und liest dann Salvage/Sellable/Namen neu ein. Katalog-Gruppen und Icons erst nach Neuladen des Skripts."""
    global _item_flags_by_model
    now = time.monotonic()
    if now - _items_json_watch['polled'] < _ITEMS_JSON_POLL_S:
        return
    _items_json_watch['polled'] = now
    mtime = _items_json_mtime()
    if _items_json_watch['mtime'] < 0:
        _items_json_watch['mtime'] = mtime  # erster Aufruf: nur merken
        return
    if mtime == _items_json_watch['mtime']:
        return
    _items_json_watch['mtime'] = mtime
    _item_flags_by_model = None
    Log.write('items.json von aussen geaendert: Salvage/Merchant neu eingelesen '
              '(Katalog-Gruppen erst nach Neuladen des Skripts).', PySystem.Console.MessageType.Info, log_source)


TipFn = Callable[[CatalogItem], str]  # Zusatzzeile im Tooltip ('' = keine)
# Weitere Haken-Spalte: (Titel, Regeln, gilt fuer das Item?); gilt sie nicht, steht '-' statt eines Hakens.
ExtraColumn = tuple[str, 'LootRules', Callable[[CatalogItem], bool]]


def _draw_item_rows(rules: LootRules, items: list[CatalogItem], id_prefix: str, table_id: str,
                    column: str = 'Aufheben', extra_tip: TipFn | None = None,
                    extra_columns: Sequence[ExtraColumn] = ()) -> None:
    """Haken = Einzelregel PICK (Aufheben bzw. Verkaufen/Zerlegen); ohne Haken keine Einzelregel.
    Ignorieren/Gruppenregel steht daneben."""
    if not PyImGui.begin_table(f'##{id_prefix}_{table_id}', 3 + len(extra_columns), _TABLE_FLAGS):
        return
    for title in (column, *(extra[0] for extra in extra_columns), 'Item', 'Model-ID'):
        PyImGui.table_setup_column(title)
    PyImGui.table_headers_row()
    for item in items:
        action = rules.action(item.key)
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        picked = PyImGui.checkbox(f'##{id_prefix}_{table_id}_{item.key}', action == PICK)
        if picked != (action == PICK):
            _set_pick(rules, item, picked)
        for index, (_title, extra_rules, applies) in enumerate(extra_columns):
            PyImGui.table_next_column()
            if not applies(item):
                PyImGui.text_disabled('-')
                continue
            checked = extra_rules.action(item.key) == PICK
            value = PyImGui.checkbox(f'##{id_prefix}_{table_id}_x{index}_{item.key}', checked)
            if value != checked:
                _set_pick(extra_rules, item, value)
        PyImGui.table_next_column()
        size = PyImGui.get_text_line_height()
        if item.icon:
            ImGui.DrawTexture(item.icon, size, size)
        else:
            PyImGui.dummy((size, size))
        PyImGui.same_line(0, 4)
        if item.key.startswith('rarity:'):
            color = rarity_color(int(item.key.split(':', 1)[1]))
        else:
            color = rarity_color(item.rarity) if item.rarity is not None else None
        if action == IGNORE:
            PyImGui.text_colored(f'{item.name} (ignoriert)', _COLOR_IGNORE)
        elif color is not None:
            PyImGui.text_colored(item.name, color)
        else:
            PyImGui.text(item.name)
        if PyImGui.is_item_hovered():
            lines = [item.english, *item.categories]
            if action is None and item.item_type is not None:
                inherited = rules.action(type_key(item.item_type))
                if inherited:
                    lines.append(f'Gruppenregel {item.type_group}: {"Aufheben" if inherited == PICK else "Ignorieren"}')
            if item.note:
                lines.append(item.note)
            extra = extra_tip(item) if extra_tip else ''
            if extra:
                lines.append(extra)
            PyImGui.set_tooltip('\n'.join(lines))
        PyImGui.table_next_column()
        PyImGui.text(str(item.model_id) if item.model_id else '-')
    PyImGui.end_table()


def _draw_catalog(rules: LootRules, id_prefix: str, log_source: str, items: list[CatalogItem] | None = None,
                  column: str = 'Aufheben', verb: str = 'aufheben', extra_tip: TipFn | None = None,
                  hidden_text: str = '') -> None:
    """Suche, Zaehler und Gruppen mit ALLE/KEINE; ohne items der ganze Katalog (Reiter Loot)."""
    if items is None:
        items = _catalog_items()
        if not items:
            PyImGui.text_disabled(f'Keine Items: {_ITEMS_PATH}')
            return
    search_key = f'search_{id_prefix}'
    PyImGui.push_item_width(170)
    _view[search_key] = PyImGui.input_text(f'Suche (Name/ID)##{id_prefix}_search', str(_view.get(search_key, '')))
    PyImGui.pop_item_width()
    picked_total = sum(1 for item in items if rules.action(item.key) == PICK)
    PyImGui.same_line(0, 10)
    PyImGui.text_disabled(f'{picked_total} von {len(items)} ausgewaehlt')
    if hidden_text:
        PyImGui.same_line(0, 10)
        PyImGui.text_disabled(hidden_text)
    PyImGui.separator()

    search = str(_view[search_key]).strip().casefold()
    if search:
        found = [item for item in items
                 if search in item.name.casefold() or search in item.english.casefold() or search == str(item.model_id)]
        if not found:
            PyImGui.text_disabled('Nichts gefunden.')
            return
        _draw_item_rows(rules, found[:_SEARCH_LIMIT], id_prefix, 'found', column, extra_tip)
        if len(found) > _SEARCH_LIMIT:
            PyImGui.text_disabled(f'{len(found) - _SEARCH_LIMIT} weitere, Suche genauer fassen.')
        return

    for index, (top, subs) in enumerate(_groups(items)):
        group = list({item.key: item for _sub, members in subs for item in members}.values())
        # ### haelt die ID fest, waehrend sich der Zaehler im Titel aendert.
        if not PyImGui.collapsing_header(f'{_group_title(rules, top, group)}###{id_prefix}_grp_{top}'):
            continue
        _draw_group_buttons(rules, group, top, f'{id_prefix}_{index}', log_source, verb)
        for sub_index, (sub, members) in enumerate(subs):
            table_id = f'grp_{index}_{sub_index}'
            if not sub:
                _draw_item_rows(rules, members, id_prefix, table_id, column, extra_tip)
                continue
            if not PyImGui.tree_node(f'{_group_title(rules, sub, members)}###{id_prefix}_sub_{top}_{sub}'):
                continue
            label = f'{top}{_GROUP_SEP}{sub}'
            _draw_group_buttons(rules, members, label, f'{id_prefix}_{index}_{sub_index}', log_source, verb)
            _draw_item_rows(rules, members, id_prefix, table_id, column, extra_tip)
            PyImGui.tree_pop()


def _group_title(rules: LootRules, name: str, items: list[CatalogItem]) -> str:
    picked = sum(1 for item in items if rules.action(item.key) == PICK)
    return f'{name} ({picked}/{len(items)})'


def _draw_group_buttons(rules: LootRules, items: list[CatalogItem], name: str, button_id: str, log_source: str,
                        verb: str = 'aufheben') -> None:
    """ALLE / KEINE fuer genau diese Items; speichert einmal."""
    if PyImGui.small_button(f'ALLE##{button_id}_all'):
        for item in items:
            _set_pick(rules, item, True, save=False)
        rules.save()
        Log.write(f'Katalog {name}: alle {verb}.', PySystem.Console.MessageType.Info, log_source)
    PyImGui.same_line(0, 10)
    if PyImGui.small_button(f'KEINE##{button_id}_none'):
        for item in items:
            if rules.action(item.key) == PICK:
                rules.set(item.key, None, save=False)
        rules.save()
        Log.write(f'Katalog {name}: keine {verb}.', PySystem.Console.MessageType.Info, log_source)


def _selected_item(rules: LootRules, key: str) -> CatalogItem:
    """Eintrag aus dem Katalog; fehlt die Regel dort (z. B. von Hand eingetragen), aus der Regel selbst."""
    item = _catalog_by_key.get(key)
    if item is not None:
        return item
    entry = rules.rules[key]
    model_id = entry.get('model_id', 0)
    model_id = model_id if isinstance(model_id, int) else 0
    return CatalogItem(key, model_id, rules.label(key), str(entry.get('model_name', key)), _NO_TYPE, (), None,
                       'Nicht in items.json.', Icons.item(model_id))


def _selection_sort_key(item: CatalogItem) -> tuple[int, str]:
    """Seltenheiten in Spielreihenfolge (Weiss, Blau, Lila, Gold, Gruen), alles andere nach Namen."""
    if item.key.startswith('rarity:'):
        return int(item.key.split(':', 1)[1]), ''
    return len(RARITIES), _sort_key(item.name)


def _picked_items(rules: LootRules) -> list[CatalogItem]:
    """Katalogeintraege aller Regeln mit Aufheben; ein Item mit mehreren Model-IDs nur einmal."""
    _catalog_items()  # fuellt _catalog_by_key fuer _selected_item
    picked = (_selected_item(rules, key) for key in rules.rules if rules.action(key) == PICK)
    unique = {item.key: item for item in picked}
    return sorted(unique.values(), key=_selection_sort_key)


def identify_applies(item: CatalogItem) -> bool:
    """Identifizieren ergibt nur bei Waffen und Ruestungen Sinn (und bei den Seltenheiten, die nur fuer sie gelten)."""
    return item.key.startswith('rarity:') or (item.item_type is not None and _rarity_applies(item.item_type))


def _draw_selected(rules: LootRules, id_prefix: str, merchant: LootRules | None, salvage: LootRules | None,
                   identify: LootRules | None) -> None:
    """Item-Info: alles, was aufgehoben wird; daneben Verkaufen/Zerlegen/Identifizieren, wenn uebergeben.
    Haken Aufheben weg = nicht mehr aufheben."""
    items = _picked_items(rules)
    PyImGui.spacing()
    if not items:
        PyImGui.text_disabled('Noch nichts ausgewaehlt. Im Reiter Loot anhaken.')
        return
    extra: list[ExtraColumn] = []
    if merchant is not None:
        extra.append(('Verkaufen', merchant, merchant_listed))
    if salvage is not None:
        extra.append(('Zerlegen', salvage, lambda item: salvage_status(item) != SALVAGE_NO))
    if identify is not None:
        extra.append(('Identifizieren', identify, identify_applies))
    PyImGui.text(f'{len(items)} ausgewaehlt')
    PyImGui.separator()
    PyImGui.push_font_scaled(ImguiFonts.Regular_14.value, _SELECTED_FONT_SCALE)
    _draw_item_rows(rules, items, id_prefix, 'selected', extra_columns=extra)
    PyImGui.pop_font_scaled()


def _draw_action_list(rules: LootRules, loot_rules: LootRules, id_prefix: str, log_source: str, salvage: bool) -> None:
    """Unterreiter Merchant bzw. Salvage: wie Loot, aber nur die Items der Loot-Auswahl. Salvage blendet aus, was
    laut items.json nicht wiederverwertbar ist, Merchant Unverkaeufliches. Regeln zu Items, die nicht mehr
    aufgehoben werden, bleiben in der Datei."""
    PyImGui.spacing()
    PyImGui.text_wrapped('Haken = zerlegen (nach dem Identifizieren).' if salvage else 'Haken = beim Haendler verkaufen.')
    items = _picked_items(loot_rules)
    if not items:
        PyImGui.text_disabled('Noch nichts zum Aufheben ausgewaehlt. Im Unterreiter Loot anhaken.')
        return
    shown = [item for item in items if (salvage_status(item) != SALVAGE_NO if salvage else merchant_listed(item))]
    hidden = len(items) - len(shown)
    hidden_label = 'nicht wiederverwertbar' if salvage else 'unverkaeuflich'
    if not shown:
        PyImGui.text_disabled(f'Nichts in der Loot-Auswahl ({hidden} {hidden_label} ausgeblendet).')
        return

    def unknown_tip(item: CatalogItem) -> str:
        return 'Wiederverwertbar laut Wiki unbekannt.' if salvage_status(item) == SALVAGE_UNKNOWN else ''

    _draw_catalog(rules, id_prefix, log_source, shown, 'Zerlegen' if salvage else 'Verkaufen',
                  'zerlegen' if salvage else 'verkaufen', unknown_tip if salvage else None,
                  f'({hidden} {hidden_label} ausgeblendet)' if hidden else '')


# --- Unbekannte Items: beim Loot gesehen, aber nicht in items.json --------------------------------

_RX_COLOR = re.compile(r'</?c(=[^>]*)?>')
_RX_PLURAL = re.compile(r'\[pl:"[^"]*"\]|\["[^"]*"\]|(?<=[^\W\d_])\[[a-zäöüß]{1,3}\]')
_CATEGORY_SHARE = 0.75  # so viele Eintraege eines Typs muessen dieselbe Kategorie haben, sonst nur die Obergruppe
_UNIQUE_SUFFIX = ' (einzigartig)'  # gruene Items kommen in diese Variante ihrer Kategorie, wenn es sie gibt (Waffen)

UnknownEntry = dict[str, object]


def clean_game_name(name: str) -> str:
    """Spielname ohne Farbcodes (<c=...>) und Plural-Marken (Rune[pl:"Runen"], Feder[n]); echte [Klammern] bleiben."""
    return ' '.join(_RX_PLURAL.sub('', _RX_COLOR.sub('', name or '')).split())


def is_known_model(model_id: int) -> bool:
    """In items.json enthalten (auch ausgeblendete Gruppen und weitere Model-IDs eines Eintrags)."""
    _catalog_items()
    return model_key(model_id) in _catalog_by_key


def _type_categories(entries_by_type: Mapping[str, Mapping[str, Mapping[str, object]]]) -> dict[str, list[str]]:
    """Kategorie je ItemType fuer neue Eintraege, abgeleitet aus den vorhandenen Eintraegen desselben Typs.

    Die haeufigste Angabe in Categories, wenn sie mindestens _CATEGORY_SHARE der Eintraege hat (Trophy -> Trophaeen);
    sonst nur die gemeinsame Obergruppe (Usable -> Verbrauchsgueter); ohne gemeinsame Obergruppe leer (Ohne Kategorie).
    """
    result: dict[str, list[str]] = {}
    for type_name, entries in entries_by_type.items():
        counts = Counter(tuple(str(c) for c in entry.get('Categories') or ()) for entry in entries.values())
        if not counts:
            continue
        top, count = counts.most_common(1)[0]
        if top and count >= _CATEGORY_SHARE * len(entries):
            result[type_name] = list(top)
            continue
        groups = {_top_group(c) for categories in counts for c in categories}
        result[type_name] = [groups.pop()] if len(groups) == 1 else []
    return result


class UnknownItems:
    """Beim Loot gesehene Items ohne Eintrag in items.json; je Model-ID ein Eintrag, Aufbau wie in items.json.

    Nur im Speicher: check_inventory_items traegt nach dem Loot alle mit Namen in items.json ein und nimmt sie heraus.
    Ohne Namen bleibt ein Eintrag hier, bis das Spiel ihn liefert (oft erst beim naechsten Sehen).
    """

    def __init__(self) -> None:
        self.entries: dict[str, UnknownEntry] = {}
        self._written: list[str] = []  # Beschreibungen der eingetragenen Items, fuer den Bot (take_written)

    def record(self, model_id: int, dye_color: int, item_type: int, rarity: int,
               details: Mapping[str, object], map_name: str) -> bool:
        """Eintragen bzw. aktualisieren (ohne zu speichern); True, wenn die Model-ID neu ist."""
        now = datetime.now().isoformat(timespec='seconds')
        raw_name = str(details.get('name') or '')
        try:
            type_name = ItemType(item_type).name
        except ValueError:
            type_name = str(details.get('item_type_name') or item_type)
        entry = self.entries.get(str(model_id))
        if entry is None:
            entry = {
                'ModelID': model_id, 'ModelFileID': details.get('model_file_id', -1), 'Names': {},
                'ItemType': type_name, 'Acquisition': '', 'Description': '', 'Attributes': [], 'CommonSalvage': {},
                'RareSalvage': {}, 'WikiURL': '', 'InventoryIcon': '', 'InventoryIconURL': '', 'NickIndex': None,
                'Profession': details.get('profession') or None, 'Category': None, 'SubCategory': None,
                'WikiScraped': False, 'Categories': [], 'FirstSeen': now, 'SeenCount': 0, 'Maps': [],
            }
            self.entries[str(model_id)] = entry
        if raw_name and not entry.get('GameName'):  # Name kommt oft erst beim naechsten Mal
            entry['GameName'] = raw_name
            entry['Names'] = {'German': clean_game_name(raw_name)}
        enc = details.get('name_enc')
        if enc and not entry.get('NameEncoded'):
            entry['NameEncoded'] = ', '.join(f'0x{int(c):X}' for c in enc if isinstance(c, int))
        entry.update({
            'Rarity': details.get('rarity_name') or rarity, 'DyeColor': dye_color, 'Value': details.get('value', 0),
            'Stackable': bool(details.get('stackable')), 'LastSeen': now,
            'SeenCount': int(entry.get('SeenCount') or 0) + 1,
        })
        maps = entry.setdefault('Maps', [])
        if isinstance(maps, list) and map_name and map_name not in maps:
            maps.append(map_name)
            entry['Acquisition'] = 'gesehen in ' + ', '.join(str(m) for m in maps)
        return entry['SeenCount'] == 1

    def pending(self) -> list[UnknownEntry]:
        """Noch nicht in items.json; neueste zuerst."""
        rows = [e for k, e in self.entries.items() if not is_known_model(int(k))]
        return sorted(rows, key=lambda e: str(e.get('LastSeen') or ''), reverse=True)

    def ready(self) -> list[UnknownEntry]:
        """Noch nicht in items.json und mit Namen, also bereit zum Eintragen."""
        return [entry for entry in self.pending() if _unknown_name(entry)]

    def _mark_written(self, entries: Iterable[UnknownEntry], descriptions: Iterable[str]) -> None:
        for entry in entries:
            self.entries.pop(str(entry.get('ModelID')), None)
        self._written.extend(descriptions)

    def take_written(self) -> list[str]:
        """Seit dem letzten Aufruf in items.json eingetragene Items (Beschreibung); danach leer."""
        written, self._written = self._written, []
        return written


def _add_unknown_entries(entries_by_type: dict[str, dict[str, dict[str, object]]],
                         ready: Sequence[UnknownEntry]) -> list[str]:
    """Unbekannte Items in den Abschnitt items eintragen (ItemType -> ModelID); je Item eine Beschreibung.

    Kategorie wie die anderen Eintraege desselben Typs (_type_categories); gruene Items in die Variante
    "(einzigartig)", wenn es sie gibt (Waffen).
    """
    categories = _type_categories(entries_by_type)
    known = {str(c) for entries in entries_by_type.values() for e in entries.values()
             for c in e.get('Categories') or ()}
    descriptions: list[str] = []
    for entry in ready:
        type_name = str(entry.get('ItemType') or 'Unknown')
        category = categories.get(type_name, [])
        if rarity_code(entry.get('Rarity')) == int(Rarity.Green):
            category = [c + _UNIQUE_SUFFIX if c + _UNIQUE_SUFFIX in known else c for c in category]
        entries_by_type.setdefault(type_name, {})[str(entry.get('ModelID'))] = {
            **entry, 'Categories': category, 'ModelIDSource': 'Spiel (beim Loot gesehen)'}
        descriptions.append(f'{_unknown_name(entry)} ({entry.get("ModelID")}) als {type_name}, '
                            f'Kategorie {" / ".join(category) or "keine"}')
    return descriptions


def drop_key(model_id: int, dye_color: int) -> str:
    """Ein Eintrag je Item, Farbstoffe je Farbe (wie die Loot-Regeln)."""
    return dye_key(dye_color) if model_id == _DYE_MODEL_ID and dye_color else model_key(model_id)


class DropLog:
    """Beim Loot gesehene eigene Drops (bekannt und unbekannt): wie oft gesehen, wie oft aufgehoben.

    Nur fuer die laufende Sitzung im Speicher; wird nicht gespeichert.
    """

    def __init__(self) -> None:
        self.entries: dict[str, UnknownEntry] = {}

    def clear(self) -> None:
        self.entries.clear()

    def seen(self, model_id: int, dye_color: int, item_type: int, rarity: int,
             details: Mapping[str, object], map_name: str) -> str:
        """Ein Item am Boden zaehlen; gibt den Schluessel fuer picked() zurueck."""
        key = drop_key(model_id, dye_color)
        _catalog_items()
        known = _catalog_by_key.get(key) or _catalog_by_key.get(model_key(model_id))
        name = known.name if known else clean_game_name(str(details.get('name') or ''))
        entry = self.entries.setdefault(key, {'ModelID': model_id, 'Seen': 0, 'Picked': 0, 'Maps': []})
        if name:
            entry['Name'] = name
        if known:
            entry['CatalogKey'] = known.key  # Katalog-Eintrag fuer den Haken im Reiter Drops
        maps = entry.setdefault('Maps', [])
        if isinstance(maps, list) and map_name and map_name not in maps:
            maps.append(map_name)
        entry.update({
            'ItemType': item_type, 'Rarity': details.get('rarity_name') or RARITIES.get(rarity, str(rarity)),
            'Value': details.get('value', 0), 'Seen': _count(entry, 'Seen') + 1,
            'LastSeen': datetime.now().isoformat(timespec='seconds'),
        })
        return key

    def picked(self, key: str) -> None:
        entry = self.entries.get(key)
        if entry is not None:
            entry['Picked'] = _count(entry, 'Picked') + 1

    def salvaged(self, key: str) -> None:
        """Ein aufgehobenes Item wurde zerlegt: zaehlt nicht mehr als aufgehoben (Liegen gelassen bleibt gleich)."""
        entry = self.entries.get(key)
        if entry is not None:
            entry['Salvaged'] = _count(entry, 'Salvaged') + 1

    def sold(self, key: str) -> None:
        """Ein aufgehobenes Item wurde verkauft: zaehlt nicht mehr als aufgehoben (Liegen gelassen bleibt gleich)."""
        entry = self.entries.get(key)
        if entry is not None:
            entry['Sold'] = _count(entry, 'Sold') + 1

    def add_gold(self, key: str, amount: int) -> None:
        """Eigener Gold-Anteil (Inventar nachher minus vorher), ueber die Sitzung addiert."""
        entry = self.entries.get(key)
        if entry is not None:
            entry['GoldShare'] = _count(entry, 'GoldShare') + max(0, amount)

    def picked_rows(self) -> list[UnknownEntry]:
        """Mindestens einmal aufgehoben und nicht alles davon zerlegt oder verkauft; nach Name."""
        rows = [e for e in self.entries.values() if _kept(e) > 0]
        return sorted(rows, key=lambda e: _sort_key(_drop_name(e)))

    def left_rows(self) -> list[UnknownEntry]:
        """In items.json, aber mindestens einmal liegen gelassen; nach Name."""
        rows = [e for e in self.entries.values()
                if _count(e, 'Seen') > _count(e, 'Picked') and is_known_model(_count(e, 'ModelID'))]
        return sorted(rows, key=lambda e: _sort_key(_drop_name(e)))


def _count(entry: Mapping[str, object], field: str) -> int:
    value = entry.get(field)
    return value if isinstance(value, int) else 0


def _kept(entry: Mapping[str, object]) -> int:
    """Aufgehoben minus zerlegt minus verkauft."""
    return _count(entry, 'Picked') - _count(entry, 'Salvaged') - _count(entry, 'Sold')


def _left(entry: Mapping[str, object]) -> int:
    return _count(entry, 'Seen') - _count(entry, 'Picked')


def _drop_name(entry: Mapping[str, object]) -> str:
    return str(entry.get('Name') or f'Model {entry.get("ModelID")}')


def _unknown_name(entry: Mapping[str, object]) -> str:
    names = entry.get('Names')
    return str(names.get('German')) if isinstance(names, dict) and names.get('German') else ''


_confirm_view: dict[str, bool] = {}  # offene Rueckfragen von _draw_clear


def _push_rarity_color(entry: Mapping[str, object]) -> bool:
    """Textfarbe der Zeile nach Seltenheit; True, wenn danach pop_style_color noetig ist."""
    color = rarity_color(entry.get('Rarity'))
    if color is None:
        return False
    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, color)
    return True


def _type_name(item_type: object) -> str:
    """Englischer Typ (Enum-Name) fuer die Anzeige; gespeichert ist die Zahl (Drops) oder der Enum-Name (Unbekannt)."""
    if isinstance(item_type, int):
        try:
            return ItemType(item_type).name.replace('_', ' ')
        except ValueError:
            return str(item_type)
    return str(item_type).replace('_', ' ')


def _rarity_name(rarity: object) -> str:
    """Englische Seltenheit (White, Blue, ...) fuer die Anzeige; Altwerte auf Deutsch werden umgesetzt."""
    code = rarity_code(rarity)
    return str(rarity) if code is None else Rarity(code).name


def _draw_drop_table(rows: list[UnknownEntry], table_id: str, count_title: str, count: Callable[[UnknownEntry], int],
                     empty: str, rules: LootRules | None = None,
                     value_of: Callable[[UnknownEntry], object] = lambda e: e.get('Value')) -> None:
    """Tabelle wie Unbekannt: Item, Model-ID, Typ, Seltenheit, Wert, Anzahl (Gesehen steht im Tooltip).

    Mit rules vorn ein Haken Aufheben, der dieselbe Regel setzt wie der Katalog.
    """
    if not rows:
        PyImGui.text_disabled(empty)
        return
    titles = ('Item', 'Model-ID', 'Typ', 'Seltenheit', 'Wert', count_title)
    if rules is not None:
        titles = ('Aufheben', *titles)
    if not PyImGui.begin_table(table_id, len(titles), _TABLE_FLAGS):
        return
    if rules is not None:
        _catalog_items()  # nach Aenderung an items.json ist der Katalog bis zum naechsten Zugriff leer
    for title in titles:
        PyImGui.table_setup_column(title)
    PyImGui.table_headers_row()
    for index, e in enumerate(rows):
        PyImGui.table_next_row()
        # Eigener ID-Bereich je Zeile: zwei Drops koennen zum selben Katalog-Eintrag gehoeren (AlsoModelIDs).
        PyImGui.push_id_int(index)
        colored = _push_rarity_color(e)
        if rules is not None:
            PyImGui.table_next_column()
            _draw_catalog_checkbox(rules, e)
        PyImGui.table_next_column()
        PyImGui.text(_drop_name(e))
        if PyImGui.is_item_hovered():
            maps = e.get('Maps')
            lines = [f'Gesehen: {e.get("Seen")}x, zuletzt {e.get("LastSeen")}']
            if isinstance(maps, list) and maps:
                lines.append('Gesehen in ' + ', '.join(str(m) for m in maps))
            PyImGui.set_tooltip('\n'.join(lines))
        for value in (e.get('ModelID'), _type_name(e.get('ItemType')), _rarity_name(e.get('Rarity')),
                      value_of(e), count(e)):
            PyImGui.table_next_column()
            PyImGui.text(str(value))
        if colored:
            PyImGui.pop_style_color()
        PyImGui.pop_id()
    PyImGui.end_table()


def _draw_catalog_checkbox(rules: LootRules, entry: Mapping[str, object]) -> None:
    """Haken Aufheben fuer eine Drop-Zeile; ohne gemerkten Katalog-Eintrag (beim Sehen noch unbekannt, inzwischen in
    items.json) ueber die Model-ID. Die ID kommt aus dem push_id der Zeile."""
    item = (_catalog_by_key.get(str(entry.get('CatalogKey') or ''))
            or _catalog_by_key.get(model_key(_count(entry, 'ModelID'))))
    if item is None:
        PyImGui.align_text_to_frame_padding()  # gleiche Zeilenhoehe wie mit Haken
        PyImGui.text_disabled('-')
        return
    was_picked = rules.action(item.key) == PICK
    picked = PyImGui.checkbox('##pick', was_picked)
    if picked != was_picked:
        _set_pick(rules, item, picked)


def _draw_clear(label: str, button_id: str, on_clear: Callable[[], None], question: str = 'Wirklich leeren?') -> None:
    """Knopf mit Rueckfrage; die Rueckfrage haengt an button_id."""
    pending_key = f'clear_{button_id}'
    if not _confirm_view.get(pending_key):
        if PyImGui.button(f'{label}##{button_id}'):
            _confirm_view[pending_key] = True
        return
    PyImGui.text_colored(question, _COLOR_IGNORE)
    PyImGui.same_line(0, 8)
    if PyImGui.button(f'JA##{button_id}_yes'):
        on_clear()
        _confirm_view[pending_key] = False
    PyImGui.same_line(0, 8)
    if PyImGui.button(f'ABBRECHEN##{button_id}_no'):
        _confirm_view[pending_key] = False


def _draw_drops(rules: LootRules, drops: DropLog, id_prefix: str) -> None:
    """Reiter Drops: aufgehoben, bekannt aber liegen gelassen (unbekannte traegt der Bot gleich in items.json ein)."""
    open_flag = int(PyImGui.TreeNodeFlags.DefaultOpen)
    picked = drops.picked_rows()
    if PyImGui.collapsing_header(f'Aufgehoben ({len(picked)})###{id_prefix}_drops_picked', open_flag):
        _draw_drop_table(picked, f'##{id_prefix}_drops_picked_table', 'Aufgehoben',
                         _kept, 'Noch nichts aufgehoben.',
                         value_of=lambda e: e.get('GoldShare', e.get('Value')))  # Gold: eigener Anteil, summiert
    left = drops.left_rows()
    if PyImGui.collapsing_header(f'Bekannt, nicht aufgehoben ({len(left)})###{id_prefix}_drops_left', open_flag):
        _draw_drop_table(left, f'##{id_prefix}_drops_left_table', 'Liegen gelassen', _left,
                         'Nichts Bekanntes liegen gelassen.', rules)
    _draw_clear('DROPS LEEREN', f'{id_prefix}_drops_clear', drops.clear)


def draw_rules_tab(rules: LootRules, id_prefix: str = 'loot', log_source: str = 'shared_data',
                   drops: DropLog | None = None,
                   merchant: LootRules | None = None, salvage: LootRules | None = None,
                   identify: LootRules | None = None) -> None:
    """Inhalt des Reiters Items: Loot (Katalog anhaken), Item-Info (Loot-Auswahl, dazu Spalten fuer die
    uebergebenen Regeln Verkaufen/Zerlegen/Identifizieren) und, wenn uebergeben, Merchant/Salvage und Drops.
    Kein eigenes Fenster."""
    PyImGui.spacing()
    if not PyImGui.begin_tab_bar(f'##{id_prefix}_tabs'):
        return
    if PyImGui.begin_tab_item(f'Loot##{id_prefix}_catalog'):
        PyImGui.text_wrapped('Haken = aufheben. Ohne Haken wird nichts aufgehoben.')
        _draw_catalog(rules, id_prefix, log_source)
        PyImGui.end_tab_item()
    if PyImGui.begin_tab_item(f'Item-Info##{id_prefix}_selected'):
        _draw_selected(rules, id_prefix, merchant, salvage, identify)
        PyImGui.end_tab_item()
    if merchant is not None and PyImGui.begin_tab_item(f'Merchant##{id_prefix}_merchant'):
        _draw_action_list(merchant, rules, f'{id_prefix}_merchant', log_source, salvage=False)
        PyImGui.end_tab_item()
    if salvage is not None and PyImGui.begin_tab_item(f'Salvage##{id_prefix}_salvage'):
        _draw_action_list(salvage, rules, f'{id_prefix}_salvage', log_source, salvage=True)
        PyImGui.end_tab_item()
    if drops is not None and PyImGui.begin_tab_item(f'Drops##{id_prefix}_drops'):
        _draw_drops(rules, drops, id_prefix)
        PyImGui.end_tab_item()
    PyImGui.end_tab_bar()
