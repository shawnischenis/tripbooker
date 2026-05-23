"""O/D-aware multi-leg planner — Phase C.

Pipeline:
  1. Look up origin + destination in the catalog. Route through corridor.py
     to determine strategy (same_hub | njt_direct | compare_operators).
  2. Build the leg template sequence: first-mile + intercity + last-mile.
  3. Run mode-selection reasoning (OpenAI) in parallel with operator queries.
  4. Schedule legs backward from intent.arrive_by — each leg's depart/arrive
     is computed from its duration plus a transfer buffer.
  5. Log all bus quotes to ClickHouse; emit the final plan dict.

The legacy hardcoded Rockville→NYC plan is one specific path through this
pipeline; everything else (Metuchen→NYC single-leg, DC→NYC three-leg, etc.)
falls out for free.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from orchestrator.intent import Intent
from orchestrator.modes import select_modes
from orchestrator.catalog import LEG_LIBRARY, get_leg
from orchestrator.corridor import plan_route
from orchestrator.operators import compare_intercity
from integrations import wmata, njt, nimble_lyft, clickhouse_client

# Minimum buffer at any non-bookable platform transfer
_TRANSFER_BUFFER_MIN = 5
# Extra buffer before stepping onto a bookable intercity vehicle
_BOOKABLE_BOARDING_BUFFER_MIN = 10
_BUS_OPERATORS = {"FlixBus", "OurBus", "Vamoose"}


def _schedule_backward(templates: list[dict], arrive_by: datetime) -> list[dict]:
    """Assign depart/arrive to each leg, working backward from arrive_by.
    Bookable legs get a larger boarding buffer in front of them."""
    legs = []
    current = arrive_by
    for tpl in reversed(templates):
        dur = tpl.get("duration_min", 0)
        leg = {**tpl}
        leg["arrive"] = current.isoformat()
        depart_dt = current - timedelta(minutes=dur)
        leg["depart"] = depart_dt.isoformat()
        legs.append(leg)
        buffer = _BOOKABLE_BOARDING_BUFFER_MIN if tpl.get("bookable") else _TRANSFER_BUFFER_MIN
        current = depart_dt - timedelta(minutes=buffer)
    legs.reverse()
    for i, leg in enumerate(legs, start=1):
        leg["n"] = i
        leg.setdefault("source", "static")
    return legs


# ─── per-strategy leg builders ──────────────────────────────────────────────
async def _build_legs_njt_direct(route: dict, intent: Intent) -> tuple[list[dict], dict | None]:
    """Single NJT NEC ride between two on-line hubs (e.g. Metuchen → NY Penn)."""
    o_hub, d_hub = route["origin_hub"], route["destination_hub"]
    fare_info = await njt.northeast_corridor(o_hub, d_hub)

    # Mint an intercity NJT leg template on the fly using the live fare lookup.
    njt_leg = {
        "from": o_hub, "to": d_hub,
        "mode": "train",
        "operator": f"{fare_info['operator']} {fare_info['line']}",
        "duration_min": fare_info["duration_min"],
        "cost_usd": fare_info["fare_usd"],
        "bookable": False,
        "detail": f"Next departures: {', '.join(fare_info.get('next_departures', [])[:3])} · walk-up fare",
        "source": fare_info.get("source", "cached"),
    }

    templates = (
        [get_leg(k) for k in route["to_hub_keys"]]
        + [njt_leg]
        + [get_leg(k) for k in route["from_hub_keys"]]
    )
    return templates, None


async def _build_legs_compare_operators(route: dict, intent: Intent) -> tuple[list[dict], dict]:
    """First-mile + intercity (bus/train compared) + (optional bridge) + last-mile."""
    o_hub, d_hub = route["origin_hub"], route["destination_hub"]

    # Earliest intercity departure depends on how long the first-mile takes.
    first_mile_total = sum(LEG_LIBRARY[k]["duration_min"] for k in route["to_hub_keys"])
    # Earliest is "as late as possible given arrive_by minus everything after intercity"
    # but for the comparison filter we just need a sane lower bound — anchor on the demo's
    # 10:50 (Metro arrival + walk) which is the legacy reference.
    earliest = datetime.fromisoformat("2026-05-25T10:50:00")
    comparison = await compare_intercity(intent, earliest_depart=earliest)
    winner = comparison["winner"]

    # Log all candidates to CH
    await clickhouse_client.record_prices([
        {"corridor": f"{o_hub[:3]}-{d_hub[:3]}", "operator": c["operator"],
         "mode": "bus" if c["operator"] in _BUS_OPERATORS else "train",
         "price_usd": c["price_usd"], "depart": c["depart"], "source": "stub"}
        for c in comparison["candidates"]
    ])

    if winner is None:
        # Fallback: empty intercity placeholder so the rest renders
        intercity_legs = [{
            "from": o_hub, "to": d_hub, "mode": "bus", "operator": "—",
            "duration_min": 0, "cost_usd": 0.0, "bookable": False,
            "detail": "No intercity option returned.",
        }]
    else:
        intercity_leg = {
            "from": winner["origin"], "to": winner["destination"],
            "mode": "bus" if winner["operator"] in _BUS_OPERATORS else "train",
            "operator": winner["operator"],
            "duration_min": winner["duration_min"],
            "cost_usd": winner["price_usd"],
            "bookable": winner["operator"] != "Amtrak NER",
            "departure_id": winner["departure_id"],
            "detail": (
                f"{winner.get('seats_left', 0)} seats left · "
                f"winner of {comparison['n_operators_queried']}-operator comparison "
                f"({comparison['n_viable']} viable)"
            ),
        }

        intercity_legs = [intercity_leg]

        # Bridge leg if the intercity drops us at a different hub than dest_hub.
        # For the DC→NY case, FlixBus terminates at Newark Penn while destination
        # hub is NY Penn → add an NJT NEC bridge.
        if winner["destination"] != d_hub:
            bridge = await njt.northeast_corridor(winner["destination"], d_hub)
            intercity_legs.append({
                "from": winner["destination"], "to": d_hub,
                "mode": "train",
                "operator": f"{bridge['operator']} {bridge['line']}",
                "duration_min": bridge["duration_min"],
                "cost_usd": bridge["fare_usd"],
                "bookable": False,
                "detail": f"Next departures: {', '.join(bridge.get('next_departures', [])[:3])} · walk-up fare",
                "source": bridge.get("source", "cached"),
            })

    templates = (
        [get_leg(k) for k in route["to_hub_keys"]]
        + intercity_legs
        + [get_leg(k) for k in route["from_hub_keys"]]
    )
    return templates, comparison


async def _build_legs_same_hub(route: dict, intent: Intent) -> tuple[list[dict], None]:
    """Just first-mile + last-mile, no intercity. Edge case."""
    templates = (
        [get_leg(k) for k in route["to_hub_keys"]]
        + [get_leg(k) for k in route["from_hub_keys"]]
    )
    return templates, None


# ─── Lyft live-estimate substitution (when no_drive flips first-mile to lyft) ──
async def _apply_lyft_live(legs: list[dict]) -> list[dict]:
    """If any leg has mode=lyft, swap its cost/duration with a live estimate."""
    if not any(l.get("mode") == "lyft" for l in legs):
        return legs
    est = await nimble_lyft.estimate()
    out = []
    for l in legs:
        if l.get("mode") == "lyft":
            l = {**l, "cost_usd": est["cost_usd"], "duration_min": est["duration_min"],
                 "detail": f"ETA pickup {est['eta_pickup_min']} min · surge {est['surge_multiplier']}x",
                 "source": est.get("source", "cached")}
            if est.get("error"):
                l["error"] = est["error"]
        out.append(l)
    return out


async def _apply_metro_live(legs: list[dict]) -> list[dict]:
    """Refresh metro leg detail string with live WMATA arrivals (if present)."""
    if not any(l.get("mode") == "metro" for l in legs):
        return legs
    info = await wmata.trip()
    out = []
    for l in legs:
        if l.get("mode") == "metro":
            arrivals = info.get("next_trains_min", [])
            detail = (
                f"Next trains to Glenmont: {', '.join(str(m) + 'm' for m in arrivals[:3])} · tap-to-pay"
                if arrivals else l.get("detail", "tap-to-pay")
            )
            l = {**l, "detail": detail, "source": info.get("source", "cached")}
        out.append(l)
    return out


# ─── Top-level entry point ──────────────────────────────────────────────────
async def plan(intent: Intent) -> dict:
    no_drive = "no_drive" in intent.constraints
    route = plan_route(intent.origin, intent.destination, no_drive)

    if not route["valid"]:
        return {
            "intent": intent.model_dump(mode="json"),
            "error": route["reason"],
            "legs": [],
            "total_usd": 0.0,
            "within_budget": True,
            "predicted_arrival": intent.arrive_by.isoformat(),
            "modes": None,
            "intercity_comparison": None,
            "phase": "C",
        }

    # Strategy dispatch (intercity work happens in parallel with mode reasoning)
    if route["strategy"] == "njt_direct":
        leg_task = _build_legs_njt_direct(route, intent)
    elif route["strategy"] == "compare_operators":
        leg_task = _build_legs_compare_operators(route, intent)
    else:
        leg_task = _build_legs_same_hub(route, intent)

    route_hint = {
        "origin_hub": route["origin_hub"],
        "destination_hub": route["destination_hub"],
        "strategy": route["strategy"],
    }
    modes, (templates, comparison) = await asyncio.gather(
        select_modes(intent, route_hint),
        leg_task,
    )

    # Substitute live data on legs that have a corresponding integration
    templates = await _apply_lyft_live(templates)
    templates = await _apply_metro_live(templates)

    legs = _schedule_backward(templates, intent.arrive_by)
    total = round(sum(l["cost_usd"] for l in legs), 2)

    return {
        "intent": intent.model_dump(mode="json"),
        "route": {
            "strategy": route["strategy"],
            "origin_hub": route["origin_hub"],
            "destination_hub": route["destination_hub"],
            "leg_count": len(legs),
        },
        "modes": modes,
        "intercity_comparison": comparison,
        "legs": legs,
        "total_usd": total,
        "predicted_arrival": legs[-1]["arrive"] if legs else intent.arrive_by.isoformat(),
        "within_budget": total <= intent.max_budget_usd,
        "phase": "C",
    }
