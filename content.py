from dataclasses import dataclass

@dataclass(frozen=True)
class Contract:
    key: str
    name: str
    metric: str
    goal: int
    reward: int
    board: int = 0
    decoration: str = ""

CONTRACTS = (
    Contract("open", "Open for business: treat 10 patients", "manual", 10, 30),
    Contract("team", "Build a team: own 3 dentists", "dentists", 3, 100, decoration="plant"),
    Contract("move", "Growing practice: expand once", "clinic", 1, 400),
    Contract("regulars", "Regular faces: treat 100 patients", "manual", 100, 500, 1),
    Contract("cases", "Case closed: finish 3 patient cases", "cases", 3, 750, 1),
    Contract("centre", "Smile Centre: reach clinic level 2", "clinic", 2, 2500, 1, "aquarium"),
    Contract("busy", "Busy practice: earn $100,000 total", "lifetime", 100000, 5000, 2),
    Contract("expert", "Case specialist: finish 15 cases", "cases", 15, 7500, 2),
    Contract("fresh", "Fresh start: prestige once", "prestiges", 1, 10000, 2, "diploma"),
    Contract("hospital", "Hospital director: reach clinic level 3", "clinic", 3, 25000, 3),
    Contract("legend", "Local legend: treat 1,000 patients", "manual", 1000, 50000, 3),
    Contract("empire", "The Molar Empire: complete a clinic", "wins", 1, 100000, 3, "trophy"),
)
CONTRACT_KEYS = {c.key for c in CONTRACTS}

@dataclass(frozen=True)
class Patient:
    name: str
    face: str
    complaint: str

PATIENTS = (
    Patient("Mina", "(^_^)", "flosses twice a year."),
    Patient("Arthur", "(-_-)", "king wants a crown (on his tooth)"),
    Patient("Pip", "(o_o)", "broke her tooth on a gobstopper"),
    Patient("Bea", "(:D)", "has blindingly white teeth"),
    Patient("Ravi", "(>_<)", "uses ice-cream as a diagnostic tool"),
    Patient("June", "(._.)", "scared of the dentist"),
    Patient("Sal", "(o_O)", "comes to the dentist for the free toothpaste"),
    Patient("Nico", "(^o^)", "goes to the dentist every month"),
)

@dataclass(frozen=True)
class Case:
    title: str
    patient: int
    steps: int
    clinic: int

CASES = (
    Case("Popcorn stuck in teeth", 0, 6, 0),
    Case("Golden crown", 1, 8, 0),
    Case("Gobstopper rematch", 2, 10, 1),
    Case("Flashbang smile", 3, 12, 1),
    Case("Ice-cream investigation", 4, 14, 2),
    Case("First checkup", 5, 16, 2),
    Case("Complimentary toothpase", 6, 20, 3),
    Case("All gold crown fitting", 1, 24, 3),
    Case("Monthly maintenance", 7, 28, 4),
    Case("Squeaky clean teeth", 3, 32, 4),
)