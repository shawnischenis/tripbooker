"""Intercity operator comparison — the agency moment.

Queries multiple intercity operators in parallel (FlixBus, OurBus, Vamoose,
Amtrak NER), evaluates each departure against the trip intent (budget +
arrive-by + constraints), and picks the winner. Every candidate is logged
to ClickHouse so the demo can show "the agent considered N, picked X."

Phase 3.1: operator modules return realistic stubs.
Phase 3.2 (not yet built): each operator scrapes via Nimble Browser Agent.
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime
from orchestrator.intent import Intent
from integrations import nimble_flixbus, ourbus, vamoose, amtrak

# Rough reserve for non-intercity legs (drive/lyft + metro + NJT). Used to
# decide whether an intercity option fits the user's total budget.
_OTHER_LEGS_RESERVE_USD = 15.0


def _evaluate(dep: dict, intent: Intent) -> dict:
    """Annotate a departure with viability flags + reason."""
    intercity_budget = intent.max_budget_usd - _OTHER_LEGS_RESERVE_USD
    over_budget = dep["price_usd"] > intercity_budget
    try:
        arrive_dt = datetime.fromisoformat(dep["arrive"])
        too_late = arrive_dt > intent.arrive_by
    except (ValueError, TypeError):
        too_late = False

    viable = not over_budget and not too_late
    reasons = []
    if over_budget:
        reasons.append(
            f"${dep['price_usd']:.2f} exceeds intercity budget ${intercity_budget:.2f}"
        )
    if too_late:
        reasons.append(f"arrives after {intent.arrive_by.isoformat()}")
    return {**dep, "viable": viable, "reason": "; ".join(reasons) or "viable"}


async def _query(module, intent: Intent) -> list[dict]:
    """Best-effort: each operator module exposes a sync find_departures()
    today; wrap in to_thread so we don't accidentally block when Phase 3.2
    swaps in real Nimble calls."""
    return await asyncio.to_thread(module.find_departures)


async def compare_intercity(intent: Intent) -> dict:
    t0 = time.monotonic()
    raw = await asyncio.gather(
        _query(nimble_flixbus, intent),
        _query(ourbus, intent),
        _query(vamoose, intent),
        _query(amtrak, intent),
        return_exceptions=True,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    candidates: list[dict] = []
    for r in raw:
        if isinstance(r, Exception) or not r:
            continue
        for dep in r:
            candidates.append(_evaluate(dep, intent))

    criterion = "speed" if "fast" in intent.constraints else "cost"
    viable = [c for c in candidates if c["viable"]]

    if not viable:
        # Everyone is filtered out; pick the cheapest infeasible option so
        # the UI shows *something* and the rationale explains why.
        winner = min(candidates, key=lambda c: c["price_usd"]) if candidates else None
        reasoning = (
            "No operator fits both the budget and the arrive-by deadline. "
            "Surfacing the cheapest option as a stretch — user can relax constraints."
        )
    else:
        if criterion == "speed":
            winner = min(viable, key=lambda c: c["duration_min"])
            reasoning = (
                f"Constraint 'fast' set → ranked by duration. "
                f"{winner['operator']} {winner['duration_min']}min beats next best."
            )
        else:
            winner = min(viable, key=lambda c: c["price_usd"])
            reasoning = (
                f"Default cost-optimal ranking. {winner['operator']} ${winner['price_usd']:.2f} "
                f"is the cheapest of {len(viable)} viable options."
            )

    return {
        "winner": winner,
        "candidates": candidates,
        "criterion": criterion,
        "elapsed_ms": elapsed_ms,
        "reasoning": reasoning,
        "n_operators_queried": 4,
        "n_viable": len(viable),
    }
