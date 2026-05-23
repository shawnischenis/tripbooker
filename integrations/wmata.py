"""WMATA Metro via Nimble — scrapes the live PIDS widget on the Shady Grove
station page. Returns the same shape as the Phase 1 stub plus a `source` field
so callers can distinguish live vs cached data.
"""
from __future__ import annotations
import re
from integrations.nimble_client import extract, NimbleError

WMATA_PAGE = "https://www.wmata.com/rider-guide/stations/shady-grove.cfm"
_FARE_USD = 3.85
_DURATION_TO_UNION = 38
_STUB_TRAINS = [4, 12, 20, 28]


def _parse_glenmont_arrivals(markdown: str) -> list[int]:
    return [int(m) for m in re.findall(r"Glenmont\s*(\d+)\s*min", markdown, re.IGNORECASE)]


async def trip(origin: str = "Shady Grove", destination: str = "Union Station") -> dict:
    base = {
        "origin": origin,
        "destination": destination,
        "line": "Red",
        "duration_min": _DURATION_TO_UNION,
        "fare_usd": _FARE_USD,
        "transfers": 0,
    }
    try:
        result = await extract(
            WMATA_PAGE,
            render=True,
            render_options={"render_type": "idle0", "timeout": 20000},
        )
        md = result.get("data", {}).get("markdown", "")
        arrivals = _parse_glenmont_arrivals(md)
        if arrivals:
            return {**base, "next_trains_min": arrivals[:5], "source": "nimble"}
        return {**base, "next_trains_min": _STUB_TRAINS, "source": "nimble-partial"}
    except NimbleError as e:
        return {**base, "next_trains_min": _STUB_TRAINS, "source": "cached", "error": str(e)[:120]}


async def next_trains(station: str = "Shady Grove", direction: str = "Glenmont") -> dict:
    t = await trip(station, "Union Station")
    return {
        "station": station,
        "line": "Red",
        "direction": direction,
        "next_trains_min": t.get("next_trains_min", _STUB_TRAINS),
        "fare_usd": t["fare_usd"],
        "duration_to_union_min": t["duration_min"],
        "source": t.get("source", "cached"),
    }
