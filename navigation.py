from dataclasses import dataclass

@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    renderer: str

TABS = (
    Tab("clinic", "CLINIC", "clinic"),
    Tab("staff", "STAFF", "staff_page"),
    Tab("upgrades", "UPGRADES", "upgrades_page"),
    Tab("skills", "PRESTIGE", "prestige_page"),
    Tab("records", "RECORDS", "stats"),
    Tab("contracts", "CONTRACTS", "contracts_page"),
    Tab("cases", "CASES", "cases_page"),
    Tab("workshop", "WORKSHOP", "workshop_page"),
    Tab("cabinet", "CABINET", "cabinet_page"),
    Tab("inventory", "INVENTORY", "inventory_page"),
    Tab("help", "HELP", "help"),
)
TAB_KEYS = tuple(tab.key for tab in TABS)
TAB_BY_KEY = {tab.key: tab for tab in TABS}
