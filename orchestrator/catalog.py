"""NEC corridor catalog — drives O/D-aware planning.

Each supported city has:
  - hub: the NEC intercity station it's served by
  - first_mile_drive / first_mile_no_drive: the sequence of leg-templates to
    reach that hub
  - last_mile: legs to get from the destination hub to the final destination

LEG_LIBRARY holds the reusable per-leg shapes — mode, operator, duration_min,
cost_usd, detail, from, to. The planner assigns depart/arrive at scheduling
time so the same template can be used outbound or in different sub-trips.

NJT_NEC_HUBS / FLIXBUS_HUBS / AMTRAK_NER_HUBS define which intercity
strategies are valid for a given O/D-hub pair.
"""
from __future__ import annotations

# ─── Leg-template library ────────────────────────────────────────────────────
LEG_LIBRARY: dict[str, dict] = {
    # — DC area ↦ Union Station —
    "drive:rockville→shadygrove": {
        "from": "Rockville, MD", "to": "Shady Grove Metro",
        "mode": "drive", "operator": "Self-drive",
        "duration_min": 18, "cost_usd": 5.00, "bookable": False,
        "detail": "Park at Shady Grove garage · $5 day rate",
    },
    "lyft:rockville→shadygrove": {
        "from": "Rockville, MD", "to": "Shady Grove Metro",
        "mode": "lyft", "operator": "Lyft Standard",
        "duration_min": 22, "cost_usd": 18.50, "bookable": False,
        "detail": "ETA pickup 6 min · surge 1.0x",
        "swap_reason": "Driver opted out; live Lyft estimate.",
    },
    "metro:shadygrove→union": {
        "from": "Shady Grove", "to": "Washington Union Station",
        "mode": "metro", "operator": "WMATA Red Line",
        "duration_min": 38, "cost_usd": 3.85, "bookable": False,
        "detail": "Red Line southbound · tap-to-pay",
    },
    "walk:dc→union": {
        "from": "Washington, DC", "to": "Washington Union Station",
        "mode": "walk", "operator": "Walk",
        "duration_min": 10, "cost_usd": 0.00, "bookable": False,
        "detail": "Downtown DC to Union Station",
    },
    # — NEC on-line cities ↦ their NJT NEC station —
    "walk:metuchen→station": {
        "from": "Metuchen, NJ", "to": "Metuchen Station",
        "mode": "walk", "operator": "Walk",
        "duration_min": 8, "cost_usd": 0.00, "bookable": False,
        "detail": "Downtown Metuchen to NEC platform",
    },
    "walk:princeton→junction": {
        "from": "Princeton, NJ", "to": "Princeton Junction",
        "mode": "shuttle", "operator": "Dinky shuttle + walk",
        "duration_min": 15, "cost_usd": 3.25, "bookable": False,
        "detail": "Dinky train to Princeton Jct",
    },
    "walk:newark→penn": {
        "from": "Newark, NJ", "to": "Newark Penn Station",
        "mode": "walk", "operator": "Walk",
        "duration_min": 6, "cost_usd": 0.00, "bookable": False,
        "detail": "Downtown Newark to Penn Station",
    },
    "walk:philadelphia→30th": {
        "from": "Philadelphia, PA", "to": "Philadelphia 30th St Station",
        "mode": "walk", "operator": "Walk / SEPTA",
        "duration_min": 12, "cost_usd": 0.00, "bookable": False,
        "detail": "Center City to 30th St",
    },
    # — Destination-side: NEC hub → final destination —
    "njt:newark→nypenn": {
        "from": "Newark Penn Station", "to": "New York Penn Station",
        "mode": "train", "operator": "NJ Transit Northeast Corridor",
        "duration_min": 18, "cost_usd": 5.75, "bookable": False,
        "detail": "Walk-up fare · TVM at platform",
    },
    "walk:nypenn→nyc": {
        "from": "New York Penn Station", "to": "New York, NY",
        "mode": "walk", "operator": "Walk",
        "duration_min": 5, "cost_usd": 0.00, "bookable": False,
        "detail": "Exit to 7th/8th Ave · subway/cab available",
    },
    "walk:southstation→boston": {
        "from": "Boston South Station", "to": "Boston, MA",
        "mode": "walk", "operator": "Walk",
        "duration_min": 8, "cost_usd": 0.00, "bookable": False,
        "detail": "Exit to Atlantic Ave · T available",
    },
}


# ─── City catalog ────────────────────────────────────────────────────────────
CITIES: dict[str, dict] = {
    # Origins are restricted to pairs that produce coherent end-to-end plans
    # under the current operator stubs:
    #   - Rockville, DC → use the DC↔NY FlixBus corridor (compare_operators)
    #   - Princeton, Metuchen, Newark → direct NJT NEC ride (njt_direct)
    # Philadelphia is excluded for now because the FlixBus stub returns
    # DC-origin departures regardless of the requested corridor, so the
    # rendered plan's intercity leg would not match Philly's hub.
    # Boston as a destination is excluded for the same reason (no operator
    # stub serves it yet).
    "Rockville, MD": {
        "hub": "Washington Union Station",
        "to_hub_drive":    ["drive:rockville→shadygrove", "metro:shadygrove→union"],
        "to_hub_no_drive": ["lyft:rockville→shadygrove",  "metro:shadygrove→union"],
    },
    "Washington, DC": {
        "hub": "Washington Union Station",
        "to_hub_drive":    ["walk:dc→union"],
        "to_hub_no_drive": ["walk:dc→union"],
    },
    "Princeton, NJ": {
        "hub": "Princeton Junction",
        "to_hub_drive":    ["walk:princeton→junction"],
        "to_hub_no_drive": ["walk:princeton→junction"],
    },
    "Metuchen, NJ": {
        "hub": "Metuchen Station",
        "to_hub_drive":    ["walk:metuchen→station"],
        "to_hub_no_drive": ["walk:metuchen→station"],
    },
    "Newark, NJ": {
        "hub": "Newark Penn Station",
        "to_hub_drive":    ["walk:newark→penn"],
        "to_hub_no_drive": ["walk:newark→penn"],
    },
    "New York, NY": {
        "hub": "New York Penn Station",
        "from_hub": ["walk:nypenn→nyc"],
    },
}

# ─── Intercity service maps ──────────────────────────────────────────────────
# Hubs served by NJ Transit Northeast Corridor line (direct one-seat ride)
NJT_NEC_HUBS = {
    "Trenton Transit Center",
    "Princeton Junction",
    "Metuchen Station",
    "Newark Penn Station",
    "New York Penn Station",
}

# Hubs served by Amtrak Northeast Regional
AMTRAK_NER_HUBS = {
    "Washington Union Station",
    "Baltimore Penn Station",
    "Wilmington",
    "Philadelphia 30th St Station",
    "Newark Penn Station",
    "New York Penn Station",
    "Stamford",
    "New Haven Union",
    "Boston South Station",
}

# Hubs FlixBus serves — limited to the demo's DC↔Newark corridor
FLIXBUS_HUBS = {
    "Washington Union Station",
    "Newark Penn Station",
}


def supported_origins() -> list[str]:
    """Cities that can be used as an origin (have to_hub_* legs)."""
    return [name for name, c in CITIES.items() if "to_hub_drive" in c]


def supported_destinations() -> list[str]:
    """Cities that can be used as a destination (have from_hub legs or are at a terminal)."""
    return [name for name, c in CITIES.items() if "from_hub" in c]


def get_city(name: str) -> dict | None:
    return CITIES.get(name)


def get_leg(key: str) -> dict:
    return {**LEG_LIBRARY[key]}
