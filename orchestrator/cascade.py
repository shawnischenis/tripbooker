"""Replan cascade — Phase 4 timing math.

When any leg's actual arrival is later than originally scheduled, propagate
the delay forward:

  - leg N's actual_depart shifts to the next-available transit departure
    (frequent transit only — metro / commuter train) or fails (bookable bus).
  - Downstream legs recompute against the SHIFTED actual times.

Surfaces, per transition: scheduled times, actual times after propagation,
slack (or miss) in minutes, whether the departure was shifted to a later
train, and whether the chain still catches the bookable bus leg.

When the bookable bus is missed, queries Senso for the change-fee policy
and pulls candidate rebooks from intercity_comparison.candidates.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from integrations import senso

MIN_TRANSFER_BUFFER_MIN = 5
WALK_TO_BUS_DECK_MIN = 5   # Union Station Metro platform → FlixBus boarding area
METRO_FREQUENCY_MIN = 6    # WMATA Red Line peak headway


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _propagate(legs: list[dict]) -> dict:
    """For each leg.n, compute actual_depart / actual_arrive after delays
    propagate forward. None means the leg couldn't be boarded."""
    actual: dict[int, dict] = {}
    for i, leg in enumerate(legs):
        sched_dep = _iso(leg["depart"])
        sched_arr = _iso(leg["arrive"])
        duration = sched_arr - sched_dep

        if i == 0:
            # Leg 1's "scheduled" times already reflect replan perturbations
            actual[leg["n"]] = {
                "depart": sched_dep, "arrive": sched_arr,
                "shifted": False, "shifted_by_min": 0,
            }
            continue

        prev = legs[i - 1]
        prev_actual_arr = actual[prev["n"]].get("arrive")
        if prev_actual_arr is None:
            actual[leg["n"]] = {"depart": None, "arrive": None,
                                "shifted": False, "shifted_by_min": 0}
            continue

        walk = WALK_TO_BUS_DECK_MIN if leg.get("bookable") else 0
        platform_time = prev_actual_arr + timedelta(minutes=walk)

        if platform_time <= sched_dep:
            depart = sched_dep
            shifted, shift_by = False, 0
        elif leg.get("mode") in ("metro", "train") and not leg.get("bookable"):
            # Walk-on transit: skip to next scheduled departure on the headway grid
            late_min = (platform_time - sched_dep).total_seconds() / 60
            trains_to_skip = int(late_min // METRO_FREQUENCY_MIN) + 1
            depart = sched_dep + timedelta(minutes=trains_to_skip * METRO_FREQUENCY_MIN)
            shifted, shift_by = True, trains_to_skip * METRO_FREQUENCY_MIN
        else:
            # Bookable bus / non-frequent leg: can't be boarded
            depart, shifted, shift_by = None, True, None

        arrive = depart + duration if depart else None
        actual[leg["n"]] = {"depart": depart, "arrive": arrive,
                            "shifted": shifted, "shifted_by_min": shift_by}
    return actual


def _transitions(legs: list[dict], actual: dict[int, dict]) -> list[dict]:
    out = []
    for i in range(len(legs) - 1):
        a, b = legs[i], legs[i + 1]
        a_actual_arr = actual[a["n"]]["arrive"]
        b_sched_dep = _iso(b["depart"])
        b_actual = actual[b["n"]]
        walk = WALK_TO_BUS_DECK_MIN if b.get("bookable") else 0

        if a_actual_arr is None:
            out.append({
                "from_leg": a["n"], "to_leg": b["n"],
                "from_label": f"{a['operator']} → {a['to']}",
                "to_label": b["operator"],
                "scheduled_arrive": a["arrive"], "scheduled_depart": b["depart"],
                "actual_arrive": None, "actual_depart": None,
                "walk_buffer_min": walk, "slack_min": None,
                "feasible": False, "miss_by_min": None,
                "shifted": False, "shifted_by_min": 0,
                "recoverable": False, "recovery_note": "upstream leg failed",
            })
            continue

        platform_time = a_actual_arr + timedelta(minutes=walk)
        slack_min = int((b_sched_dep - platform_time).total_seconds() / 60)
        made_scheduled = slack_min >= 0
        is_frequent_transit = b.get("mode") in ("metro", "train") and not b.get("bookable")
        feasible = made_scheduled or (is_frequent_transit and b_actual["depart"] is not None)
        miss_by = -slack_min if not made_scheduled else 0

        out.append({
            "from_leg": a["n"], "to_leg": b["n"],
            "from_label": f"{a['operator']} → {a['to']}",
            "to_label": b["operator"],
            "scheduled_arrive": a["arrive"],
            "scheduled_depart": b["depart"],
            "actual_arrive": a_actual_arr.isoformat(),
            "actual_depart": b_actual["depart"].isoformat() if b_actual["depart"] else None,
            "walk_buffer_min": walk,
            "slack_min": slack_min,
            "feasible": feasible,
            "made_scheduled": made_scheduled,
            "miss_by_min": miss_by,
            "tight": 0 <= slack_min < MIN_TRANSFER_BUFFER_MIN,
            "shifted": b_actual["shifted"],
            "shifted_by_min": b_actual["shifted_by_min"],
            "recoverable": b_actual["shifted"] and b_actual["depart"] is not None,
            "recovery_note": (
                f"caught next {b.get('mode')} at {b_actual['depart'].strftime('%H:%M')}"
                if b_actual["shifted"] and b_actual["depart"] else None
            ),
        })
    return out


def _find_rebook(
    bookable_leg: dict,
    candidates: list[dict],
    earliest_dep: datetime,
    arrive_by: datetime,
) -> list[dict]:
    """Returns up to 3 later candidates from the same operator. Candidates
    that arrive after the user's arrive_by are still returned with a flag,
    so the user has the option to relax."""
    out = []
    for c in candidates:
        if c.get("operator") != bookable_leg.get("operator"):
            continue
        if c.get("departure_id") == bookable_leg.get("departure_id"):
            continue
        try:
            cd, ca = _iso(c["depart"]), _iso(c["arrive"])
        except (ValueError, KeyError):
            continue
        if cd < earliest_dep:
            continue
        out.append({
            "departure_id": c["departure_id"],
            "depart": c["depart"], "arrive": c["arrive"],
            "price_usd": c["price_usd"], "operator": c["operator"],
            "delay_vs_planned_min": int((cd - _iso(bookable_leg["depart"])).total_seconds() / 60),
            "extra_cost_vs_planned_usd": round(c["price_usd"] - bookable_leg["cost_usd"], 2),
            "violates_arrive_by": ca > arrive_by,
            "arrival_overrun_min": max(0, int((ca - arrive_by).total_seconds() / 60)),
        })
    out.sort(key=lambda x: (x["violates_arrive_by"], x["delay_vs_planned_min"]))
    return out[:3]


def analyze(plan: dict, intent: dict) -> dict:
    legs = plan.get("legs", [])
    if len(legs) < 2:
        return {"transitions": [], "bookable_catchable": True, "rebook_required": False}

    actual = _propagate(legs)
    transitions = _transitions(legs, actual)
    bookable = next((l for l in legs if l.get("bookable")), None)

    bookable_transition = None
    bookable_catchable = True
    miss_by_min = 0
    if bookable:
        bookable_transition = next(
            (t for t in transitions if t["to_leg"] == bookable["n"]), None
        )
        if bookable_transition:
            bookable_catchable = bookable_transition["made_scheduled"]
            miss_by_min = bookable_transition["miss_by_min"]

    rebook_options: list[dict] = []
    senso_policy = None
    if not bookable_catchable and bookable:
        senso_policy = senso.query_policy("FlixBus", "change_fee")
        last_actual = actual[legs[legs.index(bookable) - 1]["n"]]["arrive"]
        earliest = (last_actual or _iso(bookable["depart"])) + timedelta(minutes=WALK_TO_BUS_DECK_MIN)
        try:
            arrive_by = _iso(intent.get("arrive_by") or legs[-1]["arrive"])
        except (ValueError, TypeError):
            arrive_by = _iso(legs[-1]["arrive"])
        rebook_options = _find_rebook(
            bookable,
            (plan.get("intercity_comparison") or {}).get("candidates", []),
            earliest, arrive_by,
        )

    # Summary text
    upstream_shifts = [t for t in transitions
                       if t.get("shifted") and t.get("to_leg") != (bookable["n"] if bookable else None)]
    if bookable_catchable:
        if upstream_shifts:
            us = upstream_shifts[0]
            bs = bookable_transition["slack_min"] if bookable_transition else 0
            summary = (
                f"Leg {us['from_leg']} late → missed planned {us['to_label']} by "
                f"{us['miss_by_min']} min. {us['recovery_note']}. FlixBus still "
                f"catchable with {bs} min at the bus deck."
            )
        elif bookable_transition and bookable_transition["tight"]:
            summary = (
                f"Plan holds — FlixBus catchable with only "
                f"{bookable_transition['slack_min']} min at the bus deck. Tight."
            )
        else:
            bs = bookable_transition["slack_min"] if bookable_transition else "—"
            summary = f"All connections feasible. FlixBus has {bs} min of slack at the bus deck."
    else:
        cheapest = min(rebook_options, key=lambda o: o["price_usd"]) if rebook_options else None
        if cheapest:
            policy_first = (senso_policy or {}).get("answer", "").split(".")[0]
            overrun = (
                f"; arrives {cheapest['arrival_overrun_min']} min past arrive-by"
                if cheapest["violates_arrive_by"] else ""
            )
            summary = (
                f"FlixBus miss by {miss_by_min} min. Best rebook: "
                f"{cheapest['operator']} departing {cheapest['depart'][-8:-3]} "
                f"(+{cheapest['delay_vs_planned_min']} min, "
                f"{'+' if cheapest['extra_cost_vs_planned_usd'] >= 0 else '−'}$"
                f"{abs(cheapest['extra_cost_vs_planned_usd']):.2f}{overrun}). "
                f"Senso: {policy_first}."
            )
        else:
            summary = (
                f"FlixBus miss by {miss_by_min} min, and no later candidate "
                f"from any operator could be found. User must relax constraints."
            )

    return {
        "transitions": transitions,
        "bookable_leg_n": bookable["n"] if bookable else None,
        "bookable_catchable": bookable_catchable,
        "miss_by_min": miss_by_min,
        "rebook_required": not bookable_catchable,
        "rebook_options": rebook_options,
        "senso_policy": senso_policy,
        "summary": summary,
    }
