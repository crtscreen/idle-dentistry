from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import random
import re

CATALOGUE_PATH = Path(__file__).resolve().parent / "data" / "cosmetics.json"
RARITIES = ("Common", "Uncommon", "Rare", "Epic", "Legendary")
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
RETIRED_ART = (" .--------. ", " | STORED | ", " |________| ", " '--------' ")

@dataclass(frozen=True)
class Cosmetic:
    key: str
    name: str
    rarity: str
    description: str
    art: tuple
    enabled: bool = True

class CatalogueError(ValueError):
    pass

def valid_item_key(key):
    return isinstance(key, str) and KEY_PATTERN.fullmatch(key) is not None

def _text(value, field, maximum):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(not " " <= char <= "~" for char in value)):
        raise CatalogueError(f"{field}: use 1-{maximum} printable ASCII characters.")
    return value

def load_catalogue(path=CATALOGUE_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise CatalogueError(f"Cannot read {path}: {error}") from error
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise CatalogueError("The catalogue must be an object with version 1.")
    weights = data.get("rarity_weights")
    if (not isinstance(weights, dict) or set(weights) != set(RARITIES)
            or any(type(w) is not int or not 0 <= w <= 10000 for w in weights.values())
            or not sum(weights.values())):
        raise CatalogueError("rarity_weights needs all five rarities and nonnegative integer weights.")
    rows = data.get("items")
    if not isinstance(rows, list):
        raise CatalogueError("items must be a list of cosmetic objects.")
    items, seen = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise CatalogueError(f"Item {index}: expected an object.")
        key = row.get("key")
        if not valid_item_key(key) or key in seen:
            raise CatalogueError(f"Item {index}: key must be unique, lowercase, and use letters/digits/underscores.")
        seen.add(key)
        rarity = row.get("rarity")
        if rarity not in RARITIES:
            raise CatalogueError(f"{key}: unknown rarity {rarity!r}.")
        enabled = row.get("enabled", True)
        if type(enabled) is not bool:
            raise CatalogueError(f"{key}: enabled must be true or false.")
        art = row.get("art")
        if (not isinstance(art, list) or not 1 <= len(art) <= 4
                or any(not isinstance(line, str) or len(line) > 14
                       or any(not " " <= char <= "~" for char in line) for line in art)
                or not any(line.strip() for line in art)):
            raise CatalogueError(f"{key}: art needs 1-4 ASCII lines, each at most 14 columns.")
        items.append(Cosmetic(key, _text(row.get("name"), f"{key}.name", 48), rarity,
                              _text(row.get("description"), f"{key}.description", 200),
                              tuple(line.rstrip() for line in art), enabled))
    return tuple(items), {rarity: weights[rarity] for rarity in RARITIES}

ITEMS, RARITY_WEIGHTS = load_catalogue()
ITEM_BY_KEY = {item.key: item for item in ITEMS}
ACTIVE_ITEMS = tuple(item for item in ITEMS if item.enabled)
BY_RARITY = {rarity: tuple(i for i in ACTIVE_ITEMS if i.rarity == rarity) for rarity in RARITIES}
DROP_POOLS = tuple((RARITY_WEIGHTS[r], BY_RARITY[r]) for r in RARITIES
                   if RARITY_WEIGHTS[r] and BY_RARITY[r])
TOTAL_WEIGHT = sum(weight for weight, _ in DROP_POOLS)
RARITY_ODDS = {r: (100 * RARITY_WEIGHTS[r] / TOTAL_WEIGHT if BY_RARITY[r] and TOTAL_WEIGHT else 0)
               for r in RARITIES}

@lru_cache(maxsize=256)
def get_cosmetic(key):
    if key in ITEM_BY_KEY:
        return ITEM_BY_KEY[key]
    return Cosmetic(key, "Retired item", "Retired",
                    "Removed from the catalogue. Your copies are kept. Restoring its key restores the item.",
                    RETIRED_ART, False)

def roll_cosmetic(rng=None):
    if not TOTAL_WEIGHT:
        return None
    rng = rng if rng is not None else random
    roll = rng.randrange(TOTAL_WEIGHT)
    for weight, items in DROP_POOLS:
        if roll < weight:
            return rng.choice(items)
        roll -= weight

def inventory_items(owned, mode="All", rarity="All"):
    catalogue = ACTIVE_ITEMS + tuple(get_cosmetic(key) for key in owned
                                    if key not in ITEM_BY_KEY or not ITEM_BY_KEY[key].enabled)
    return [item for item in catalogue
            if (rarity == "All" or item.rarity == rarity or (rarity == "Retired" and not item.enabled))
            and (mode == "All" or (item.key in owned) == (mode == "Owned"))]

def collection_count(owned):
    return sum(item.key in owned for item in ACTIVE_ITEMS)

def rarity_summary():
    return " | ".join(f"{rarity} {chance:.2f}%".replace(".00%", "%")
                      for rarity, chance in RARITY_ODDS.items())