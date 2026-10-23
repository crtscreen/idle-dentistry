import curses
import math
import os
import time
import textwrap
import shutdown

from game import (ACHIEVEMENTS, CLINICS, STAFF, UPGRADES, SKILLS,
                  PRESTIGE_AT, Session, save_game)
from terminal_input import TerminalInput, PressGate
from content import CONTRACTS, CASES, PATIENTS
from settings import Settings
from activities import MATERIALS, RECIPES
from cabinet import PRIZES
from cosmetics import ACTIVE_ITEMS, collection_count, get_cosmetic, rarity_summary
from inventory import InventoryUI
from menus import colours
from navigation import TABS, TAB_KEYS, TAB_BY_KEY

def cash(value):
    for size, suffix in ((1e15, "q"), (1e12, "t"), (1e9, "b"), (1e6, "m")):
        if value >= size:
            return f"${value / size:,.2f}{suffix}"
    return f"${value:,.0f}" if value >= 1000 else f"${value:,.2f}"

def duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m {seconds % 60:02d}s"

class UI(InventoryUI):
    def __init__(self, screen, state, path, messages=(), colour=True, settings=None, safe_input=False):
        self.settings = settings or Settings()
        self.safe_input = safe_input
        self.outcome = "quit"
        self.welcome = list(messages)
        self.screen = screen
        self.state = state
        self.path = path
        self.session = Session(state)
        for message in messages:
            self.session.say(message)
        self.view = "clinic"
        self.gate = PressGate()
        self.reader = None
        self.mouse_down = False
        self.input_notice = False
        self.selected = 0
        self.quantity = 1
        self.achievement_filter = "all"
        self.scroll = 0
        self.modal = None
        self.restore_pause = False
        self.last_treat = -10
        self.last_save = time.monotonic()
        self.save_ok = True
        self.mouse_area = None
        self.init_inventory()
        screen.timeout(50)
        screen.keypad(False)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.attrs = colours(self.settings.theme, colour)
        if self.welcome:
            self.open_modal("welcome")
        elif self.state.tutorial_status == "pending":
            self.open_modal("tutorial")

    def key(self, action):
        return self.settings.label(action)

    def put(self, y, x, text, colour="text", bold=False, limit=None, reverse=False):
        height, width = self.screen.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= width - 1:
            return
        attr = self.attrs[colour] | (curses.A_BOLD if bold else 0)
        if reverse:
            attr |= curses.A_REVERSE
        room = max(0, width - x - 1)
        if limit is not None:
            room = min(room, max(0, limit))
        try:
            self.screen.addnstr(y, x, str(text), room, attr)
        except curses.error:
            pass

    def line(self, y, x, width, colour="muted"):
        self.put(y, x, "-" * max(0, width), colour)

    def bar(self, y, x, width, ratio):
        filled = int(max(0, min(1, ratio)) * width)
        self.put(y, x, "#" * filled + "." * (width - filled), "good")

    def room(self, y, x, width, rows):
        state = self.state
        item = get_cosmetic(state.showcase) if state.showcase else None
        room_width = width - 17 if item else width
        self.put(y, x, CLINICS[state.clinic][0].upper(), "accent", True)
        clock = (time.strftime("%H:%M:%S") if self.settings.clock == "real" else
                 duration(state.play_seconds) if self.settings.clock == "elapsed" else "")
        if clock:
            self.put(y, x + max(0, width - len(clock)), clock, "muted")
        self.line(y + 1, x, room_width)
        rooms = ("[CHAIR]  [broom]", "[CHAIR] [CHAIR]  [RECEPTION]",
                 "[ROOM 1] [ROOM 2]  [X-RAY]",
                 "[WARD A] [WARD B] [LAB] [RECEPTION]",
                 "[WING A] [WING B] [ROBOT LAB] [SKY LOUNGE]")
        self.put(y + 2, x, rooms[state.clinic], "muted", limit=room_width)
        decorations = {"plant": "{plant}", "aquarium": "[><> tank]",
                       "diploma": "[diploma]", "trophy": "[TROPHY]"}
        decor = "  ".join(decorations[key] for key in state.decorations)
        self.put(y + 3, x, decor or "Waiting room: one wobbly magazine.", "good", limit=room_width)
        if rows >= 7:
            active = not self.settings.reduced_animation and self.session.clock - self.last_treat < .3
            blink = "o" if self.settings.reduced_animation or int(self.session.clock) % 4 else "O"
            patients = " ".join(f"{blink} |_|" for _ in range(state.clinic + 1))
            self.put(y + 4, x, " * scrub scrub polish scrub *" if active else patients,
                     "gold", limit=room_width)
            self.put(y + 5, x, "_" * width, "muted")
        if item:
            self.draw_cosmetic(item, y + 1, x + width - 14)

    @property
    def enhanced_input(self):
        return not self.safe_input and self.reader is not None and self.reader.decoder.enhanced

    def treatment_hint(self):
        key = self.key("treat")
        if self.enhanced_input:
            return f"[ {key} / CLICK: TREAT ]"
        if self.gate.legacy_armed:
            return "[ ENTER: FINISH TREATMENT ]"
        return f"[ {key}, THEN ENTER / CLICK ]"

    def clinic(self, height, width):
        s = self.state
        large = height >= 27
        self.room(5, 2, min(width - 4, 64), 7 if large else 4)
        y = 12 if large else 10
        p = s.patient
        self.put(y, 2, f"{p.face} {p.name}: {p.complaint}", "text")
        self.put(y + 1, 2, self.treatment_hint() + f" +{cash(s.click_value * self.session.bonus * s.focus_multiplier)}", "gold", True)
        self.mouse_area = (2, y + 1, min(width - 4, 54), 1)
        if s.case:
            c = CASES[s.case["index"]]
            line = f"CASE: {c.title} {s.case['progress']}/{c.steps} | +{cash(s.case['reward'])}"
        else:
            line = f"[{self.key('cases')}] Patient cases: complete for rewards."
        self.put(y + 2, 2, line, "good")
        if s.clinic < len(CLINICS) - 1:
            cost = s.expansion_cost()
            self.put(y + 4, 2, f"[{self.key('expand')}] Expand: " + CLINICS[s.clinic + 1][0], "accent")
            increase = 100 * ((1 + .4 * (s.clinic + 1)) / (1 + .4 * s.clinic) - 1)
            self.put(y + 5, 2, f"{cash(s.money)} / {cash(cost)} | +{increase:.1f}% earnings", "muted")
            self.bar(y + 6, 2, min(width - 4, 58), s.money / cost)
        else:
            self.put(y + 4, 2, "THE MOLAR EMPIRE IS COMPLETE", "gold", True)
            self.put(y + 5, 2, f"Keep growing or press {self.key('prestige')} for permanent reputation.", "muted")
        if s.manual < 10:
            focus = f"Focus + Workshop unlock: {s.manual}/10 treatments"
        elif s.focus_left > 0:
            focus = f"FOCUS {math.ceil(s.focus_left)}s | 3x treatment cash | +1 case step"
        elif s.focus_wait > 0:
            focus = f"Focus recharges in {math.ceil(s.focus_wait)}s"
        else:
            focus = f"[{self.key('focus')}] FOCUS READY: 3x cash for {25 if 'lamp' in s.crafted else 15}s"
        self.put(y + 3, 2, focus, "good" if s.focus_left > 0 else "accent")
        if height >= 27:
            ready = sum(c.key not in s.contracts and s.contract_unlocked(c)
                        and s.contract_progress(c) >= c.goal for c in CONTRACTS)
            self.put(y + 7, 2, f"[{self.key('workshop')}] Workshop: craft equipment", "accent")
            self.put(y + 8, 2, f"[{self.key('contracts')}] Contract board: {ready} ready | {len(s.contracts)}/{len(CONTRACTS)} claimed", "accent")

    def cases_page(self, height, width):
        s = self.state
        index = s.case["index"] if s.case else self.selected % len(CASES)
        c = CASES[index]
        self.put(5, 2, f"PATIENT CASES {index + 1}/{len(CASES)} - no deadline", "accent", True)
        self.put(7, 2, c.title, "gold", True)
        patient = PATIENTS[c.patient]
        self.put(8, 2, f"{patient.face} {patient.name}")
        self.put(9, 2, patient.complaint, "muted")
        progress = s.case["progress"] if s.case else 0
        reward = s.case["reward"] if s.case else s.case_quote(index)
        self.put(10, 2, f"Treatment steps: {progress}/{c.steps} | +{s.case_power} per treatment")
        self.put(11, 2, f"Completion reward: {cash(reward)} (fixed when accepted)", "gold")
        self.bar(12, 2, min(width - 4, 50), progress / c.steps)
        if s.case:
            line = f"Return to Clinic ({self.key('clinic')}) and treat to advance the case."
        elif s.clinic < c.clinic:
            line = f"LOCKED: requires {CLINICS[c.clinic][0]}."
        else:
            line = "ENTER: accept | Up/Down: browse available and locked cases"
        self.put(14, 2, line, "accent")
        self.put(16, 2, "Cases require manual treatment.", "muted")
        self.put(17, 2, "Unfinished cases reset on prestige.", "muted")

    def staff_page(self, height, width):
        self.shop(height, width, staff=True)

    def upgrades_page(self, height, width):
        self.shop(height, width, staff=False)

    def shop(self, height, width, staff=True):
        items = STAFF if staff else UPGRADES
        self.selected %= len(items)
        mode = "MAX" if self.quantity == 0 else str(self.quantity)
        self.put(5, 2, "STAFF - everyone earns passive income" if staff else "UPGRADES", "accent", True)
        self.put(6, 2, f"[{self.key('quantity')}] Buy {mode} | Up/Down select | ENTER buy", "muted")
        for i, p in enumerate(items):
            status = "LOCKED" if self.state.run_earned < p.unlock else f"owned {self.state.owned(p)}"
            self.put(8 + i, 2, f"[{i + 1}] {p.name:<18} {status}", reverse=i == self.selected)
        index = self.selected if staff else len(STAFF) + self.selected
        quote = self.state.purchase_preview(index, self.quantity)
        self.put(height - 9, 2, f"Batch: {quote['count']} | Cost: {cash(quote['price'])}", "gold")
        self.put(height - 8, 2, f"Staff: {cash(self.state.income)} -> {cash(quote['income'])}/s")
        self.put(height - 7, 2, f"Treat: {cash(self.state.click_value)} -> {cash(quote['click'])}")
        line = f"Passively earned: {duration(quote['payback'])}" if quote['payback'] is not None else "Passively earned: no passive gain."
        self.put(height - 6, 2, line, "muted")
        self.put(height - 5, 2, quote["reason"] or "READY: ENTER to buy the displayed batch.", "bad" if quote['reason'] else "good")

    def workshop_page(self, height, width):
        s = self.state
        self.selected %= len(RECIPES)
        self.put(5, 2, "WORKSHOP - permanent equipment", "accent", True)
        self.put(6, 2, " | ".join(f"{key.title()}: {s.materials[key]}" for key in MATERIALS), "gold")
        self.put(7, 2, f"Up/Down select | ENTER build | {self.selected + 1}/{len(RECIPES)}", "muted")
        visible = max(1, height - 17)
        start = max(0, self.selected - visible + 1)
        for row, index in enumerate(range(start, min(len(RECIPES), start + visible))):
            recipe = RECIPES[index]
            reason = s.craft_reason(index)
            status = "BUILT" if recipe.key in s.crafted else "LOCK" if "LOCKED" in reason else "NEED" if reason else "READY"
            self.put(8 + row, 2, f"[{status}] {recipe.name}", reverse=index == self.selected)
        recipe = RECIPES[self.selected]
        self.put(height - 8, 2, recipe.description, "accent")
        cost = " + ".join(f"{value} {key}" for key, value in zip(MATERIALS, recipe.cost) if value)
        self.put(height - 7, 2, "Cost: " + cost, "gold")
        self.put(height - 6, 2, s.craft_reason(self.selected) or "ENTER builds | Up/Down selects", "muted")
        self.put(height - 5, 2, "5 treatments: +1 metal | Finished case: +2 resin", "muted")
        self.put(height - 4, 2, "Level 1+ case: +1 chip | All equipment survives prestige", "muted")

    def cabinet_page(self, height, width):
        s = self.state
        self.selected %= 9
        self.put(5, 2, f"SUPPLY CABINET | Keys: {s.supply_keys}", "accent", True)
        self.put(6, 2, "Every 3 finished cases: +1 key. Prizes are kept.", "muted")
        board = s.cabinet
        for index in range(9):
            label = "???"
            if board and index in board["opened"]:
                item = board["layout"][index]
                label = ("SPOILED" if item == "spoiled" else cash(board["cash"]) if item == "cash"
                         else f"{PRIZES[item]} {item}")
            x, y = 2 + (index % 3) * 18, 8 + (index // 3) * 2
            self.put(y, x, f"{index + 1}: {label}", reverse=index == self.selected, limit=16)
        if s.cabinet_active:
            status = f"Shields: {board['shields']} | 2 spoiled packages. 7 prizes"
            control = "Up/Down or 1-9 select | ENTER reveal | / finish"
        else:
            status = ("Last search: " + board["status"] + ". Prizes kept." if board else
                      "A cabinet holds 7 prizes and 2 spoiled packages.")
            control = "ENTER then Y: spend 1 key to open a cabinet"
        self.put(14, 2, status, "gold")
        self.put(15, 2, control, "accent")
        self.put(16, 2, "Spoiled package ends search unless a liner protects it.", "muted")
        self.put(17, 2, "Leave and resume anytime. Layout survives saves/prestige.", "muted")

    def contracts_page(self, height, width):
        self.selected %= len(CONTRACTS)
        self.put(5, 2, "CONTRACTS - permanent, no daily timers", "accent", True)
        self.put(6, 2, "Up/Down select | ENTER claim | / pin goal", "muted")
        visible = max(1, height - 13)
        start = max(0, self.selected - visible + 1)
        for row, i in enumerate(range(start, min(len(CONTRACTS), start + visible))):
            c = CONTRACTS[i]
            status = ("DONE" if c.key in self.state.contracts else
                      "LOCK" if not self.state.contract_unlocked(c) else
                      "READY" if self.state.contract_progress(c) >= c.goal else "TODO")
            self.put(8 + row, 2, f"{'*' if c.key == self.state.pinned_contract else ' '}[{status:5}] {c.name}", reverse=i == self.selected)
        c = CONTRACTS[self.selected]
        self.put(height - 5, 2, f"Board {c.board + 1} | {self.state.contract_progress(c):,.0f}/{c.goal:,} | +{cash(c.reward)}", "gold")
        self.put(height - 4, 2, "Complete earlier boards first." if not self.state.contract_unlocked(c)
                 else "Cash grant.", "muted")

    def skill_lines(self, skill):
        rank = self.state.skills[skill.key]
        requirement = self.state.skill_requirement(skill)
        if rank >= skill.limit:
            status = "MAXED"
        elif requirement:
            status = requirement
        else:
            status = f"Next rank: {self.state.skill_cost(skill)} stars"
        return rank, status

    def prestige_page(self, height, width):
        s = self.state
        self.selected %= len(SKILLS)
        self.put(5, 2, f"PRESTIGE  |  {s.skill_points} unspent / {s.stars} earned stars", "gold", True)
        self.put(6, 2, f"Permanent reputation: +{s.stars * 10}% (spending keeps this bonus)", "muted")
        self.put(7, 2, f"[{self.key('prestige')}] Restart for +{s.prestige_reward} stars | [ENTER] buy selected skill", "accent")
        if s.prestige_reward == 0:
            self.put(7, 2, f"[{self.key('prestige')}] Unlock at {cash(PRESTIGE_AT)} earned | ENTER buy skill", "accent")
        if width >= 94 and height >= 29:
            column_width = (width - 6) // 3
            for branch in range(3):
                x = 2 + branch * column_width
                self.put(9, x, SKILLS[branch * 3].branch, "accent", True)
                for tier in range(3):
                    i = branch * 3 + tier
                    skill = SKILLS[i]
                    rank, status = self.skill_lines(skill)
                    y = 11 + tier * 4
                    self.put(y, x, f"[{i + 1}] {skill.name}", bold=self.selected == i,
                             reverse=self.selected == i, limit=column_width - 2)
                    self.put(y + 1, x, f"Rank {rank}/{skill.limit}", "gold", limit=column_width - 2)
                    if self.state.skill_requirement(skill):
                        parent, needed = skill.requires
                        status = f"Needs previous skill rank {needed}"
                    self.put(y + 2, x, status, "muted", limit=column_width - 2)
                    if tier < 2:
                        self.put(y + 3, x + 2, "|", "muted")
        else:
            for i, skill in enumerate(SKILLS):
                rank, status = self.skill_lines(skill)
                if self.state.skill_requirement(skill):
                    status = "LOCKED"
                self.put(9 + i, 2, f"[{i + 1}] {skill.name:<21} {rank}/{skill.limit}  {status}",
                         bold=self.selected == i, reverse=self.selected == i)
        skill = SKILLS[self.selected]
        if height >= 29:
            self.put(height - 6, 2, skill.branch + ": " + skill.description, "text")
            self.put(height - 5, 2, self.state.skill_requirement(skill) or
                     "Skills are permanent. Starting grants apply on your next prestige.", "muted")
        else:
            description = skill.description
            self.put(height - 4, 2, description, "muted")

    def text_page(self, title, lines, height, width):
        self.put(5, 2, title, "accent", True)
        lines = [part for line in lines for part in (textwrap.wrap(line, max(10, width - 5)) or [""])]
        visible = max(1, height - 11)
        self.scroll = min(self.scroll, max(0, len(lines) - visible))
        for i, line in enumerate(lines[self.scroll:self.scroll + visible]):
            self.put(7 + i, 2, line, "text", limit=width - 4)
        if len(lines) > visible:
            self.put(height - 4, 2, f"Up/Down: scroll ({self.scroll + 1}-{min(len(lines), self.scroll + visible)}/{len(lines)})", "muted")

    def stats(self, height, width):
        s = self.state
        lines = [
            f"Lifetime: {cash(s.lifetime)}    Earned this run: {cash(s.run_earned)}",
            f"Manual treatments: {s.manual:,}    Staff units: {sum(s.staff.values())}",
            f"Active time: {duration(s.play_seconds)}    Completed empires: {s.wins}",
            f"Reputation: {s.stars} stars (+{s.stars * 10}% earnings)",
            f"Unspent stars: {s.skill_points}    Skill ranks: {sum(s.skills.values())}",
            f"Cases completed: {s.cases_completed} | Contracts: {len(s.contracts)}/{len(CONTRACTS)}",
            f"Workshop equipment: {len(s.crafted)}/{len(RECIPES)} | Focus uses: {s.focus_uses}",
            f"Cabinet keys: {s.supply_keys} | Cabinets opened: {s.hunts_played}",
            f"Supply crates: {s.supply_crates} | Crate keys: {s.crate_keys}",
            f"Crates opened: {s.crates_opened} | Cosmetics: {collection_count(s.cosmetics)}/{len(ACTIVE_ITEMS)}",
            f"Prestiges: {s.prestiges}    Offline cap: {s.offline_cap // 3600} hours",
            f"Current per tap: {cash(s.click_value)}    Per second: {cash(s.income)}",
            "", "ACHIEVEMENTS - each adds +2% earnings",
            f"/ filter: {self.achievement_filter} | {len(s.achievements)}/{len(ACHIEVEMENTS)} unlocked", "",
        ]
        for achievement in ACHIEVEMENTS:
            key, name, description, _, goal = achievement
            unlocked = key in s.achievements
            if self.achievement_filter == "locked" and unlocked:
                continue
            if self.achievement_filter == "unlocked" and not unlocked:
                continue
            lines.append(("[x] " if unlocked else "[ ] ") + name)
            progress = s.achievement_progress(achievement)
            lines.append(f"    {progress:,.0f}/{goal:,} - {description}")
        lines.extend(("", "RECENT NOTICES", *reversed(self.session.log[-15:])))
        self.text_page("YOUR PRACTICE", lines, height, width)

    def help(self, height, width):
        k = self.key
        lines = [
            "Idle Dentistry is an idle game (wow) where your goal is to build a molar empire",
            "",
            f"Press {k('treat')} or click to treat patients and earn cash.",
            "Hire staff for passive income, buy upgrades, and expand.",
            "Complete patient cases and contracts for extra rewards.",
            "",
            f"Use {k('focus')} for a temporary treatment boost.",
            "Collect materials and craft permanent Workshop equipment.",
            "Search the Supply Cabinet for prizes. Watch out for spoiled packages!",
            "Find crates and keys while treating patients to collect cosmetics.",
            "Choose an owned cosmetic from your Inventory to decorate your clinic.",
            "",
            "Prestige resets your practice in exchange for permanent stars.",
            "Spend stars on skills to make your next practice stronger.",
            "",
            "TAB / Left / Right: switch pages.",
            "Up / Down: select or scroll. ENTER: choose an action.",
            f"{k('menu')}: menu and settings | {k('pause')}: pause",
            f"{k('save')}: save | {k('quit')}: save and quit",
            "",
            "Progress saves automatically. Staff also earn while you're away.",
        ]
        self.text_page("HOW TO PLAY", lines, height, width)

    def tutorial_hint(self):
        k = self.key
        prompts = [f"Treat a patient with {k('treat')} / click. Press K to skip this tutorial.",
                   f"Hire your first dentist: {k('staff')} then 1 ($25).",
                   f"Visit upgrades: {k('upgrades')}. Prices and effects appear below.",
                   f"Visit contracts: {k('contracts')}. ENTER claims a ready goal.",
                   f"Visit cases: {k('cases')}. ENTER accepts optional work.",
                   f"Visit skills: {k('skills')}. Prestige earns permanent stars."]
        return f"GUIDE {self.state.tutorial_step + 1}/6: " + prompts[self.state.tutorial_step]

    def update_tutorial(self):
        s = self.state
        if s.tutorial_status != "active" or self.modal or self.session.paused:
            return
        goals = (s.manual >= s.tutorial_target, s.staff["dentists"] >= 1,
                 self.view == "upgrades", self.view == "contracts", self.view == "cases", self.view == "skills")
        if goals[s.tutorial_step]:
            if s.tutorial_step == 5:
                s.tutorial_status = "done"
                self.session.say("GUIDE COMPLETE. Grow your clinic, finish contracts, build an empire!")
            else:
                s.tutorial_step += 1
            self.save()

    def dialog(self, height, width):
        s = self.state
        if self.modal == "prestige":
            title = "START A NEW PRACTICE?"
            body = [f"Gain {s.prestige_reward} stars. Unspent balance: {s.skill_points + s.prestige_reward}.",
                    "RESET: cash, staff, upgrades, clinic, focus timers and active case.",
                    "KEEP: skills, stars, achievements, contracts, supplies and cosmetics.",
                    f"Next-run perks: ${250 * s.skills['investors']} + {2 if s.skills['automation'] else 0} dentists."]
            footer = "[Y] Prestige   [N / ESC] Keep this clinic"
        elif self.modal == "crate":
            title = "OPEN A COSMETIC SUPPLY CRATE?"
            body = [f"Spend 1 crate + 1 crate key? You have {s.supply_crates} crates / {s.crate_keys} keys.",
                    rarity_summary(),
                    "These do not give any stat bonuses. It's just fun to open crates :)",
                    "Crate keys are earned by treating patients."]
            footer = "[Y] Open   [N / ESC] Cancel"
        elif self.modal == "cabinet":
            title = "OPEN A SUPPLY CABINET?"
            body = [f"Spend one cabinet key? You have {s.supply_keys}.",
                    "Find seven prizes among nine drawers. Two packages are spoiled.",
                    "A spoiled package ends the search unless a liner protects it.",
                    "You keep every revealed prize. The key is not refunded."]
            footer = "[Y] Spend key   [N / ESC] Cancel"
        elif self.modal == "tutorial":
            title = "WELCOME TO YOUR PRACTICE"
            body = ["Would you like a tutorial?",
                    "Learn treatments, hiring, upgrades, contracts, cases and prestige.",
                    "Your earnings and existing progress stay with you.",
                    "The tutorial resumes when you return. Press K to skip anytime."]
            footer = "[Y / ENTER] Start guide   [K / ESC] Skip"
        elif self.modal == "welcome":
            title, body, footer = "PRACTICE REPORT", self.welcome, "[ENTER / ESC] Continue"
        else:
            title = "THE MOLAR EMPIRE"
            body = ["Your waiting room finally has enough chairs.", f"Lifetime earnings: {cash(s.lifetime)}",
                    "Run complete! Keep growing, finish your contracts, or prestige."]
            footer = "[ENTER / ESC] Continue playing"
        boxwidth = min(66, width - 4)
        wrapped = [part for line in body for part in textwrap.wrap(line, max(10, boxwidth - 4))]
        lines = [title, ""] + wrapped[:max(1, height - 10)] + ["", footer]
        x, y = (width - boxwidth) // 2, max(0, (height - len(lines) - 2) // 2)
        for dy in range(len(lines) + 2):
            self.put(y + dy, x, " " * boxwidth, reverse=True)
        for i, line in enumerate(lines):
            self.put(y + 1 + i, x + 2, line, "gold" if i == 0 else "text",
                     bold=i == 0, limit=boxwidth - 4, reverse=True)

    def status_banner(self):
        if self.session.paused:
            banner, colour = f"PAUSED - {self.key('pause')} to resume", "bad"
        elif self.state.tutorial_status == "active":
            banner, colour = self.tutorial_hint(), "gold"
        elif self.session.event:
            seconds = max(0, math.ceil(self.session.event_end - self.session.clock))
            kind = "Tooth fairy tip" if self.session.event == "tip" else "Walk-in rush: 2x income"
            banner, colour = f"[{self.key('bonus')}] {kind} - {seconds}s to claim", "good"
        elif self.session.bonus == 2:
            banner, colour = f"WALK-IN RUSH: 2x earnings for {math.ceil(self.session.boost_end - self.session.clock)}s", "good"
        elif self.state.pinned_contract:
            goal = next(c for c in CONTRACTS if c.key == self.state.pinned_contract)
            progress = self.state.contract_progress(goal)
            banner = f"GOAL {progress:,.0f}/{goal.goal:,}: {goal.name}"
            colour = "good" if progress >= goal.goal else "accent"
        elif self.state.showcase:
            item = get_cosmetic(self.state.showcase)
            banner, colour = "Showcase: " + item.name + " [" + item.rarity + "]", item.rarity
        else:
            banner, colour = "Your patients have been waiting since 2006.", "muted"
        return banner, colour

    def render(self):
        self.update_crate_reveal()
        height, width = self.screen.getmaxyx()
        self.screen.erase()
        self.mouse_area = None
        if height < 22 or width < 60:
            self.put(0, 0, "IDLE DENTISTRY", "accent", True)
            self.put(2, 0, "Resize to at least 60 columns x 22 rows.")
            self.put(4, 0, f"Income continues. {self.key('quit')} saves and quits.")
            self.screen.refresh()
            return
        self.put(0, 2, "IDLE DENTISTRY", "accent", True)
        saved = f"SAVE ERROR - {self.key('save')} retries" if not self.save_ok else "Autosave: ON"
        self.put(0, max(24, width - len(saved) - 2), saved, "bad" if not self.save_ok else "muted")
        self.put(1, 2, f"{cash(self.state.money)}   +{cash(self.state.income * self.session.bonus)}/s   "
                 f"{self.state.skill_points}/{self.state.stars} stars   | {CLINICS[self.state.clinic][0]}", "gold", True)
        tab = TAB_BY_KEY[self.view]
        position = TAB_KEYS.index(self.view) + 1
        self.put(2, 2, f"< TAB / arrows >  {position}/{len(TABS)}  {tab.label}", "accent", True)
        banner, colour = self.status_banner()
        self.put(3, 2, banner, colour)
        self.line(4, 2, width - 4)
        if self.crate_reel:
            self.crate_overlay(height, width)
        else:
            getattr(self, tab.renderer)(height, width)
        self.line(height - 3, 2, width - 4)
        if self.session.log:
            self.put(height - 2, 2, self.session.log[-1], "muted")
        footer = f"TAB pages | {self.key('help')} help | {self.key('menu')} menu | {self.key('quit')} quit"
        self.put(height - 1, 2, footer)
        if self.modal:
            self.dialog(height, width)
        self.screen.refresh()

    def save(self, announce=False):
        try:
            save_game(self.path, self.state)
            self.save_ok = True
            self.last_save = time.monotonic()
            if announce:
                self.session.say("Progress saved.")
            return True
        except (OSError, ValueError) as exc:
            self.save_ok = False
            self.last_save = time.monotonic()
            self.session.say(f"SAVE FAILED: {exc}. {self.key('save')} retries.")
            return False

    def open_modal(self, kind):
        self.modal = kind
        self.restore_pause = self.session.paused
        self.session.paused = True
        self.gate.legacy_armed = False
        self.mouse_down = False

    def close_modal(self):
        previous = self.modal
        self.modal = None
        self.session.paused = self.restore_pause
        if previous == "welcome" and self.state.tutorial_status == "pending":
            self.open_modal("tutorial")

    def change_view(self, view):
        if view not in TAB_BY_KEY:
            raise ValueError(f"Unknown tab: {view}")
        self.view = view
        self.selected = self.state.next_case if self.view == "cases" else 0
        self.scroll = 0
        self.gate.legacy_armed = False
        self.mouse_down = False
        self.mouse_area = None

    def treat(self):
        if not self.session.paused and not self.modal and not self.state.pending_crate and self.view == "clinic":
            previous = dict(self.state.case)
            before_drops = (self.state.supply_crates, self.state.crate_keys)
            amount = self.state.treat(self.session.bonus)
            self.last_treat = self.session.clock
            self.session.achievements()
            self.session.say(f"TREATED: +{cash(amount)}." +
                             (" Supply delivery: +1 metal." if self.state.manual % 5 == 0 else ""))
            if previous and not self.state.case:
                self.session.say(f"CASE COMPLETE: +{cash(previous['reward'])}, +2 resin" +
                                 (", +1 chip!" if CASES[previous["index"]].clinic >= 1 else "!") +
                                 (f" Cabinet key earned! [{self.key('cabinet')}]" if self.state.cases_completed % 3 == 0 else ""))
            if before_drops != (self.state.supply_crates, self.state.crate_keys):
                drop = "Supply crate" if self.state.supply_crates > before_drops[0] else "Crate key"
                self.session.say(f"DROP: {drop}! [{self.key('inventory')}] Inventory")
                self.save()

    def handle_event(self, event):
        if event.key == "focus":
            self.gate.clear()
            self.mouse_down = False
            return True
        if event.key == "mouse":
            inside = False
            if self.mouse_area:
                x, y, w, h = self.mouse_area
                inside = x <= event.x < x + w and y <= event.y < y + h
            if event.kind == "press":
                self.mouse_down = inside
            elif event.kind == "release":
                if self.mouse_down and inside:
                    self.treat()
                self.mouse_down = False
            return True
        if not self.gate.accept(event):
            return True
        if (event.key in (99, 67) and event.modifiers & 4) or event.key == 3:
            raise KeyboardInterrupt
        if event.modifiers & (2 | 4 | 8):
            return True
        key = event.key
        if key == 47 and event.modifiers & 1:
            key = ord('?')
        action = self.settings.action(key)
        if self.view == "clinic" and not self.modal and not self.state.pending_crate and (action == "treat" or key in (10, 13)):
            if self.session.paused:
                self.gate.legacy_armed = False
            elif self.enhanced_input:
                if action == "treat" and event.enhanced:
                    self.treat()
            else:
                treatment_key = ord(self.settings.keys["treat"])
                normalised = treatment_key if action == "treat" else key
                if self.gate.legacy_treatment(normalised, treatment_key):
                    self.treat()
            return True
        return self.input(key)

    def handle_modal(self, key):
        lower = chr(key).lower() if isinstance(key, int) and 0 <= key < 128 else key
        if self.modal == "prestige" and lower == "y":
            stars = self.state.prestige()
            self.session.say(f"PRESTIGE: +{stars} stars. Skills: {self.key('skills')}.")
            self.session.event = ""
            self.session.boost_end = 0
            self.session.next_event = self.session.clock + 45
            self.session.achievements()
            self.close_modal()
            self.save()
        elif self.modal == "crate" and lower == "y":
            self.close_modal()
            self.start_crate_opening()
        elif self.modal == "crate" and lower in ("n", "\x1b"):
            self.close_modal()
        elif self.modal == "cabinet" and lower == "y":
            self.session.say(self.state.start_cabinet())
            self.selected = 0
            self.close_modal()
            self.save()
        elif self.modal == "cabinet" and lower in ("n", "\x1b"):
            self.close_modal()
        elif self.modal == "tutorial" and lower in ("y", "k", "n", "\x1b", "\n", "\r"):
            if lower in ("y", "\n", "\r"):
                self.state.start_tutorial()
                self.change_view("clinic")
            else:
                self.state.tutorial_status = "skipped"
            self.close_modal()
            self.save()
        elif self.modal == "prestige" and lower in ("n", "\x1b"):
            self.close_modal()
        elif self.modal in ("welcome", "win") and key in (10, 13, 27):
            self.close_modal()

    def handle_navigation(self, key, action):
        if key in (9, "right", "backtab", "left"):
            direction = -1 if key in ("left", "backtab") else 1
            self.change_view(TAB_KEYS[(TAB_KEYS.index(self.view) + direction) % len(TAB_KEYS)])
            return True
        if action in TAB_BY_KEY or key == ord('?'):
            self.change_view("help" if key == ord('?') else action)
            return True
        if key == 27:
            self.change_view("clinic")
            return True
        if self.view == "inventory" and key in (ord('['), ord(']'), ord('/'), 10, 13,
                                       "down", "up", "pagedown", "pageup"):
            self.inventory_input(key)
            return True
        if key in ("down", "up", "pagedown", "pageup"):
            direction = 1 if key in ("down", "pagedown") else -1
            sizes = {"staff": len(STAFF), "upgrades": len(UPGRADES), "skills": len(SKILLS),
                     "contracts": len(CONTRACTS), "cases": len(CASES), "workshop": len(RECIPES), "cabinet": 9}
            if self.view == "cases" and self.state.case:
                return True
            if self.view in sizes:
                self.selected = (self.selected + direction) % sizes[self.view]
            elif self.view in ("records", "help"):
                self.scroll = max(0, self.scroll + direction * (8 if key in ("pagedown", "pageup") else 1))
            return True
        if key == ord('/') and self.view == "records":
            filters = ("all", "locked", "unlocked")
            self.achievement_filter = filters[(filters.index(self.achievement_filter) + 1) % 3]
            self.scroll = 0
            return True
        if key == ord('/') and self.view == "contracts":
            self.session.say(self.state.pin_contract(self.selected))
            self.save()
            return True
        return False

    def handle_page_action(self, key):
        feedback = ""
        digit = key - ord('1') if isinstance(key, int) and ord('1') <= key <= ord('9') else None
        enter = key in (10, 13)
        if self.view in ("staff", "upgrades"):
            size = len(STAFF) if self.view == "staff" else len(UPGRADES)
            if digit is not None and digit < size:
                self.selected = digit
                enter = True
            if enter:
                index = self.selected if self.view == "staff" else len(STAFF) + self.selected
                feedback = self.state.buy(index, self.quantity)
        elif self.view == "skills":
            if digit is not None:
                self.selected = digit
            elif enter:
                feedback = self.state.buy_skill(self.selected)
                self.save()
        elif self.view == "contracts" and enter:
            feedback = self.state.claim_contract(self.selected)
            self.save()
        elif self.view == "cases" and enter:
            feedback = self.state.accept_case(self.selected)
            self.save()
        elif self.view == "cabinet":
            if digit is not None:
                self.selected = digit
            elif enter:
                if self.state.cabinet_active:
                    feedback = self.state.reveal_drawer(self.selected)
                    self.save()
                elif self.state.supply_keys:
                    self.open_modal("cabinet")
                else:
                    feedback = "NEED A KEY: every 3 completed patient cases gives one."
            elif key == ord('/'):
                feedback = self.state.stop_cabinet()
                self.save()
        elif self.view == "workshop" and enter:
            feedback = self.state.craft(self.selected)
            self.save()
        return feedback

    def input(self, key):
        action = self.settings.action(key)
        lower = chr(key).lower() if isinstance(key, int) and 0 <= key < 128 else key
        if action in ("quit", "menu"):
            if self.save():
                self.outcome = action
                return False
            return True
        if action == "save":
            self.save(announce=True)
            return True
        self.update_crate_reveal()
        if self.crate_reel:
            self.crate_input(key)
            return True
        height, width = self.screen.getmaxyx()
        if height < 22 or width < 60:
            return True
        if self.modal:
            self.handle_modal(key)
            return True
        if lower == "k" and self.state.tutorial_status == "active":
            self.state.tutorial_status = "skipped"
            self.session.say(f"Tutorial skipped. Press {self.key('tutorial')} to replay it.")
            self.save()
            return True
        if action == "tutorial":
            self.open_modal("tutorial")
            return True
        if action == "pause":
            self.session.paused = not self.session.paused
            self.gate.legacy_armed = False
            return True
        if self.handle_navigation(key, action):
            return True
        if self.session.paused:
            return True
        feedback = self.handle_page_action(key)
        if action == "focus":
            feedback = self.state.activate_focus()
            self.save()
        elif action == "quantity":
            self.quantity = {1: 10, 10: 0, 0: 1}[self.quantity]
        elif action == "expand":
            before = self.state.clinic
            feedback = self.state.expand()[0]
            if self.state.clinic != before:
                if self.state.clinic == len(CLINICS) - 1:
                    self.open_modal("win")
                self.save()
        elif action == "bonus":
            self.session.claim()
        elif action == "prestige":
            if self.state.prestige_reward:
                self.open_modal("prestige")
            else:
                self.session.say(f"Prestige unlocks at {cash(PRESTIGE_AT)} earned this run.")
        self.session.achievements()
        if feedback:
            self.session.say(feedback)
        return True

    def run(self):
        self.reader = TerminalInput()
        previous = time.monotonic()
        running = True
        try:
            self.render()
            with self.reader as reader:
                while running and not shutdown.requested():
                    now = time.monotonic()
                    self.session.tick(now - previous)
                    previous = now
                    self.update_tutorial()
                    if now - self.last_save >= 15:
                        self.save()
                    size = reader.size()
                    if self.screen.getmaxyx() != (size.lines, size.columns):
                        if os.name == "nt":
                            curses.resize_term(0, 0)
                        else:
                            curses.resizeterm(size.lines, size.columns)
                    self.render()
                    events = reader.poll(.2 if self.settings.reduced_animation else .05)
                    if not self.input_notice and (reader.decoder.queried or now - reader.started > .7):
                        self.input_notice = True
                        self.session.say(self.treatment_hint())
                    for event in events:
                        running = self.handle_event(event)
                        if not running:
                            break
        finally:
            save_game(self.path, self.state)
        return self.outcome