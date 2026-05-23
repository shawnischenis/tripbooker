"""Receipt builder — turn a plan + booking + settlement into a per-step
payable summary the user can read at a glance.

Three payer categories:
  - user_direct:    pays at-time of travel (parking, metro tap, walk-up train ticket)
  - user_via_agent: the agent prepays with its virtual card, user reimburses
                    via x402 along with the agent fee (currently just the bus leg)
  - agent_fee:      the railpass service fee, settled via x402 on Base Sepolia
"""
from __future__ import annotations

# Per-mode payment instructions. Keyed by the leg's `mode` field.
_PAYMENT_BY_MODE = {
    "drive":  ("user", "at the Shady Grove parking garage ($5/day)"),
    "lyft":   ("user", "your Lyft account (in-app payment)"),
    "metro":  ("user", "tap SmarTrip / contactless card at gate"),
    "bus":    ("agent", "agent-prepaid via single-use CDP virtual card"),
    "train":  ("user", "walk-up ticket at NJT kiosk / TVM"),
}


def build_receipt(plan: dict, booking: dict | None, settlement: dict | None) -> dict:
    intent = plan.get("intent", {})
    items: list[dict] = []
    user_direct = 0.0
    user_via_agent = 0.0

    for leg in plan.get("legs", []):
        payer, method = _PAYMENT_BY_MODE.get(
            leg.get("mode", ""),
            ("user", "at the time of travel"),
        )
        item = {
            "step": leg["n"],
            "operator": leg["operator"],
            "description": f"{leg['from']} → {leg['to']}",
            "mode": leg["mode"],
            "depart": leg.get("depart"),
            "duration_min": leg.get("duration_min"),
            "cost_usd": round(leg["cost_usd"], 2),
            "payer": payer,
            "payment_method": method,
        }
        if leg.get("bookable") and booking:
            item["booking_reference"] = booking.get("booking_reference")
            item["status"] = booking.get("status", "stubbed")
        else:
            item["status"] = "pay-at-time"

        if payer == "user":
            user_direct += item["cost_usd"]
        else:
            user_via_agent += item["cost_usd"]
        items.append(item)

    agent_fee = (settlement or {}).get("amount_usd", 0.0)
    if agent_fee:
        items.append({
            "step": len(items) + 1,
            "operator": "Hop",
            "description": "Agent service fee · x402 micropayment on Base Sepolia",
            "mode": "service",
            "cost_usd": round(agent_fee, 2),
            "payer": "user→agent",
            "payment_method": "x402 (settles atomically on confirmed booking)",
            "status": settlement.get("settled", False) and "settled" or "pending",
            "tx_hash": settlement.get("tx_hash"),
        })

    grand_total = round(user_direct + user_via_agent + agent_fee, 2)
    return {
        "trip": f"{intent.get('origin')} → {intent.get('destination')}",
        "depart_date": (intent.get("arrive_by") or "").split("T")[0],
        "items": items,
        "totals": {
            "user_direct": round(user_direct, 2),
            "user_via_agent": round(user_via_agent, 2),
            "agent_fee": round(agent_fee, 2),
            "grand_total": grand_total,
        },
        "currency": "USD",
        "notes": [
            "Only the bus leg requires upfront payment — the agent uses a single-use "
            "CDP virtual card so your card never touches FlixBus.",
            "x402 settles the agent fee atomically on confirmed booking; if the booking "
            "fails, the fee never charges.",
        ],
    }
