"""OurBus departures. Phase 3 stub.

Same shape as nimble_flixbus.find_departures. Real Nimble Browser Agent
scrape of https://www.ourbus.com/transit/washington-dc-bus-to-new-york-ny
is Phase 3.2 work.
"""
from __future__ import annotations


def find_departures(
    origin: str = "Washington DC Union Station",
    destination: str = "New York Penn Station",
    date: str = "2026-05-25",
) -> list[dict]:
    return [
        {
            "departure_id": "OURBUS-2026-05-25-0745",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T07:45:00",
            "arrive": f"{date}T11:55:00",
            "duration_min": 250,
            "price_usd": 32.99,
            "operator": "OurBus",
            "seats_left": 14,
        },
        {
            "departure_id": "OURBUS-2026-05-25-1045",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T10:45:00",
            "arrive": f"{date}T14:55:00",
            "duration_min": 250,
            "price_usd": 34.99,
            "operator": "OurBus",
            "seats_left": 21,
        },
        {
            "departure_id": "OURBUS-2026-05-25-1330",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T13:30:00",
            "arrive": f"{date}T17:40:00",
            "duration_min": 250,
            "price_usd": 31.99,
            "operator": "OurBus",
            "seats_left": 8,
        },
    ]


def book(departure_id: str, passenger: dict, payment_token: str) -> dict:
    return {
        "status": "stubbed",
        "operator": "OurBus",
        "departure_id": departure_id,
        "booking_reference": f"OB-{departure_id.split('-')[-1]}",
        "total_charged_usd": 0.0,
        "passenger": passenger,
        "note": "Real Nimble Browser Agent checkout lands in Phase 3.2.",
    }
