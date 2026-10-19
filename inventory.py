import math
import random
import time
import textwrap
from cosmetics import (ACTIVE_ITEMS, RARITY_ODDS, TOTAL_WEIGHT, collection_count,
                       get_cosmetic, inventory_items, roll_cosmetic)

WINNER_INDEX = 30
CARD_WIDTH = 22
REEL_SECONDS = 4.5


def make_reel(pending):
    rng = random.Random(pending["reel_seed"])
    reel = [(roll_cosmetic(rng) or get_cosmetic(pending["item"])) for _ in range(WINNER_INDEX + 5)]
    reel[WINNER_INDEX] = get_cosmetic(pending["item"])
    return reel

def reel_position(elapsed, seconds=REEL_SECONDS):
    progress = 1 if seconds <= 0 else max(0, min(1, elapsed / seconds))
    return WINNER_INDEX * (1 - (1 - progress) ** 3)


def card_lines(item):
    inner = CARD_WIDTH - 2
    border = "+" + "-" * inner + "+"
    return (border, "|" + item.name[:inner].center(inner) + "|",
            "|" + item.rarity.center(inner) + "|", border)


class InventoryUI:
    def draw_cosmetic(self, item, y, x, width=14, height=4):
        art_width = max(map(len, item.art))
        left = x + max(0, (width - art_width) // 2)
        for row, line in enumerate(item.art[:height]):
            self.put(y + row, left, line, item.rarity, limit=width)

    def init_inventory(self):
        self.inventory_mode = "All"
        self.inventory_rarity = "All"
        self.crate_reel = None

    def filtered_items(self):
        return inventory_items(self.state.cosmetics, self.inventory_mode, self.inventory_rarity)

    def inventory_page(self, height, width):
        s = self.state
        self.put(5, 2, f"INVENTORY | Collection {collection_count(s.cosmetics)}/{len(ACTIVE_ITEMS)}", "accent", True)
        self.put(6, 2, f"Supply crates: {s.supply_crates} | Crate keys: {s.crate_keys} | / OPEN", "gold")
        self.put(7, 2, f"[ ownership: {self.inventory_mode} | ] rarity: {self.inventory_rarity}", "muted")
        items = self.filtered_items()
        visible = max(1, height - 18)
        if items:
            self.selected %= len(items)
            preview = items[self.selected]
            self.draw_cosmetic(preview, 8, width - 17)
            start = max(0, self.selected - visible + 1)
            for row, index in enumerate(range(start, min(len(items), start + visible))):
                item = items[index]
                count = s.cosmetics.get(item.key, 0)
                mark = "*" if item.key == s.showcase else " "
                label = f"x{count}" if count else "---"
                self.put(8 + row, 2, f"{mark}{label:>4} {item.rarity:<9} {item.name}",
                         item.rarity if count else "muted", reverse=index == self.selected,
                         limit=width - 21)
            item = items[self.selected]
            retired = " (retired)" if not item.enabled else ""
            self.put(height - 9, 2, f"{self.selected + 1}/{len(items)}  {item.name}{retired}", item.rarity, True)
            for row, line in enumerate(textwrap.wrap(item.description, width - 4)[:2]):
                self.put(height - 8 + row, 2, line, "muted")
        else:
            self.selected = 0
            self.put(9, 2, "No items match. [ or ] changes the filters.", "muted")
            self.put(height - 8, 2, "Treat patients to find crates and matching keys.", "accent")
        self.put(height - 6, 2, "Up/Down browse | PgUp/PgDn jump | ENTER showcase", "accent")
        self.put(height - 5, 2, "5% per manual treatment: crate OR key (50/50).", "muted")
        self.put(height - 4, 2, "Cosmetics only. Duplicates stack. Kept after prestige.", "muted")

    def inventory_input(self, key):
        if key in (ord('['), ord(']')):
            if key == ord('['):
                choices = ("All", "Owned", "Missing")
                self.inventory_mode = choices[(choices.index(self.inventory_mode) + 1) % len(choices)]
            else:
                choices = ("All", *RARITY_ODDS, "Retired")
                self.inventory_rarity = choices[(choices.index(self.inventory_rarity) + 1) % len(choices)]
            self.selected = 0
        elif key in ("down", "up", "pagedown", "pageup"):
            items = self.filtered_items()
            step = 8 if key in ("pagedown", "pageup") else 1
            direction = 1 if key in ("down", "pagedown") else -1
            self.selected = (self.selected + step * direction) % max(1, len(items))
        elif key == ord('/'):
            if self.session.paused:
                self.session.say(f"Resume with {self.key('pause')} before opening a crate.")
            else:
                self.open_modal("crate")
        elif key in (10, 13):
            items = self.filtered_items()
            if items:
                self.session.say(self.state.set_showcase(items[self.selected % len(items)].key))
                self.save()

    def start_crate_opening(self):
        s = self.state
        if not TOTAL_WEIGHT:
            self.session.say("No cosmetics are available in crates right now.")
            return
        before = (s.supply_crates, s.crate_keys, s.crates_opened,
                  dict(s.cosmetics), dict(s.pending_crate))
        if not s.begin_crate():
            self.session.say("Opening needs 1 supply crate AND 1 crate key.")
            return
        if not self.save():
            (s.supply_crates, s.crate_keys, s.crates_opened,
             s.cosmetics, s.pending_crate) = before
            self.session.say("Opening cancelled: save failed. Crate and key kept.")
            return
        self.update_crate_reveal()

    def update_crate_reveal(self):
        if self.state.pending_crate and not self.modal and self.crate_reel is None:
            self.change_view("inventory")
            items = make_reel(self.state.pending_crate)
            self.crate_reel = {"items": items, "cards": tuple(card_lines(item) for item in items),
                               "started": time.monotonic(),
                               "seconds": 0 if self.settings.reduced_animation else REEL_SECONDS}
            self.gate.legacy_armed = False
            self.mouse_area = None

    def crate_elapsed(self):
        return max(0, time.monotonic() - self.crate_reel["started"])

    def crate_ready(self):
        return self.crate_elapsed() >= self.crate_reel["seconds"]

    def crate_input(self, key):
        if key not in (10, 13, 27):
            return
        if not self.crate_ready():
            self.crate_reel["seconds"] = 0
            return
        pending = self.state.pending_crate
        self.state.pending_crate = {}
        if not self.save():
            self.state.pending_crate = pending
            return
        self.crate_reel = None
        self.inventory_mode, self.inventory_rarity = "Owned", "All"
        self.selected = next(i for i, item in enumerate(self.filtered_items())
                             if item.key == pending["item"])
        self.session.say("COLLECTED: " + get_cosmetic(pending["item"]).name + ". Press ENTER to display it.")

    def crate_overlay(self, height, width):
        self.put(5, 2, "SUPPLY CRATE | COLLECTION", "accent", True)
        self.put(6, 2, "Reward saved.", "muted")
        center = width // 2
        self.put(8, center, "v", "gold", True)
        position = reel_position(self.crate_elapsed(), self.crate_reel["seconds"])
        radius = math.ceil(width / (2 * CARD_WIDTH)) + 1
        first = max(0, int(position) - radius)
        last = min(len(self.crate_reel["items"]), int(position) + radius + 2)
        for index in range(first, last):
            item = self.crate_reel["items"][index]
            x = center + math.floor((index - position) * CARD_WIDTH) - CARD_WIDTH // 2
            for row, line in enumerate(self.crate_reel["cards"][index]):
                left, right = max(2, x), min(width - 2, x + CARD_WIDTH)
                if right > left:
                    self.put(9 + row, left, line[left - x:right - x], item.rarity)
        self.put(13, center, "^", "gold", True)
        if self.crate_ready():
            pending = self.state.pending_crate
            item = get_cosmetic(pending["item"])
            label = "DUPLICATE" if pending["duplicate"] else "NEW ITEM"
            count = self.state.cosmetics[item.key]
            self.put(15, 2, f"{label}: {item.name}", item.rarity, True)
            self.put(16, 2, f"{item.rarity} | Owned: {count}", item.rarity)
            self.put(17, 2, "ENTER / ESC: return to Inventory", "accent")
            if height >= 25:
                self.put(19, 2, item.description, "muted")
        else:
            self.put(15, 2, "unpacking supply crate...", "muted")
            self.put(17, 2, "ENTER / ESC: skip animation", "accent")