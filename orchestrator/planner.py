"""Builds the multi-leg NEC corridor plan.

Pipeline:
  1. Mode-selection reasoning (OpenAI) — decides which transport modes are
     viable for first/last mile and intercity given the intent's budget and
     constraints. Runs BEFORE any operator call.
  2. Operator queries (Nimble) for the live legs — WMATA, NJT, Lyft. The bus
     leg stays stubbed in Phase 2; Phase 3 will parallelize multiple operators.
  3. Itinerary assembly with the selected operators.

Mode selection runs in parallel with the operator calls — both have similar
latency so we hide the OpenAI cost.
"""
from __future__ import annotations
import asyncio
from orchestrator.intent import Intent
from orchestrator.modes import select_modes
from orchestrator.operators import compare_intercity
from integrations import nimble_lyft, wmata, njt, clickhouse_client


async def _leg1_drive() -> dict:
    return {
        "n": 1,
        "from": "Rockville, MD",
        "to": "Shady Grove Metro",
        "mode": "drive",
        "operator": "Self-drive",
        "depart": "2026-05-25T09:42:00",
        "arrive": "2026-05-25T10:00:00",
        "duration_min": 18,
        "cost_usd": 5.00,
        "bookable": False,
        "detail": "Park at Shady Grove garage · $5 day rate",
        "source": "static",
    }


async def _leg1_lyft() -> dict:
    est = await nimble_lyft.estimate("Rockville, MD", "Shady Grove Metro")
    return {
        "n": 1,
        "from": "Rockville, MD",
        "to": "Shady Grove Metro",
        "mode": "lyft",
        "operator": est["service"],
        "depart": "2026-05-25T09:35:00",
        "arrive": "2026-05-25T09:57:00",
        "duration_min": est["duration_min"],
        "cost_usd": est["cost_usd"],
        "bookable": False,
        "detail": f"ETA pickup {est['eta_pickup_min']} min · surge {est['surge_multiplier']}x",
        "swap_reason": "Driver opted out; live Lyft estimate.",
        "source": est.get("source", "cached"),
    }


async def _leg2() -> dict:
    t = await wmata.trip("Shady Grove", "Union Station")
    arrivals = t.get("next_trains_min", [])
    detail = (
        f"Next trains to Glenmont: {', '.join(str(m) + 'm' for m in arrivals[:3])} · tap-to-pay"
        if arrivals
        else "tap-to-pay"
    )
    return {
        "n": 2,
        "from": "Shady Grove",
        "to": "Union Station",
        "mode": "metro",
        "operator": f"WMATA {t['line']} Line",
        "depart": "2026-05-25T10:07:00",
        "arrive": "2026-05-25T10:45:00",
        "duration_min": t["duration_min"],
        "cost_usd": t["fare_usd"],
        "bookable": False,
        "detail": detail,
        "source": t.get("source", "cached"),
    }


_BUS_OPERATORS = {"FlixBus", "OurBus", "Vamoose"}


async def _leg3(intent: Intent) -> tuple[dict, dict]:
    """Returns (leg_dict, intercity_comparison_dict).

    Calls 4 operators in parallel, picks the winner per intent constraints,
    logs every candidate's price to ClickHouse for the corridor chart.
    """
    # Leg 2 (Metro) arrives Union Station 10:45; +5 min walk to bus deck.
    # Hardcoded for the demo since leg 2's schedule is fixed.
    from datetime import datetime as _dt
    earliest = _dt.fromisoformat("2026-05-25T10:50:00")
    comparison = await compare_intercity(intent, earliest_depart=earliest)
    winner = comparison["winner"]

    await clickhouse_client.record_prices([
        {
            "corridor": "WAS-NYC",
            "operator": c["operator"],
            "mode": "bus" if c["operator"] in _BUS_OPERATORS else "train",
            "price_usd": c["price_usd"],
            "depart": c["depart"],
            "source": "stub",
        }
        for c in comparison["candidates"]
    ])

    if winner is None:
        # No candidates at all — surface a placeholder so the rest of the
        # plan still renders. The UI will show the comparison panel with
        # the empty state.
        return ({
            "n": 3,
            "from": "—",
            "to": "—",
            "mode": "bus",
            "operator": "—",
            "depart": intent.arrive_by.isoformat(),
            "arrive": intent.arrive_by.isoformat(),
            "duration_min": 0,
            "cost_usd": 0.0,
            "bookable": False,
            "detail": "No intercity operator returned a candidate.",
            "source": "static",
        }, comparison)

    leg = {
        "n": 3,
        "from": winner["origin"],
        "to": winner["destination"],
        "mode": "bus" if winner["operator"] in _BUS_OPERATORS else "train",
        "operator": winner["operator"],
        "depart": winner["depart"],
        "arrive": winner["arrive"],
        "duration_min": winner["duration_min"],
        "cost_usd": winner["price_usd"],
        "bookable": winner["operator"] != "Amtrak NER",  # Amtrak booking is GDS-gated
        "departure_id": winner["departure_id"],
        "detail": (
            f"{winner.get('seats_left', 0)} seats left · "
            f"winner of {comparison['n_operators_queried']}-operator comparison "
            f"({comparison['n_viable']} viable)"
        ),
        "source": "static",
    }
    return leg, comparison


async def _leg4() -> dict:
    nec = await njt.northeast_corridor()
    deps = nec.get("next_departures", [])
    detail = (
        f"Next NEC departures from Newark: {', '.join(deps[:3])} · walk-up fare"
        if deps
        else "Walk-up fare"
    )
    return {
        "n": 4,
        "from": "Newark Penn Station",
        "to": "New York Penn Station",
        "mode": "train",
        "operator": f"{nec['operator']} {nec['line']}",
        "depart": "2026-05-25T15:36:00",
        "arrive": "2026-05-25T15:54:00",
        "duration_min": nec["duration_min"],
        "cost_usd": nec["fare_usd"],
        "bookable": False,
        "detail": detail,
        "source": nec.get("source", "cached"),
    }


async def plan(intent: Intent) -> dict:
    no_drive = "no_drive" in intent.constraints
    leg1 = _leg1_lyft() if no_drive else _leg1_drive()
    modes, l1, l2, leg3_pair, l4 = await asyncio.gather(
        select_modes(intent),
        leg1,
        _leg2(),
        _leg3(intent),
        _leg4(),
    )
    leg3, intercity_comparison = leg3_pair
    legs = [l1, l2, leg3, l4]
    total = round(sum(leg["cost_usd"] for leg in legs), 2)
    return {
        "intent": intent.model_dump(mode="json"),
        "modes": modes,
        "intercity_comparison": intercity_comparison,
        "legs": legs,
        "total_usd": total,
        "predicted_arrival": legs[-1]["arrive"],
        "within_budget": total <= intent.max_budget_usd,
        "phase": 3,
    }
