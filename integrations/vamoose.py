"""Vamoose Bus departures. Phase 3 stub.

Vamoose runs Bethesda/Arlington/Lorton ↔ Manhattan (slightly different DC
boarding points than FlixBus/OurBus). Premium positioning, modestly higher
price.
"""
from __future__ import annotations


def find_departures(
    origin: str = "Washington DC Union Station",
    destination: str = "New York Penn Station",
    date: str = "2026-05-25",
) -> list[dict]:
    return [
        {
            "departure_id": "VAMOOSE-2026-05-25-0830",
            "origin": "Bethesda, MD",
            "destination": "Midtown Manhattan, NY",
            "depart": f"{date}T08:30:00",
            "arrive": f"{date}T12:30:00",
            "duration_min": 240,
            "price_usd": 34.00,
            "operator": "Vamoose",
            "seats_left": 12,
        },
        {
            "departure_id": "VAMOOSE-2026-05-25-1115",
            "origin": "Bethesda, MD",
            "destination": "Midtown Manhattan, NY",
            "depart": f"{date}T11:15:00",
            "arrive": f"{date}T15:15:00",
            "duration_min": 240,
            "price_usd": 34.99,
            "operator": "Vamoose",
            "seats_left": 18,
        },
        {
            "departure_id": "VAMOOSE-2026-05-25-1400",
            "origin": "Bethesda, MD",
            "destination": "Midtown Manhattan, NY",
            "depart": f"{date}T14:00:00",
            "arrive": f"{date}T18:00:00",
            "duration_min": 240,
            "price_usd": 36.99,
            "operator": "Vamoose",
            "seats_left": 22,
        },
    ]


def book(departure_id: str, passenger: dict, payment_token: str) -> dict:
    return {
        "status": "stubbed",
        "operator": "Vamoose",
        "departure_id": departure_id,
        "booking_reference": f"VM-{departure_id.split('-')[-1]}",
        "total_charged_usd": 0.0,
        "passenger": passenger,
        "note": "Real Nimble Browser Agent checkout lands in Phase 3.2.",
    }
