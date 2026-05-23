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
from integrations import nimble_lyft, nimble_flixbus, wmata, njt, clickhouse_client


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


async def _leg3() -> dict:
    options = nimble_flixbus.find_departures()
    chosen = options[1]
    # Log every departure quote we see so the corridor price-history chart
    # accumulates over time. Stub for now; Phase 3 swaps in live Nimble pricing.
    await clickhouse_client.record_prices([
        {
            "corridor": "WAS-EWR",
            "operator": opt["operator"],
            "mode": "bus",
            "price_usd": opt["price_usd"],
            "depart": opt["depart"],
            "source": "stub",
        }
        for opt in options
    ])
    return {
        "n": 3,
        "from": "Washington DC Union Station",
        "to": "Newark Penn Station",
        "mode": "bus",
        "operator": chosen["operator"],
        "depart": chosen["depart"],
        "arrive": chosen["arrive"],
        "duration_min": chosen["duration_min"],
        "cost_usd": chosen["price_usd"],
        "bookable": True,
        "departure_id": chosen["departure_id"],
        "detail": f"{chosen['seats_left']} seats left · this is the real booking",
        "source": "static",
    }


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
    modes, *legs = await asyncio.gather(
        select_modes(intent),
        leg1,
        _leg2(),
        _leg3(),
        _leg4(),
    )
    total = round(sum(leg["cost_usd"] for leg in legs), 2)
    return {
        "intent": intent.model_dump(mode="json"),
        "modes": modes,
        "legs": legs,
        "total_usd": total,
        "predicted_arrival": legs[-1]["arrive"],
        "within_budget": total <= intent.max_budget_usd,
        "phase": 2,
    }
