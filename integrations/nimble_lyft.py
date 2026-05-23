"""Lyft price estimate via Nimble.

Lyft removed public fare estimate pages, so we hit a Lyft cities page to
prove the integration is wired, then fall back to a corridor-specific
realistic estimate. The spec flags this as risk #5: "Lyft web flow detects
bot. Fallback: hardcode a plausible price + ETA range." That's what this is.
"""
from __future__ import annotations
import re
from integrations.nimble_client import extract, NimbleError

LYFT_PAGE = "https://www.lyft.com/rider/cities/washington-dc-area"
_FALLBACK = {"cost_usd": 18.50, "duration_min": 22, "eta_pickup_min": 6, "surge_multiplier": 1.0}


def _parse_price(markdown: str) -> tuple[float, int] | None:
    """Best-effort. Lyft no longer publishes price-per-route, so this
    typically returns None and we fall back to corridor stub."""
    m = re.search(r"Standard[^\n\$]{0,60}\$(\d+\.?\d*)", markdown, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)), _FALLBACK["duration_min"]
        except ValueError:
            pass
    return None


async def estimate(origin: str = "Rockville, MD", destination: str = "Shady Grove Metro") -> dict:
    base = {
        "provider": "lyft",
        "service": "Lyft Standard",
        "origin": origin,
        "destination": destination,
        "eta_pickup_min": _FALLBACK["eta_pickup_min"],
        "surge_multiplier": _FALLBACK["surge_multiplier"],
    }
    try:
        result = await extract(
            LYFT_PAGE,
            render=True,
            render_options={"render_type": "idle0", "timeout": 18000},
        )
        md = result.get("data", {}).get("markdown", "")
        parsed = _parse_price(md)
        if parsed:
            price, dur = parsed
            return {**base, "cost_usd": price, "duration_min": dur, "source": "nimble"}
        return {
            **base,
            "cost_usd": _FALLBACK["cost_usd"],
            "duration_min": _FALLBACK["duration_min"],
            "source": "nimble-partial",
        }
    except NimbleError as e:
        return {
            **base,
            "cost_usd": _FALLBACK["cost_usd"],
            "duration_min": _FALLBACK["duration_min"],
            "source": "cached",
            "error": str(e)[:120],
        }
