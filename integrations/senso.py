"""Senso policy knowledge base. Phase 1 stub.

Ingests refund/change policies + cancellation procedures and answers
ground-truth queries before the agent commits to a non-refundable fare
or proposes a rebooking.
"""
from __future__ import annotations


def query_policy(operator: str, topic: str) -> dict:
    canned = {
        ("FlixBus", "change_fee"): {
            "operator": "FlixBus",
            "topic": "change_fee",
            "answer": "Departure changes are free up to 15 minutes before departure if rebooking to the same route. New fare difference applies.",
            "citation": "FlixBus Terms of Carriage §6.2",
        },
        ("FlixBus", "cancellation"): {
            "operator": "FlixBus",
            "topic": "cancellation",
            "answer": "Vouchers issued up to 15 minutes before departure. No cash refunds on basic fare.",
            "citation": "FlixBus Terms of Carriage §7.1",
        },
        ("NJ Transit", "refund"): {
            "operator": "NJ Transit",
            "topic": "refund",
            "answer": "Unused one-way tickets refundable within 60 days minus $10 processing fee.",
            "citation": "NJT Tariff 8 §11",
        },
    }
    return canned.get(
        (operator, topic),
        {
            "operator": operator,
            "topic": topic,
            "answer": "No policy on file. Stub mode.",
            "citation": None,
        },
    )
