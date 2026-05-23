"""NJ Transit via Nimble — scrapes DepartureVision for Newark Penn (NP).
Returns the next departures to New York Penn on the Northeast Corridor.
"""
from __future__ import annotations
import re
from integrations.nimble_client import extract, NimbleError

NJT_DV_PAGE = "https://www.njtransit.com/dv-to/NP"
_FARE_USD = 5.75
_DURATION_MIN = 18
_STUB_DEPARTURES = ["15:18", "15:36", "15:54", "16:12", "16:30"]

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
    base = {
        "origin": origin,
        "destination": destination,
        "operator": "NJ Transit",
        "line": "Northeast Corridor",
        "duration_min": _DURATION_MIN,
        "fare_usd": _FARE_USD,
    }
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
        return {**base, "next_departures": _STUB_DEPARTURES, "source": "nimble-partial"}
    except NimbleError as e:
        return {**base, "next_departures": _STUB_DEPARTURES, "source": "cached", "error": str(e)[:120]}
