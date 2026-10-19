from collections import Counter
from dataclasses import dataclass, field
import math
import random

DRAWERS = ("metal", "metal", "metal", "resin", "resin", "chips", "cash", "spoiled", "spoiled")
PRIZES = {"metal": 4, "resin": 3, "chips": 1}

@dataclass
class CabinetProgress:
    supply_keys: int = 0
    hunts_played: int = 0
    cabinet: dict = field(default_factory=dict)

    @property
    def cabinet_active(self):
        return bool(self.cabinet) and self.cabinet["status"] == "active"

    def start_cabinet(self, rng=None):
        if self.cabinet_active:
            return "Finish the current cabinet first."
        if self.supply_keys < 1:
            return "NEED A KEY: every 3 completed patient cases gives one."
        layout = list(DRAWERS)
        (rng or random.Random()).shuffle(layout)
        self.supply_keys -= 1
        self.hunts_played += 1
        self.cabinet = {"layout": layout, "opened": [],
                        "shields": int("liner" in self.crafted),
                        "cash": math.ceil(max(25, self.click_value * 10, self.income * 5)),
                        "status": "active"}
        return "CABINET OPEN: choose a drawer. Revealed prizes are yours to keep."

    def reveal_drawer(self, index):
        if not self.cabinet_active:
            return "Press ENTER to open a new cabinet."
        if type(index) is not int or not 0 <= index < len(DRAWERS):
            return "Choose a drawer from 1 to 9."
        board = self.cabinet
        if index in board["opened"]:
            return "That drawer is already open. Choose another."
        board["opened"].append(index)
        item = board["layout"][index]
        if item == "spoiled":
            if board["shields"]:
                board["shields"] -= 1
                message = "SPOILED PACKAGE.... but your cabinet liner protected this search!"
            else:
                board["status"] = "spoiled"
                return "SPOILED PACKAGE: search ended. You keep every prize already found."
        elif item == "cash":
            self.money += board["cash"]
            message = f"FOUND: ${board['cash']:,.0f} cash grant."
        else:
            self.materials[item] += PRIZES[item]
            message = f"FOUND: +{PRIZES[item]} {item}."
        if all(i in board["opened"] for i, value in enumerate(board["layout"]) if value != "spoiled"):
            board["status"] = "cleared"
            message += " PERFECT SEARCH: all seven prizes found!"
        return message

    def stop_cabinet(self):
        if not self.cabinet_active:
            return "No active cabinet to close."
        self.cabinet["status"] = "stopped"
        return "Cabinet closed. Your prizes are kept."

def load_cabinet(state, data, number):
    state.supply_keys = number(data, "supply_keys", integer=True, maximum=10**15)
    state.hunts_played = number(data, "hunts_played", integer=True, maximum=10**15)
    board = data.get("cabinet", {})
    if not isinstance(board, dict):
        raise ValueError("Invalid supply cabinet")
    if not board:
        return
    layout, opened = board.get("layout"), board.get("opened")
    if (not isinstance(layout, list) or any(not isinstance(item, str) for item in layout)
            or Counter(layout) != Counter(DRAWERS)):
        raise ValueError("Invalid cabinet layout")
    if (not isinstance(opened, list)
            or any(type(i) is not int or not 0 <= i < 9 for i in opened)
            or len(set(opened)) != len(opened)):
        raise ValueError("Invalid opened drawers")
    status = board.get("status")
    if status not in ("active", "spoiled", "cleared", "stopped"):
        raise ValueError("Invalid cabinet status")
    shields = number(board, "shields", integer=True, maximum=1)
    cash = number(board, "cash")
    complete = all(i in opened for i, item in enumerate(layout) if item != "spoiled")
    if ((status == "cleared") != complete
            or (status == "spoiled" and (not opened or layout[opened[-1]] != "spoiled" or shields))
            or (status == "active" and sum(layout[i] == "spoiled" for i in opened) + shields > 1)):
        raise ValueError("Inconsistent cabinet progress")
    state.cabinet = {"layout": list(layout), "opened": list(opened), "status": status,
                     "shields": shields, "cash": cash}