"""Replan cascade — Phase 4.

Pipeline when the user types a constraint change:
  1. Parse the message into structured constraints / time perturbations.
  2. Re-run plan() with the new intent. This re-asks OpenAI for modes,
     re-fetches WMATA/NJT, re-runs the 4-operator comparison.
  3. Apply any time perturbations (traffic, surge) to leg 1, propagate.
  4. Run cascade.analyze — does the bookable leg still catch?
  5. If not, cascade.analyze queries Senso for the change-fee policy
     and finds rebook candidates from the intercity_comparison.
  6. Return a flat dict the UI can render: new plan, cascade, summary text.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from orchestrator.intent import Intent
from orchestrator.planner import plan
from orchestrator.cascade import analyze as cascade_analyze


def _detect_perturbations(msg: str) -> dict:
    """Extract structured perturbations from the user's free-text message."""
    m = msg.lower()
    out = {
        "constraints_added": [],
        "leg1_extra_min": 0,
        "leg1_extra_cost_usd": 0.0,
        "narrative_hints": [],
    }

    if any(w in m for w in ("can't drive", "cant drive", "no car", "no drive", "car broke", "car broken")):
        out["constraints_added"].append("no_drive")
        out["narrative_hints"].append("driver unavailable; swapping leg 1 to Lyft")

    if any(w in m for w in ("traffic", "stuck in", "gridlock")):
        out["leg1_extra_min"] += 15
        out["narrative_hints"].append("traffic → +15 min on leg 1")

    if any(w in m for w in ("massive jam", "huge delay", "really late", "way late", "30 min")):
        out["leg1_extra_min"] += 30
        out["narrative_hints"].append("severe delay → +30 min on leg 1")

    if any(w in m for w in ("surge", "rush hour")):
        out["leg1_extra_min"] += 10
        out["leg1_extra_cost_usd"] += 12.0
        out["narrative_hints"].append("Lyft surge → +10 min, +$12 fare")

    if "fast" in m or "in a hurry" in m or "asap" in m:
        out["constraints_added"].append("fast")
        out["narrative_hints"].append("user prioritizing speed; intercity → train if budget allows")

    return out


def _apply_leg1_perturbation(legs: list[dict], extra_min: int, extra_cost: float) -> list[dict]:
    if extra_min == 0 and extra_cost == 0:
        return legs
    out = []
    for leg in legs:
        leg = {**leg}
        if leg["n"] == 1 and extra_min > 0:
            try:
                arr = datetime.fromisoformat(leg["arrive"])
                leg["arrive"] = (arr + timedelta(minutes=extra_min)).isoformat()
                leg["duration_min"] = (leg.get("duration_min") or 0) + extra_min
            except (ValueError, TypeError):
                pass
        if leg["n"] == 1 and extra_cost > 0:
            leg["cost_usd"] = round(leg["cost_usd"] + extra_cost, 2)
        out.append(leg)
    return out


async def replan(current: dict, user_message: str) -> dict:
    perturb = _detect_perturbations(user_message)

    constraints = list(current.get("intent", {}).get("constraints", []))
    for c in perturb["constraints_added"]:
        if c not in constraints:
            constraints.append(c)

    intent_dict = {**current.get("intent", {}), "constraints": constraints}
    new_plan = await plan(Intent(**intent_dict))

    # Apply perturbations to leg 1 (traffic / surge are additive to the modeled time)
    new_plan["legs"] = _apply_leg1_perturbation(
        new_plan["legs"],
        perturb["leg1_extra_min"],
        perturb["leg1_extra_cost_usd"],
    )
    new_plan["total_usd"] = round(sum(l["cost_usd"] for l in new_plan["legs"]), 2)
    new_plan["within_budget"] = new_plan["total_usd"] <= intent_dict.get("max_budget_usd", 80)

    cascade = cascade_analyze(new_plan, intent_dict)

    delta_usd = round(new_plan["total_usd"] - current.get("total_usd", 0), 2)
    hint_text = " · ".join(perturb["narrative_hints"]) or "no recognized perturbations"

    explanation = (
        f'Heard: "{user_message.strip()}" → {hint_text}. '
        + cascade["summary"]
        + f' Total moved by ${delta_usd:+.2f}.'
    )

    return {
        "new_plan": new_plan,
        "user_message": user_message,
        "perturbations": perturb,
        "cascade": cascade,
        "delta_usd": delta_usd,
        "rebook_required": cascade["rebook_required"],
        "explanation": explanation,
    }
