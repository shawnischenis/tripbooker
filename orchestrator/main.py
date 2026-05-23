"""hop orchestrator — FastAPI entry point."""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from orchestrator.intent import Intent, parse
from orchestrator.planner import plan
from orchestrator.replan import replan
from orchestrator.receipt import build_receipt
from orchestrator.catalog import supported_origins, supported_destinations, CITIES
import asyncio
from integrations import nimble_flixbus, ourbus, vamoose, amtrak, clickhouse_client
from integrations import nimble_flixbus_checkout, browserbase_flixbus
from payments import cdp_wallet, x402_server

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
UI_FILE = UI_DIR / "index.html"
MAP_FILE = UI_DIR / "map.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Idempotent CREATE TABLE on startup so the first /plan doesn't pay for DDL.
    await clickhouse_client.init()
    yield


app = FastAPI(title="hop", version="0.2.0", lifespan=lifespan)


class ReplanRequest(BaseModel):
    current_plan: dict[str, Any]
    message: str


class BookRequest(BaseModel):
    plan: dict[str, Any]
    verify: bool = False  # When true, also drive a real Browserbase session.


@app.get("/")
def root() -> FileResponse:
    return FileResponse(UI_FILE)


@app.get("/map")
def map_page() -> FileResponse:
    return FileResponse(MAP_FILE)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "phase": 1}


@app.post("/plan")
async def plan_endpoint(intent: Intent | None = None) -> dict:
    p = await plan(intent or parse(None))
    await clickhouse_client.record_decision("plan", p)
    return p


@app.post("/replan")
async def replan_endpoint(req: ReplanRequest) -> dict:
    out = await replan(req.current_plan, req.message)
    await clickhouse_client.record_decision("replan", out.get("new_plan", {}))
    return out


_BOOKER_BY_OPERATOR = {
    "FlixBus": nimble_flixbus.book,
    "OurBus":  ourbus.book,
    "Vamoose": vamoose.book,
    "Amtrak NER": amtrak.book,
}


@app.post("/book")
async def book_endpoint(req: BookRequest) -> dict:
    bookable = next((leg for leg in req.plan.get("legs", []) if leg.get("bookable")), None)
    if not bookable:
        return {"ok": False, "error": "No bookable leg in plan."}

    operator = bookable.get("operator", "FlixBus")
    booker = _BOOKER_BY_OPERATOR.get(operator, nimble_flixbus.book)

    card = cdp_wallet.issue_virtual_card(limit_usd=bookable["cost_usd"] + 1, merchant_hint=operator)

    # Stub booking via the operator's book() runs synchronously; the real
    # Nimble Browser Agent verification runs in parallel for FlixBus winners
    # so the user only pays one round-trip latency.
    booking = booker(
        departure_id=bookable["departure_id"],
        passenger={"name": "Demo Passenger", "email": "demo@railpass.local"},
        payment_token=card["card_id"],
    )
    settlement = x402_server.verify_and_settle(payment_header=None)
    receipt = build_receipt(req.plan, booking, settlement)

    # Browserbase live-verification is opt-in via ?verify=true — it adds ~60s
    # of round-trip latency to drive a real headless browser. The receipt
    # below is always returned, instantly.
    browserbase_evidence = None
    if req.verify and operator == "FlixBus":
        browserbase_evidence = await browserbase_flixbus.search_flixbus()

    bb_log_copy = None
    if browserbase_evidence:
        bb_log_copy = {
            k: ([{**s, "screenshot_b64": f"<{len(s.get('screenshot_b64', ''))//1000}KB>"}
                 for s in v] if k == "steps" else v)
            for k, v in browserbase_evidence.items()
        }
    await clickhouse_client.record_decision(
        "book",
        {**req.plan, "booking": booking, "settlement": settlement, "receipt": receipt,
         "browserbase_evidence": bb_log_copy},
    )
    return {
        "ok": True,
        "operator": operator,
        "booking": booking,
        "card": card,
        "settlement": settlement,
        "receipt": receipt,
        "browserbase_evidence": browserbase_evidence,
        "phase": 3,
    }


@app.get("/wallet")
def wallet_endpoint() -> dict:
    return cdp_wallet.balances()


@app.get("/cities")
def cities_endpoint() -> dict:
    """Catalog of supported origins + destinations + their NEC hubs."""
    return {
        "origins":      [{"name": n, "hub": CITIES[n]["hub"]} for n in supported_origins()],
        "destinations": [{"name": n, "hub": CITIES[n]["hub"]} for n in supported_destinations()],
    }


@app.get("/metrics")
async def metrics_endpoint() -> dict:
    return await clickhouse_client.metrics()
