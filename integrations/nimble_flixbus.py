"""FlixBus checkout via Nimble Browser Agent. Phase 1 stub."""
from __future__ import annotations


def find_departures(
    origin: str = "Washington DC Union Station",
    destination: str = "Newark Penn Station",
    date: str = "2026-05-25",
) -> list[dict]:
    return [
        {
            "departure_id": "FLX-2026-05-25-0800",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T08:00:00",
            "arrive": f"{date}T12:15:00",
            "duration_min": 255,
            "price_usd": 24.99,
            "operator": "FlixBus",
            "seats_left": 18,
        },
        {
            "departure_id": "FLX-2026-05-25-1100",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T11:00:00",
            "arrive": f"{date}T15:15:00",
            "duration_min": 255,
            "price_usd": 29.99,
            "operator": "FlixBus",
            "seats_left": 9,
        },
        {
            "departure_id": "FLX-2026-05-25-1400",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T14:00:00",
            "arrive": f"{date}T18:15:00",
            "duration_min": 255,
            "price_usd": 27.99,
            "operator": "FlixBus",
            "seats_left": 22,
        },
    ]


def book(departure_id: str, passenger: dict, payment_token: str) -> dict:
    return {
        "status": "stubbed",
        "departure_id": departure_id,
        "booking_reference": "PHASE1-STUB",
        "total_charged_usd": 0.0,
        "passenger": passenger,
        "note": "Real Nimble booking lands in Phase 3.",
    }
