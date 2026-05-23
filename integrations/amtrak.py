"""Amtrak Northeast Regional departures. Phase 3 stub.

Real Amtrak booking is gated through GDS partners (~6 months acquisition per
SPEC). This module surfaces Amtrak NER pricing into the comparison so the
agent visibly considers it — most plans with tight budgets will see NER
priced out and the agent will pick a bus operator instead.
"""
from __future__ import annotations


def find_departures(
    origin: str = "Washington Union Station",
    destination: str = "New York Penn Station",
    date: str = "2026-05-25",
) -> list[dict]:
    return [
        {
            "departure_id": "AMTRAK-NER-167",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T09:35:00",
            "arrive": f"{date}T13:05:00",
            "duration_min": 210,
            "price_usd": 89.00,
            "operator": "Amtrak NER",
            "seats_left": 47,
        },
        {
            "departure_id": "AMTRAK-NER-179",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T10:50:00",
            "arrive": f"{date}T14:25:00",
            "duration_min": 215,
            "price_usd": 99.00,
            "operator": "Amtrak NER",
            "seats_left": 12,
        },
        {
            "departure_id": "AMTRAK-NER-183",
            "origin": origin,
            "destination": destination,
            "depart": f"{date}T13:00:00",
            "arrive": f"{date}T16:30:00",
            "duration_min": 210,
            "price_usd": 109.00,
            "operator": "Amtrak NER",
            "seats_left": 26,
        },
    ]


def book(departure_id: str, passenger: dict, payment_token: str) -> dict:
    # Real Amtrak booking is GDS-gated; we cannot complete a checkout via
    # Nimble Browser Agent. This stub exists so the comparison flow is
    # symmetric across operators.
    return {
        "status": "unsupported",
        "operator": "Amtrak NER",
        "departure_id": departure_id,
        "booking_reference": None,
        "total_charged_usd": 0.0,
        "passenger": passenger,
        "note": "Amtrak booking requires GDS partner access (out of demo scope).",
    }
