"""Phase 3.2 — real Nimble Browser Agent visit to FlixBus during booking.

Loads the live FlixBus corridor page via Nimble Browser API, captures a
screenshot + the live "from $X.XX" price floor, and returns evidence the
demo can show ("the agent actually drove a real browser").

Why not a full headless checkout: FlixBus serves a GDPR consent modal
inside a Shadow DOM (Usercentrics CMP). Nimble's CSS-selector-based
browser_actions cannot pierce the shadow root, and the click action
does not accept pixel coordinates. The modal blocks every underlying
control until dismissed. A production deployment would either
(a) integrate FlixBus's partner booking API directly, or
(b) maintain a Usercentrics consent-bypass cookie via a headed browser
warmup. Both are out of hackathon scope.

The demo therefore returns booking_reference as a stub but pairs it with
real Nimble evidence — the booking decision and payment rail (CDP virtual
card + x402 settlement) are real; only the final FlixBus form submission
is simulated.
"""
from __future__ import annotations
import re
from integrations.nimble_client import extract, NimbleError

FLIXBUS_CORRIDOR_URL = "https://www.flixbus.com/bus/washington-dc/new-york-ny"


async def verify_and_screenshot(leg: dict) -> dict:
    """Load FlixBus corridor page, return live-data evidence + screenshot.

    Tolerant by design: every Nimble failure mode is caught and returns
    a dict with ok=False so /book can still proceed with its stub booking
    confirmation.
    """
    try:
        r = await extract(
            FLIXBUS_CORRIDOR_URL,
            render=True,
            render_options={"render_type": "idle0", "timeout": 22000},
            browser_actions=[
                {"wait": "2s"},
                {"screenshot": {}},
            ],
            formats=["markdown"],
            timeout=60,
        )
    except NimbleError as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }

    md = r.get("data", {}).get("markdown", "") or ""
    prices = re.findall(r"\$(\d+\.\d{2})", md)
    live_price_floor = min((float(p) for p in prices), default=None)

    screenshot_b64 = None
    ba = r.get("data", {}).get("browser_actions", {})
    for res in ba.get("results", []):
        if res.get("name") == "screenshot" and "result" in res:
            screenshot_b64 = res["result"]
            break

    return {
        "ok": True,
        "operator": "FlixBus",
        "departure_id": leg.get("departure_id"),
        "live_url": FLIXBUS_CORRIDOR_URL,
        "live_price_floor_usd": live_price_floor,
        "nimble_task_id": r.get("task_id"),
        "nimble_duration_ms": r.get("metadata", {}).get("query_duration"),
        "screenshot_b64": screenshot_b64,
        "note": (
            "Real Nimble Browser Agent visit completed. Screenshot captures live FlixBus page. "
            "Headless completion of checkout is blocked by GDPR consent modal in Shadow DOM; "
            "booking confirmation falls back to demo stub."
        ),
    }
