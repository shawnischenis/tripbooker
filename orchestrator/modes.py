"""Mode-selection reasoning — runs BEFORE any specific operator is queried.

Given an Intent (origin + destination + budget + arrive-by + constraints),
asks a small LLM to reason about which transportation modes are viable for
first mile, intercity, and last mile. This is where the agent's planning
judgement lives: the operator calls (Nimble for WMATA/NJT/FlixBus) only run
for modes that pass this gate.

Falls back to a canned NEC-corridor recommendation if no OPENAI_API_KEY is set
or the model call fails, so the demo flow still runs without external deps.
"""
from __future__ import annotations
import json
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError

from orchestrator.intent import Intent
from integrations import clickhouse_client

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_client: AsyncOpenAI | None = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """You are a transit planner for the US Northeast Corridor (NEC) — DC, Baltimore, Philadelphia, NYC, Boston, plus their surrounding suburbs.

Decompose every trip into three sequential segments:
- first_mile: from ORIGIN to the nearest intercity transit hub (typical hubs: Union Station DC, Penn Station Baltimore, 30th St Philadelphia, Newark Penn, NY Penn / Port Authority, South Station Boston).
- intercity: between two intercity hubs.
- last_mile: from the arrival hub to the final DESTINATION.

For each segment, ALWAYS list ALL candidate modes — including the ones that are not viable — with viable=true/false and one-sentence reasoning. Candidate modes:
- first_mile / last_mile: drive (user drives own car this leg only, parks at the hub), lyft, walk, transit (local metro/bus/commuter rail).
- intercity: bus, train.

For intercity, ALWAYS include at least one operator name in the operators[] array. Known NEC operators:
- bus: FlixBus, OurBus, Vamoose, Greyhound, Megabus
- train: Amtrak Northeast Regional (cheaper), Amtrak Acela (faster, premium)

Constraint vocabulary:
- no_drive: user has no access to their own car. Lyft is still fine (someone else drives). Only the "drive" mode becomes infeasible.
- fast: prioritize speed — favor train (Acela > NER > bus) for intercity.
- (default, no constraint): COST-OPTIMAL. Intercity bus over train. Local transit over Lyft when reasonable.

Cost reference (per passenger, one-way, NEC):
- FlixBus / OurBus / Vamoose: $20–40
- Greyhound / Megabus: $25–50
- Amtrak Northeast Regional: $89–129
- Amtrak Acela: $159–300
- Lyft Standard urban: $15–35
- Local metro/transit: $2–6

Compare the budget you are given to these ranges. Mark an intercity option as viable=false if its low end exceeds the budget.

Return STRICT JSON ONLY in this schema:
{
  "first_mile": [{"mode": "drive|lyft|walk|transit", "viable": bool, "reasoning": "..."}],
  "intercity":  [{"mode": "bus|train", "operators": ["..."], "viable": bool, "reasoning": "..."}],
  "last_mile":  [{"mode": "drive|lyft|walk|transit", "viable": bool, "reasoning": "..."}],
  "recommended_chain": "<first_mile_mode> + <intercity_mode> + <last_mile_mode>",
  "rationale": "two-sentence explanation of the recommended chain"
}

Keep each reasoning string under 90 characters."""


def _fallback(intent: Intent) -> dict:
    """Canned NEC recommendation. Matches the Rockville→NYC demo path."""
    no_drive = "no_drive" in intent.constraints
    return {
        "first_mile": [
            {"mode": "drive", "viable": not no_drive,
             "reasoning": "Available unless user has flagged no_drive."},
            {"mode": "lyft", "viable": True,
             "reasoning": "Standard rideshare available in NEC metro areas."},
            {"mode": "walk", "viable": False,
             "reasoning": "Most NEC origins are >2 miles from intercity hubs."},
            {"mode": "transit", "viable": True,
             "reasoning": "Local transit (WMATA, SEPTA, NJT) covers most hubs."},
        ],
        "intercity": [
            {"mode": "bus", "operators": ["FlixBus", "OurBus", "Vamoose", "Greyhound"],
             "viable": True,
             "reasoning": "Cheapest corridor option; 4–5 hr DC↔NYC."},
            {"mode": "train", "operators": ["Amtrak NER", "Acela"],
             "viable": True,
             "reasoning": "Faster but 3–6x more expensive than bus."},
        ],
        "last_mile": [
            {"mode": "transit", "viable": True,
             "reasoning": "NJ Transit / LIRR / MTA serve all NEC arrival hubs."},
            {"mode": "lyft", "viable": True,
             "reasoning": "Universal NEC coverage."},
            {"mode": "walk", "viable": True,
             "reasoning": "Hubs are central; many destinations <1 mile."},
        ],
        "recommended_chain": ("lyft" if no_drive else "drive") + " + bus + transit",
        "rationale": (
            "Bus (FlixBus) is the cost-optimal intercity leg under most NEC budgets. "
            "First mile defaults to drive; flips to Lyft when no_drive is set."
        ),
        "source": "cached",
    }


async def select_modes(intent: Intent) -> dict:
    if _client is None:
        result = _fallback(intent)
    else:
        user_msg = (
            f"Origin: {intent.origin}\n"
            f"Destination: {intent.destination}\n"
            f"Max budget: ${intent.max_budget_usd:.2f} (per passenger, one-way, total across all legs)\n"
            f"Arrive by: {intent.arrive_by.isoformat()}\n"
            f"Constraints: {', '.join(intent.constraints) if intent.constraints else 'none'}\n\n"
            "Output the mode-selection JSON now."
        )
        try:
            resp = await _client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=700,
            )
            content = resp.choices[0].message.content or "{}"
            parsed = json.loads(content)
            parsed["source"] = "openai"
            parsed["model"] = OPENAI_MODEL
            result = parsed
        except (OpenAIError, json.JSONDecodeError, KeyError) as e:
            result = _fallback(intent)
            result["error"] = f"{type(e).__name__}: {str(e)[:120]}"

    await clickhouse_client.record_mode_selection(intent.model_dump(mode="json"), result)
    return result
