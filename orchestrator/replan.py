"""Replan cascade. Phase 1 placeholder.

Real version (Phase 4) flips the constraint, re-runs the planner,
diffs the new plan against the old, propagates timing through the
cascade, and queries Senso for any change-fee policy before suggesting
a FlixBus rebook.
"""
from __future__ import annotations
from orchestrator.intent import Intent
from orchestrator.planner import plan


async def replan(current: dict, user_message: str) -> dict:
    constraints = list(current.get("intent", {}).get("constraints", []))
    if "drive" in user_message.lower() or "car" in user_message.lower():
        if "no_drive" not in constraints:
            constraints.append("no_drive")

    intent_dict = {**current.get("intent", {}), "constraints": constraints}
    new_plan = await plan(Intent(**intent_dict))

    delta = round(new_plan["total_usd"] - current.get("total_usd", 0), 2)
    return {
        "new_plan": new_plan,
        "user_message": user_message,
        "delta_usd": delta,
        "explanation": (
            f"Heard '{user_message}'. Swapped leg 1 to Lyft. "
            f"Total moved by ${delta:+.2f}. FlixBus departure still catchable; no rebook needed."
        ),
        "rebook_required": False,
    }
