from dataclasses import dataclass, field
import math
from cabinet import load_cabinet
from crates import CrateProgress, load_crates

MATERIALS = ("metal", "resin", "chips")

@dataclass(frozen=True)
class Recipe:
    key: str
    name: str
    cost: tuple
    description: str
    clinic: int = 0

RECIPES = (
    Recipe("mirror", "Precision mirror", (8, 2, 0), "+25% cash per manual treatment."),
    Recipe("organizer", "Instrument organizer", (12, 4, 0), "+15% passive staff income."),
    Recipe("handpiece", "Sonic handpiece", (20, 8, 2), "+1 case step per treatment.", 1),
    Recipe("lamp", "Focus lamp", (16, 6, 3), "Focus lasts 25s instead of 15s.", 1),
    Recipe("liner", "Cabinet liner", (25, 10, 5), "Protects against one spoiled package per cabinet.", 1),
    Recipe("badge", "Masterwork badge", (40, 20, 10), "+10% to all earnings.", 2),
)
RECIPE_KEYS = {recipe.key for recipe in RECIPES}

@dataclass
class Activities(CrateProgress):
    materials: dict = field(default_factory=lambda: {key: 0 for key in MATERIALS})
    crafted: list = field(default_factory=list)
    focus_left: float = 0
    focus_wait: float = 0
    focus_uses: int = 0

    @property
    def focus_multiplier(self):
        return 3 if self.focus_left > 0 else 1

    def activate_focus(self):
        if self.manual < 10:
            return "FOCUS LOCKED: complete 10 manual treatments first."
        if self.focus_wait > 0:
            return f"Focus recharges in {math.ceil(self.focus_wait)}s of active play."
        self.focus_left = 25 if "lamp" in self.crafted else 15
        self.focus_wait = 90
        self.focus_uses += 1
        return f"FOCUS: 3x treatment cash and +1 case step for {self.focus_left}s!"

    def tick_activities(self, seconds):
        self.focus_left = max(0, self.focus_left - seconds)
        self.focus_wait = max(0, self.focus_wait - seconds)

    def collect_supplies(self, completed_case=None):
        if self.manual % 5 == 0:
            self.materials["metal"] += 1
        if completed_case is not None:
            self.materials["resin"] += 2
            if self.cases_completed % 3 == 0:
                self.supply_keys += 1
            if completed_case.clinic >= 1:
                self.materials["chips"] += 1

    def craft_reason(self, index):
        recipe = RECIPES[index]
        if recipe.key in self.crafted:
            return "ALREADY BUILT - this equipment is permanent."
        if self.manual < 10:
            return "WORKSHOP LOCKED: complete 10 manual treatments."
        if max(self.best_clinic, self.clinic) < recipe.clinic:
            return f"LOCKED: reach clinic level {recipe.clinic} in any run."
        missing = [f"{cost - self.materials[key]} {key}"
                   for key, cost in zip(MATERIALS, recipe.cost) if self.materials[key] < cost]
        return "NEED: " + ", ".join(missing) if missing else ""

    def craft(self, index):
        if type(index) is not int or not 0 <= index < len(RECIPES):
            return "Unknown workshop recipe."
        reason = self.craft_reason(index)
        if reason:
            return reason
        recipe = RECIPES[index]
        for key, cost in zip(MATERIALS, recipe.cost):
            self.materials[key] -= cost
        self.crafted.append(recipe.key)
        return f"BUILT: {recipe.name}. {recipe.description} Kept after prestige."

def load_activities(state, data, number):
    materials = data.get("materials", {})
    if not isinstance(materials, dict):
        raise ValueError("Invalid workshop materials")
    state.materials = {key: number(materials, key, integer=True, maximum=10**16)
                       for key in MATERIALS}
    crafted = data.get("crafted", [])
    if (not isinstance(crafted, list)
            or any(not isinstance(key, str) or key not in RECIPE_KEYS for key in crafted)):
        raise ValueError("Invalid workshop equipment")
    state.crafted = list(dict.fromkeys(crafted))
    state.focus_left = number(data, "focus_left", maximum=25 if "lamp" in state.crafted else 15)
    state.focus_wait = number(data, "focus_wait", maximum=90)
    state.focus_uses = number(data, "focus_uses", integer=True, maximum=10**15)
    if state.focus_left > state.focus_wait:
        raise ValueError("Focus duration exceeds recharge time")

    load_cabinet(state, data, number)
    load_crates(state, data, number)