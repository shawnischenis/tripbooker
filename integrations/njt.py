"""NJ Transit via Nimble — scrapes DepartureVision for Newark Penn (NP).
Returns the next departures to New York Penn on the Northeast Corridor.
"""
from __future__ import annotations
import re
from integrations.nimble_client import extract, NimbleError

NJT_DV_PAGE = "https://www.njtransit.com/dv-to/NP"

# Per-station-pair stub schedule + fare. Keyed by destination station name.
# The NJT NEC line has frequent service (~12 trains/hr peak).
_OD_TABLE = {
    ("Newark Penn Station",  "New York Penn Station"): {
        "fare_usd": 5.75, "duration_min": 18,
        "stub_departures": ["15:18", "15:36", "15:54", "16:12", "16:30"],
    },
    ("Metuchen Station",      "New York Penn Station"): {
        "fare_usd": 14.00, "duration_min": 47,
        "stub_departures": ["14:30", "15:00", "15:30", "16:00", "16:30"],
    },
    ("Princeton Junction",    "New York Penn Station"): {
        "fare_usd": 17.50, "duration_min": 62,
        "stub_departures": ["14:21", "14:51", "15:21", "15:51", "16:21"],
    },
}
_DEFAULT_OD = ("Newark Penn Station", "New York Penn Station")

# Matches "**New York[ -SEC]**" followed within ~120 chars by "**HH:MM AM/PM**"
_NY_DEPARTURE = re.compile(
    r"\*\*New York[^\*]{0,40}\*\*[\s\S]{0,120}?\*\*(\d{1,2}:\d{2}\s*[AP]M)\*\*",
    re.IGNORECASE,
)


def _to_24h(t: str) -> str:
    """'2:10 PM' -> '14:10'. Fails open by returning the original on error."""
    try:
        time_part, ampm = re.split(r"\s+", t.strip())
        h, m = time_part.split(":")
        h = int(h) % 12
        if ampm.upper() == "PM":
            h += 12
        return f"{h:02d}:{m}"
    except (ValueError, IndexError):
        return t.strip()


def _parse_ny_departures(markdown: str) -> list[str]:
    seen: list[str] = []
    for raw in _NY_DEPARTURE.findall(markdown):
        t = _to_24h(raw)
        if t not in seen:
            seen.append(t)
    return seen


async def northeast_corridor(
    origin: str = "Newark Penn Station",
    destination: str = "New York Penn Station",
    after: str | None = None,
) -> dict:
    od = _OD_TABLE.get((origin, destination)) or _OD_TABLE[_DEFAULT_OD]
    base = {
        "origin": origin,
        "destination": destination,
        "operator": "NJ Transit",
        "line": "Northeast Corridor",
        "duration_min": od["duration_min"],
        "fare_usd": od["fare_usd"],
    }

    # Only the Newark→NY page maps cleanly to njtransit.com/dv-to/NP today;
    # other O/D pairs fall back to the stub schedule.
    if (origin, destination) != _DEFAULT_OD:
        return {**base, "next_departures": od["stub_departures"], "source": "cached"}

    try:
        result = await extract(
            NJT_DV_PAGE,
            render=True,
            render_options={"render_type": "idle0", "timeout": 20000},
        )
        md = result.get("data", {}).get("markdown", "")
        deps = _parse_ny_departures(md)
        if deps:
            return {**base, "next_departures": deps[:5], "source": "nimble"}
        return {**base, "next_departures": od["stub_departures"], "source": "nimble-partial"}
    except NimbleError as e:
        return {**base, "next_departures": od["stub_departures"], "source": "cached", "error": str(e)[:120]}
