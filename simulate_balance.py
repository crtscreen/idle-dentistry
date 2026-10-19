import argparse
import csv
import json
import random
from pathlib import Path
from game import State, PURCHASES, STAFF, CLINICS, PRESTIGE_AT
from content import CONTRACTS, CASES
from activities import RECIPES

def simulate(strategy, seconds=21600, taps_per_second=.5, activities=True):
    if strategy not in ("balanced", "staff-first", "tools-first"):
        raise ValueError("Unknown strategy")
    if type(seconds) is not int or seconds < 1 or not 0 <= taps_per_second <= 10:
        raise ValueError("Use positive whole seconds and 0-10 treatments per second.")
    state = State(tutorial_status="skipped")
    first_expansion = first_prestige = empire = None
    credit = 0.0
    rng = random.Random(0)
    drop_rng = random.Random(1)
    bought = {p.key: 0 for p in PURCHASES}
    for elapsed in range(1, seconds + 1):
        state.earn(state.income)
        state.tick_activities(1)
        state.play_seconds += 1
        if not state.case:
            available = [i for i, case in enumerate(CASES) if case.clinic <= state.clinic]
            state.accept_case(available[state.cases_completed % len(available)])
        credit += taps_per_second
        while credit >= 1:
            state.treat(rng=drop_rng)
            credit -= 1
        state.check_achievements()
        if activities:
            if state.manual >= 10 and state.focus_wait == 0:
                state.activate_focus()
            for index in range(len(RECIPES)):
                if not state.craft_reason(index):
                    state.craft(index)
                    break
            if state.cabinet_active:
                index = next(i for i in range(9) if i not in state.cabinet["opened"])
                state.reveal_drawer(index)
            elif state.supply_keys:
                state.start_cabinet(rng)
        for i, contract in enumerate(CONTRACTS):
            if (contract.key not in state.contracts and state.contract_unlocked(contract)
                    and state.contract_progress(contract) >= contract.goal):
                state.claim_contract(i)
        if first_prestige is None and state.run_earned >= PRESTIGE_AT:
            first_prestige = elapsed
        if state.clinic < len(CLINICS) - 1 and state.money >= state.expansion_cost():
            state.expand()
            state.check_achievements()
            if first_expansion is None:
                first_expansion = elapsed
            if state.clinic == len(CLINICS) - 1:
                empire = elapsed
                break
        rate = state.income + state.click_value * taps_per_second
        cost_to_expand = state.expansion_cost() - state.money
        if 0 < cost_to_expand <= rate * 60:
            continue
        candidates = []
        for i, purchase in enumerate(PURCHASES):
            quote = state.purchase_preview(i)
            if quote["reason"]:
                continue
            gain = quote["gain"] + quote["tap_gain"] * taps_per_second
            if gain <= 0:
                continue
            payback = quote["price"] / gain
            if strategy == "staff-first" and purchase in STAFF:
                payback *= .45
            if strategy == "tools-first" and purchase.key == "tools":
                payback *= .3
            if payback <= 180:
                candidates.append((payback, i))
        if candidates:
            _, index = min(candidates)
            state.buy(index)
            bought[PURCHASES[index].key] += 1
    return {"strategy": strategy, "treatments_per_minute": taps_per_second * 60,
            "horizon_seconds": seconds, "simulated_seconds": elapsed,
            "first_expansion_seconds": first_expansion,
            "first_prestige_available_seconds": first_prestige, "empire_seconds": empire,
            "ending_clinic": state.clinic, "earned": round(state.run_earned, 2),
            "manual_treatments": state.manual, "purchases": bought,
            "cases": state.cases_completed, "activities_enabled": activities,
            "equipment_built": len(state.crafted), "focus_uses": state.focus_uses,
            "cabinets_opened": state.hunts_played}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=21600)
    parser.add_argument("--taps-per-second", type=float, default=.5)
    parser.add_argument("--baseline", action="store_true",
                        help="Compare without focus, crafting or opening cabinets")
    parser.add_argument("--csv", type=Path, help="Also export one flat row per strategy")
    args = parser.parse_args()
    if args.seconds < 1 or not 0 <= args.taps_per_second <= 10:
        parser.error("Use positive seconds and 0-10 treatments per second.")
    results = [simulate(s, args.seconds, args.taps_per_second, not args.baseline)
               for s in ("balanced", "staff-first", "tools-first")]
    print(json.dumps(results, indent=2))
    if args.csv:
        rows = [{**{k: v for k, v in result.items() if k != "purchases"},
                 **{f"bought_{k}": v for k, v in result["purchases"].items()}}
                for result in results]
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

if __name__ == "__main__":
    main()