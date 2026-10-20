from __future__ import annotations

from dataclasses import asdict, dataclass, field
from content import CONTRACTS, CONTRACT_KEYS, CASES, PATIENTS
from activities import Activities, load_activities
from version import SAVE_VERSION
from copy import copy
import json
import math
import os
from pathlib import Path
import random
import shutil
import time
import tempfile

OFFLINE_CAP = 8 * 60 * 60
PRESTIGE_AT = 100_000
MAX_STAFF = 500

@dataclass(frozen=True)
class Purchase:
    key: str
    name: str
    cost: float
    growth: float
    rate: float = 0
    unlock: float = 0
    limit: int = MAX_STAFF
    description: str = ""

STAFF = (
    Purchase("dentists", "Dentist", 25, 1.20, 1, description="+$1/s before bonuses"),
    Purchase("hygienists", "Hygienist team", 350, 1.22, 4, 150,
             description="+$4/s before bonuses"),
    Purchase("specialists", "Orthodontist", 5000, 1.24, 20, 1500,
             description="+$20/s before bonuses"),
    Purchase("robots", "Dental robot", 80_000, 1.26, 150, 20_000,
             description="+$150/s before bonuses"),
)
UPGRADES = (
    Purchase("tools", "Better tools", 40, 3.0, limit=10,
             description="+2 base cash per treatment"),
    Purchase("chairs", "Treatment suites", 800, 4.0, unlock=250, limit=10,
             description="+25% base staff production"),
    Purchase("marketing", "Advertising", 3000, 4.5, unlock=1000, limit=8,
             description="+15% to all earnings"),
)
PURCHASES = STAFF + UPGRADES
CLINICS = (
    ("Broom cupboard", 0),
    ("High Street Dental", 2500),
    ("Smile Centre", 25_000),
    ("Dental Hospital", 250_000),
    ("The Molar Empire", 2_000_000),
)
ACHIEVEMENTS = (
    ("first_patient", "Open wide", "Treat your first patient.", "manual", 1),
    ("busy_hands", "In safe hands", "Perform 100 manual treatments.", "manual", 100),
    ("steady_hands", "Dentist of the year", "Perform 1,000 manual treatments.", "manual", 1000),
    ("first_hire", "An extra pair of hands", "Hire your first staff member.", "staff", 1),
    ("team", "Staff meeting", "Employ 25 staff units at once.", "staff", 25),
    ("wealth", "Tooth fairy", "Earn $10,000 across all runs.", "lifetime", 10_000),
    ("million", "Million-dollar smile", "Earn $1,000,000 across all runs.", "lifetime", 1_000_000),
    ("expansion", "Room to breathe", "Expand your clinic once.", "clinic", 1),
    ("robot", "Please do not bite the robot", "Buy a dental robot.", "robots", 1),
    ("prestige", "A fresh practice", "Complete your first prestige.", "prestiges", 1),
    ("empire", "The Molar Empire", "Purchase the final clinic.", "wins", 1),
)
ACHIEVEMENT_KEYS = {a[0] for a in ACHIEVEMENTS}

@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    branch: str
    limit: int
    cost: int
    step: int
    description: str
    requires: tuple = ()

SKILLS = (
    Skill("steady", "Steady hands", "TREATMENT", 5, 1, 1,
          "+25% manual earnings per rank."),
    Skill("precision", "Precision dentistry", "TREATMENT", 3, 3, 2,
          "+2% of base staff income added to each tap per rank.", ("steady", 3)),
    Skill("mastery", "Master practitioner", "TREATMENT", 1, 8, 0,
          "Double all manual treatment earnings.", ("precision", 2)),
    Skill("training", "Team training", "MANAGEMENT", 5, 1, 1,
          "+15% passive earnings per rank."),
    Skill("procurement", "Smart recruitment", "MANAGEMENT", 3, 3, 2,
          "Staff cost 5% less per rank.", ("training", 3)),
    Skill("automation", "Founding team", "MANAGEMENT", 1, 8, 0,
          "Start future prestige runs with two free dentists.", ("procurement", 2)),
    Skill("reserves", "Night shift", "EXPANSION", 4, 1, 1,
          "Increase the offline cap by 2 hours per rank."),
    Skill("investors", "Seed funding", "EXPANSION", 3, 3, 2,
          "Start future prestige runs with $250 per rank.", ("reserves", 2)),
    Skill("franchise", "Franchise blueprint", "EXPANSION", 1, 8, 0,
          "All clinic expansions cost 20% less.", ("investors", 2)),
)
SKILL_BY_KEY = {s.key: s for s in SKILLS}

