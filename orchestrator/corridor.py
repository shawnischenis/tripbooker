"""Corridor routing — decides what intercity strategy applies to a trip.

Three strategies:
  - same_hub:         origin and destination share a hub; no intercity leg
  - njt_direct:       both hubs are on NJ Transit Northeast Corridor; single
                      NJT train ride between them
  - compare_operators: full bus-vs-train operator comparison (FlixBus, OurBus,
                      Vamoose, Amtrak NER); may need a destination-side bridge
                      leg if the winning operator's terminal differs from the
                      destination hub.
"""
from __future__ import annotations
from typing import Literal
from orchestrator.catalog import (
    CITIES, NJT_NEC_HUBS, AMTRAK_NER_HUBS, FLIXBUS_HUBS, get_city,
)

Strategy = Literal["same_hub", "njt_direct", "compare_operators", "invalid"]


def plan_route(origin: str, destination: str, no_drive: bool) -> dict:
    o = get_city(origin)
    d = get_city(destination)

    if not o:
        return {"valid": False, "reason": f"Unsupported origin '{origin}'. "
                f"Supported: {', '.join(sorted(CITIES.keys()))}"}
    if not d:
        return {"valid": False, "reason": f"Unsupported destination '{destination}'. "
                f"Supported: {', '.join(sorted(CITIES.keys()))}"}
    if "to_hub_drive" not in o:
        return {"valid": False, "reason": f"'{origin}' is a destination-only city in the catalog."}
    if "from_hub" not in d:
        return {"valid": False, "reason": f"'{destination}' is an origin-only city in the catalog."}

    o_hub = o["hub"]
    d_hub = d["hub"]

    to_hub_keys = o["to_hub_no_drive"] if no_drive else o["to_hub_drive"]
    from_hub_keys = d.get("from_hub") or []

    if o_hub == d_hub:
        strategy: Strategy = "same_hub"
    elif o_hub in NJT_NEC_HUBS and d_hub in NJT_NEC_HUBS:
        strategy = "njt_direct"
    elif (o_hub in FLIXBUS_HUBS or o_hub in AMTRAK_NER_HUBS):
        strategy = "compare_operators"
    else:
        return {"valid": False, "reason": f"No intercity service known between {o_hub} and {d_hub}"}

    return {
        "valid": True,
        "origin": origin,
        "destination": destination,
        "origin_hub": o_hub,
        "destination_hub": d_hub,
        "to_hub_keys": to_hub_keys,
        "from_hub_keys": from_hub_keys,
        "strategy": strategy,
    }
