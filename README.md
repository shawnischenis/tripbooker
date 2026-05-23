# Tripbooker

Tripbooker is a Northeast Corridor travel-planning prototype that turns a user trip request into a bookable, multi-leg itinerary. It compares local transit, rideshare, commuter rail, bus, and train options, then returns a plan with timing, costs, transfer buffers, and booking metadata.

The current app is built around a FastAPI orchestrator, provider-specific integrations, a small browser-facing UI, and payment stubs for checkout flows.

## Problem

Planning a real door-to-door trip is messy because the useful data is spread across many operators and product surfaces:

- local transit agencies expose inconsistent schedules and fare data
- bus operators often publish prices only through web booking flows
- rideshare and last-mile estimates change quickly
- users care about the full trip, not just the intercity segment
- demos and experiments need a record of why a route was chosen

Tripbooker solves this by treating the itinerary as an agentic planning problem. The orchestrator decomposes each request into first-mile, intercity, and last-mile legs, compares viable providers, and records the decision so the system can be debugged, replayed, and improved.

## How We Used Nimble

Nimble is used as the web data layer for live or semi-live transportation data where direct APIs are unavailable, limited, or not worth integrating for an early prototype.

The shared client lives in `integrations/nimble_client.py` and wraps Nimble's extract endpoint. Other integrations call it to scrape rendered pages and recover structured travel data while still failing softly back to seeded data when credentials, network access, or page parsing fail.

Current Nimble-related integration points include:

- `integrations/nimble_client.py`: shared async Nimble Web API wrapper
- `integrations/nimble_lyft.py`: rideshare estimate lookup
- `integrations/wmata.py` and `integrations/njt.py`: live transit data hooks
- `integrations/nimble_flixbus.py`: FlixBus departure data stub that represents the planned Nimble-backed flow
- `integrations/nimble_flixbus_checkout.py`: placeholder for browser-agent checkout work

This lets the planner use real web surfaces as data sources without hard-coding a separate custom scraper for every operator.

## How We Used ClickHouse

ClickHouse is the analytics and replay store. The app initializes its tables on FastAPI startup via `integrations/clickhouse_client.py`, then writes planning and booking events throughout the flow.

The main tables are:

- `price_observations`: bus/train quotes seen during planning
- `decisions`: full plan, replan, and booking payloads
- `mode_selections`: model-based transportation-mode recommendations

The `/metrics` endpoint reads from ClickHouse to expose recent decisions, recent mode selections, and row counts. This gives the project a lightweight observability loop: every quote and routing choice can become chart data, debugging context, or training/evaluation material later.

## Architecture

- `orchestrator/main.py`: FastAPI app and API endpoints
- `orchestrator/planner.py`: route decomposition, operator comparison, scheduling, and total cost calculation
- `orchestrator/modes.py`: OpenAI-backed mode-selection reasoning with cached fallback behavior
- `orchestrator/catalog.py` and `orchestrator/corridor.py`: supported cities, hubs, and route strategy selection
- `integrations/`: operator and data-source adapters
- `payments/`: virtual card and settlement stubs
- `ui/`: static web UI served by FastAPI

Important endpoints:

- `GET /`: web UI
- `POST /plan`: generate an itinerary
- `POST /replan`: adjust an existing itinerary based on user feedback
- `POST /book`: stub checkout and receipt generation
- `GET /metrics`: ClickHouse-backed planning metrics
- `GET /cities`: supported origins and destinations

## Running Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file with any credentials you want to enable:

```bash
NIMBLE_API_KEY=...
CLICKHOUSE_HOST=...
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Run the API:

```bash
uvicorn orchestrator.main:app --reload
```

Then open `http://localhost:8000`.

The app is designed to degrade gracefully. Without external credentials, many flows still return seeded or cached data so the demo remains usable.

## Future Work

- Replace remaining seeded operator data with live Nimble-backed extraction.
- Finish the real FlixBus checkout flow through Nimble Browser Agent or Browserbase verification.
- Expand the city and corridor catalog beyond the initial Northeast Corridor set.
- Add price-history charts using the `price_observations` table.
- Use ClickHouse decision logs for route-quality evaluation and regression tests.
- Improve re-planning so user feedback can change constraints, operators, budgets, and arrival windows more precisely.
- Add stronger error visibility for failed provider lookups while keeping the user-facing plan clean.