@dataclass
class State(Activities):
    money: float = 0
    lifetime: float = 0
    run_earned: float = 0
    manual: int = 0
    staff: dict = field(default_factory=lambda: {p.key: 0 for p in STAFF})
    upgrades: dict = field(default_factory=lambda: {p.key: 0 for p in UPGRADES})
    clinic: int = 0
    stars: int = 0
    skills: dict = field(default_factory=lambda: {s.key: 0 for s in SKILLS})
    prestiges: int = 0
    wins: int = 0
    achievements: list = field(default_factory=list)
    play_seconds: float = 0
    saved_at: float = 0
    tutorial_status: str = "pending"
    tutorial_step: int = 0
    tutorial_target: int = 1
    contracts: list = field(default_factory=list)
    pinned_contract: str = ""
    best_clinic: int = 0
    best_dentists: int = 0
    cases_completed: int = 0
    case: dict = field(default_factory=dict)
    version: int = SAVE_VERSION

    @property
    def multiplier(self):
        return ((1 + .4 * self.clinic) * (1 + .15 * self.upgrades["marketing"])
                * (1 + .1 * self.stars) * (1 + .02 * len(self.achievements))
                * (1.1 if "badge" in self.crafted else 1))

    @property
    def base_staff_income(self):
        return sum(self.staff[p.key] * p.rate for p in STAFF)

    @property
    def income(self):
        return (self.base_staff_income * (1 + .25 * self.upgrades["chairs"])
                * self.multiplier * (1 + .15 * self.skills["training"])
                * (1.15 if "organizer" in self.crafted else 1))

    @property
    def click_value(self):
        contribution = .03 + .02 * self.skills["precision"]
        return ((1 + 2 * self.upgrades["tools"] + contribution * self.base_staff_income)
                * self.multiplier * (1 + .25 * self.skills["steady"])
                * (2 if self.skills["mastery"] else 1)
                * (1.25 if "mirror" in self.crafted else 1))

    @property
    def offline_cap(self):
        return OFFLINE_CAP + self.skills["reserves"] * 2 * 3600

    @property
    def skill_points_spent(self):
        return sum(sum(skill.cost + rank * skill.step for rank in range(self.skills[skill.key]))
                   for skill in SKILLS)

    @property
    def skill_points(self):
        return self.stars - self.skill_points_spent

    def skill_cost(self, skill):
        return skill.cost + self.skills[skill.key] * skill.step

    def skill_requirement(self, skill):
        if skill.requires:
            parent, rank = skill.requires
            if self.skills[parent] < rank:
                return f"Requires {SKILL_BY_KEY[parent].name} rank {rank}."
        return ""

    def buy_skill(self, index):
        skill = SKILLS[index]
        if self.skills[skill.key] >= skill.limit:
            return f"{skill.name} is already maxed."
        requirement = self.skill_requirement(skill)
        if requirement:
            return requirement
        cost = self.skill_cost(skill)
        if self.skill_points < cost:
            return f"Need {cost} unspent stars for {skill.name}. Prestige to earn more."
        self.skills[skill.key] += 1
        return f"Learned {skill.name}, rank {self.skills[skill.key]}!"

    def expansion_cost(self):
        if self.clinic == len(CLINICS) - 1:
            return 0
        return math.ceil(CLINICS[self.clinic + 1][1] * (.8 if self.skills["franchise"] else 1))

    @property
    def prestige_reward(self):
        return math.isqrt(int(self.run_earned // PRESTIGE_AT))

    def earn(self, amount):
        amount = max(0, amount)
        self.money += amount
        self.lifetime += amount
        self.run_earned += amount

    def start_tutorial(self):
        self.tutorial_status = "active"
        self.tutorial_step = 0
        self.tutorial_target = self.manual + 1

    def record_milestones(self):
        self.best_clinic = max(self.best_clinic, self.clinic)
        self.best_dentists = max(self.best_dentists, self.staff["dentists"])

    def contract_progress(self, contract):
        self.record_milestones()
        values = {"manual": self.manual, "dentists": self.best_dentists,
                  "clinic": self.best_clinic, "cases": self.cases_completed,
                  "lifetime": self.lifetime, "prestiges": self.prestiges, "wins": self.wins}
        return min(contract.goal, values[contract.metric])

    def contract_unlocked(self, contract):
        return all(c.key in self.contracts for c in CONTRACTS if c.board < contract.board)

    @property
    def decorations(self):
        return [c.decoration for c in CONTRACTS if c.key in self.contracts and c.decoration]

    def pin_contract(self, index):
        contract = CONTRACTS[index]
        if self.pinned_contract == contract.key:
            self.pinned_contract = ""
            return "Goal unpinned."
        if contract.key in self.contracts or not self.contract_unlocked(contract):
            return "Choose an unlocked, unclaimed contract to pin."
        self.pinned_contract = contract.key
        return "GOAL PINNED: progress appears above every page."

    def claim_contract(self, index):
        contract = CONTRACTS[index]
        if contract.key in self.contracts:
            return "Already claimed. Contracts pay once across all prestige runs."
        if not self.contract_unlocked(contract):
            return "LOCKED: claim every contract on the earlier boards first."
        if self.contract_progress(contract) < contract.goal:
            return "IN PROGRESS: this objective is not complete yet."
        self.contracts.append(contract.key)
        if self.pinned_contract == contract.key:
            self.pinned_contract = ""
        self.money += contract.reward
        extra = f" Decoration unlocked: {contract.decoration}." if contract.decoration else ""
        return f"CLAIMED: +${contract.reward:,}." + extra

    def achievement_values(self):
        return {
            "manual": self.manual, "staff": sum(self.staff.values()),
            "lifetime": self.lifetime, "clinic": self.clinic,
            "robots": self.staff["robots"], "prestiges": self.prestiges, "wins": self.wins,
        }

    def achievement_progress(self, achievement):
        key, _, _, metric, threshold = achievement
        if key in self.achievements:
            return threshold
        return min(threshold, self.achievement_values()[metric])

    def check_achievements(self):
        self.record_milestones()
        values = self.achievement_values()
        unlocked = []
        for key, name, _, metric, threshold in ACHIEVEMENTS:
            if key not in self.achievements and values[metric] >= threshold:
                self.achievements.append(key)
                unlocked.append(name)
        return unlocked

    def treat(self, bonus=1, rng=None):
        amount = self.click_value * bonus * self.focus_multiplier
        self.earn(amount)
        self.manual += 1
        completed = None
        if self.case:
            self.case["progress"] += self.case_power
            if self.case["progress"] >= CASES[self.case["index"]].steps:
                self.earn(self.case["reward"])
                self.cases_completed += 1
                completed = CASES[self.case["index"]]
                self.case = {}
        self.collect_supplies(completed)
        self.roll_crate_drop(rng)
        return amount

    @property
    def patient(self):
        index = CASES[self.case["index"]].patient if self.case else self.manual % len(PATIENTS)
        return PATIENTS[index]

    @property
    def case_power(self):
        return 1 + ("handpiece" in self.crafted) + (self.focus_left > 0)

    @property
    def next_case(self):
        return self.cases_completed % len(CASES)

    def case_quote(self, index=None):
        c = CASES[self.next_case if index is None else index]
        return math.ceil(max(self.click_value * c.steps * 2, self.income * 8, 20))

    def accept_case(self, index=None):
        if self.case:
            return "A case is already active. Treat patients to finish it."
        index = self.next_case if index is None else index
        if type(index) is not int or not 0 <= index < len(CASES):
            return "Unknown patient case."
        c = CASES[index]
        if self.clinic < c.clinic:
            return f"LOCKED: expand to {CLINICS[c.clinic][0]} for this case."
        self.case = {"index": index, "progress": 0, "reward": self.case_quote(index)}
        return f"CASE ACCEPTED: {c.title}. Reward locked at ${self.case['reward']:,.0f}."

    def owned(self, p):
        return (self.staff if p in STAFF else self.upgrades)[p.key]

    def cost(self, p, extra=0):
        discount = 1 - .05 * self.skills["procurement"] if p in STAFF else 1
        return math.ceil(p.cost * p.growth ** (self.owned(p) + extra) * discount)

    def quote(self, p, quantity=1):
        owned = self.owned(p)
        available = p.limit - owned
        if self.run_earned < p.unlock or available <= 0:
            return 0, 0
        count = min(available, quantity if quantity else available)
        discount = 1 - .05 * self.skills["procurement"] if p in STAFF else 1
        total = 0
        for i in range(count):
            cost = math.ceil(p.cost * p.growth ** (owned + i) * discount)
            if quantity == 0 and total + cost > self.money + 1e-9:
                return i, total
            total += cost
        return count, total

    def purchase_preview(self, index, quantity=1):
        p = PURCHASES[index]
        count, price = self.quote(p, quantity)
        reason = ""
        if self.run_earned < p.unlock:
            reason = f"LOCKED: earn ${p.unlock:,.0f} this run (${self.run_earned:,.0f} so far)."
        elif self.owned(p) >= p.limit:
            reason = "MAX LEVEL reached."
        elif not count or price > self.money + 1e-9:
            reason = f"CANNOT AFFORD: need ${price if count else self.cost(p):,.0f}."
        after = copy(self)
        after.staff = self.staff.copy()
        after.upgrades = self.upgrades.copy()
        after.achievements = self.achievements.copy()
        group = after.staff if p in STAFF else after.upgrades
        group[p.key] += count
        after.check_achievements()
        gain = after.income - self.income
        return {"count": count, "price": price, "reason": reason,
                "income": after.income, "click": after.click_value,
                "gain": gain, "tap_gain": after.click_value - self.click_value,
                "payback": price / gain if gain > 0 and count else None}

    def buy(self, index, quantity=1):
        p = PURCHASES[index]
        if self.run_earned < p.unlock:
            return f"Unlock {p.name} by earning ${p.unlock:,.0f} this run."
        if self.owned(p) >= p.limit:
            return f"{p.name}: maximum reached."
        count, price = self.quote(p, quantity)
        if not count or self.money + 1e-9 < price:
            return f"CANNOT AFFORD {p.name}: need ${price if count else self.cost(p):,.0f}."
        self.money = max(0, self.money - price)
        collection = self.staff if p in STAFF else self.upgrades
        collection[p.key] += count
        return f"BOUGHT: {count} x {p.name} for ${price:,.0f}."

    def expand(self):
        if self.clinic == len(CLINICS) - 1:
            return "Your Molar Empire is complete. Keep growing or prestige!", False
        name = CLINICS[self.clinic + 1][0]
        cost = self.expansion_cost()
        if self.money < cost:
            return f"You need ${cost:,.0f} to open {name}.", False
        self.money -= cost
        self.clinic += 1
        won = self.clinic == len(CLINICS) - 1
        if won:
            self.wins += 1
        return f"Welcome to {name}! All earnings increased.", won

    def prestige(self):
        reward = self.prestige_reward
        if reward < 1:
            return 0
        self.record_milestones()
        self.stars += reward
        self.prestiges += 1
        self.money = self.run_earned = 0
        self.staff = {p.key: 0 for p in STAFF}
        self.upgrades = {p.key: 0 for p in UPGRADES}
        self.clinic = 0
        self.case = {}
        self.focus_left = self.focus_wait = 0
        self.money = 250 * self.skills["investors"]
        self.staff["dentists"] = 2 if self.skills["automation"] else 0
        return reward

def _number(data, key, default=0, integer=False, maximum=1e60):
    value = data.get(key, default)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= maximum
            or (integer and value != int(value))):
        raise ValueError(f"Invalid save field: {key}")
    return int(value) if integer else float(value)

def decode_save(data):
    if not isinstance(data, dict):
        raise ValueError("Save must contain an object")
    if type(data.get("version")) is not int or data["version"] != SAVE_VERSION:
        raise ValueError(f"Unsupported save format, expected version {SAVE_VERSION}")
    s = State()
    for name in ("money", "lifetime", "run_earned", "play_seconds", "saved_at"):
        setattr(s, name, _number(data, name))
    for name in ("manual", "prestiges", "wins"):
        setattr(s, name, _number(data, name, integer=True, maximum=10**15))
    s.stars = _number(data, "stars", integer=True, maximum=10**12)
    skill_data = data.get("skills", {})
    if not isinstance(skill_data, dict):
        raise ValueError("Invalid skills")
    s.skills = {skill.key: _number(skill_data, skill.key, integer=True, maximum=skill.limit)
                for skill in SKILLS}
    if s.skill_points < 0:
        raise ValueError("Skill spending exceeds earned stars")
    for skill in SKILLS:
        if s.skills[skill.key] and s.skill_requirement(skill):
            raise ValueError("Skill prerequisites are missing")
    s.clinic = _number(data, "clinic", integer=True, maximum=len(CLINICS) - 1)
    for fieldname, purchases in (("staff", STAFF), ("upgrades", UPGRADES)):
        group = data.get(fieldname, {})
        if not isinstance(group, dict):
            raise ValueError(f"Invalid {fieldname}")
        setattr(s, fieldname, {p.key: _number(group, p.key, integer=True, maximum=p.limit)
                               for p in purchases})
    achievements = data.get("achievements", [])
    if not isinstance(achievements, list) or any(not isinstance(a, str) for a in achievements):
        raise ValueError("Invalid achievements")
    s.achievements = list(dict.fromkeys(a for a in achievements if a in ACHIEVEMENT_KEYS))
    status = data.get("tutorial_status", "skipped")
    if status not in ("pending", "active", "done", "skipped"):
        raise ValueError("Invalid tutorial status")
    s.tutorial_status = status
    s.tutorial_step = _number(data, "tutorial_step", integer=True, maximum=5)
    s.tutorial_target = _number(data, "tutorial_target", default=s.manual + 1,
                                integer=True, maximum=10**15 + 1)
    claims = data.get("contracts", [])
    if not isinstance(claims, list) or any(not isinstance(c, str) or c not in CONTRACT_KEYS for c in claims):
        raise ValueError("Invalid contract claims")
    s.contracts = list(dict.fromkeys(claims))
    pinned = data.get("pinned_contract", "")
    if not isinstance(pinned, str) or (pinned and pinned not in CONTRACT_KEYS):
        raise ValueError("Invalid pinned contract")
    s.pinned_contract = pinned if pinned not in s.contracts else ""
    s.best_clinic = _number(data, "best_clinic", integer=True, maximum=len(CLINICS) - 1)
    s.best_dentists = _number(data, "best_dentists", integer=True, maximum=MAX_STAFF)
    s.cases_completed = _number(data, "cases_completed", integer=True, maximum=10**15)
    case = data.get("case", {})
    if not isinstance(case, dict):
        raise ValueError("Invalid patient case")
    if case:
        if not {"index", "progress", "reward"} <= case.keys():
            raise ValueError("Incomplete patient case")
        index = _number(case, "index", integer=True, maximum=len(CASES) - 1)
        progress = _number(case, "progress", integer=True, maximum=CASES[index].steps - 1)
        reward = _number(case, "reward")
        s.case = {"index": index, "progress": progress, "reward": reward}
    s.record_milestones()
    load_activities(s, data, _number)
    s.lifetime = max(s.lifetime, s.run_earned)
    return s

def offline_earnings(s, now):
    seconds = min(s.offline_cap, max(0, now - s.saved_at)) if s.saved_at else 0
    amount = s.income * seconds
    s.earn(amount)
    s.saved_at = now
    s.check_achievements()
    return seconds, amount

def load_game(path: Path, now=None):
    now = time.time() if now is None else now
    warnings = []
    backup = path.with_suffix(path.suffix + ".bak")
    if not path.exists() and not backup.exists():
        return State(saved_at=now), ["Welcome! Build a tiny practice into the Molar Empire."]
    state = None
    for candidate in (path, backup):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not read {candidate.name}: {exc}")
            continue
        try:
            state = decode_save(data)
        except (ValueError, TypeError, OverflowError) as exc:
            warnings.append(f"Invalid {candidate.name}: {exc}")
            continue
        if candidate != path:
            warnings.append("Recovered progress from the backup save.")
        break
    if state is None:
        raise ValueError(f"No readable format-{SAVE_VERSION} save found. New Game archives existing saves before starting over.")
    away = max(0, now - state.saved_at) if state.saved_at else 0
    seconds, amount = offline_earnings(state, now)
    if away >= 1:
        def elapsed(value):
            return f"{int(value) // 3600}h {int(value) % 3600 // 60:02d}m"
        warnings.append(f"While away: {elapsed(away)}. Earned ${amount:,.2f}.")
        warnings.append(f"Paid time: {elapsed(seconds)}. Offline cap {state.offline_cap // 3600}h. No timed bonuses offline.")
    return state, warnings


def save_game(path: Path, state: State, now=None):
    timestamp = time.time() if now is None else now
    payload = asdict(state)
    payload["saved_at"] = timestamp
    decode_save(payload)
    text = json.dumps(payload, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            try:
                decode_save(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError, TypeError, OverflowError):
                pass
            else:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        os.replace(temporary, path)
        state.saved_at = timestamp
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

class Session:
    def __init__(self, state, rng=None):
        self.state = state
        self.rng = rng or random.Random()
        self.clock = 0.0
        self.next_event = 45.0
        self.event = ""
        self.event_end = 0.0
        self.boost_end = 0.0
        self.paused = False
        self.log = []

    @property
    def bonus(self):
        return 2 if self.clock < self.boost_end else 1

    def say(self, message):
        self.log.append(message)
        self.log = self.log[-40:]

    def achievements(self):
        for name in self.state.check_achievements():
            self.say(f"Achievement: {name}! (+2% earnings)")

    def tick(self, seconds):
        if self.paused or seconds <= 0:
            return
        boosted = min(seconds, max(0, self.boost_end - self.clock))
        self.state.earn(self.state.income * (seconds + boosted))
        self.state.tick_activities(seconds)
        self.state.play_seconds += seconds
        self.clock += seconds
        if self.event and self.clock >= self.event_end:
            self.say("The bonus opportunity passed. Another will come along.")
            self.event = ""
        if self.clock >= self.next_event:
            self.event = self.rng.choice(("tip", "rush"))
            self.event_end = self.clock + 20
            self.next_event = self.clock + self.rng.uniform(65, 100)
            self.say("BONUS AVAILABLE: claim it using the key shown above.")
        self.achievements()

    def claim(self):
        if not self.event or self.clock >= self.event_end:
            self.say("No bonus to collect just now.")
            return
        if self.event == "tip":
            amount = max(self.state.click_value * 25, self.state.income * 20)
            self.state.earn(amount)
            self.say(f"The tooth fairy left a tip: ${amount:,.0f}!")
        else:
            self.boost_end = self.clock + 25
            self.say("Walk-in rush! Double all earnings for 25 seconds.")
        self.event = ""
        self.achievements()