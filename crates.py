from dataclasses import dataclass, field
import random
from cabinet import CabinetProgress
from cosmetics import get_cosmetic, roll_cosmetic, valid_item_key

@dataclass
class CrateProgress(CabinetProgress):
    supply_crates: int = 0
    crate_keys: int = 0
    crates_opened: int = 0
    cosmetics: dict = field(default_factory=dict)
    showcase: str = ""
    pending_crate: dict = field(default_factory=dict)

    def roll_crate_drop(self, rng=None):
        rng = rng if rng is not None else random
        roll = rng.randrange(40)
        if roll == 0:
            self.supply_crates += 1
            return "Supply crate"
        if roll == 1:
            self.crate_keys += 1
            return "Crate key"
        return ""

    def begin_crate(self, rng=None):
        if self.pending_crate or self.supply_crates < 1 or self.crate_keys < 1:
            return False
        rng = rng if rng is not None else random
        item = roll_cosmetic(rng)
        if item is None:
            return False
        duplicate = item.key in self.cosmetics
        self.supply_crates -= 1
        self.crate_keys -= 1
        self.crates_opened += 1
        self.cosmetics[item.key] = self.cosmetics.get(item.key, 0) + 1
        self.pending_crate = {"item": item.key, "duplicate": duplicate,
                              "reel_seed": rng.randrange(2**32)}
        return True

    def set_showcase(self, key):
        if key not in self.cosmetics:
            return "Find this cosmetic in a supply crate first."
        self.showcase = "" if self.showcase == key else key
        return ("Showcase cleared." if not self.showcase else
                "ON DISPLAY: " + get_cosmetic(key).name + ". Cosmetic only.")

def load_crates(state, data, number):
    for name in ("supply_crates", "crate_keys", "crates_opened"):
        setattr(state, name, number(data, name, integer=True, maximum=10**15))
    owned = data.get("cosmetics", {})
    if not isinstance(owned, dict) or any(not valid_item_key(key) for key in owned):
        raise ValueError("Invalid cosmetic collection")
    state.cosmetics = {}
    for key in owned:
        count = number(owned, key, integer=True, maximum=10**15)
        if count < 1:
            raise ValueError("Invalid cosmetic count")
        state.cosmetics[key] = count
    if sum(state.cosmetics.values()) != state.crates_opened:
        raise ValueError("Cosmetic counts do not match opened crates")
    showcase = data.get("showcase", "")
    if not isinstance(showcase, str) or (showcase and showcase not in state.cosmetics):
        raise ValueError("Invalid showcase item")
    state.showcase = showcase
    pending = data.get("pending_crate", {})
    if not isinstance(pending, dict):
        raise ValueError("Invalid pending crate")
    state.pending_crate = {}
    if pending:
        key = pending.get("item")
        if (not isinstance(key, str) or key not in state.cosmetics
                or type(pending.get("duplicate")) is not bool
                or pending["duplicate"] != (state.cosmetics[key] > 1)
                or "reel_seed" not in pending):
            raise ValueError("Invalid pending cosmetic reward")
        seed = number(pending, "reel_seed", integer=True, maximum=2**32 - 1)
        state.pending_crate = {"item": key, "duplicate": pending["duplicate"],
                               "reel_seed": seed}