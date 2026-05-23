"""Railpass orchestrator — FastAPI entry point."""
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
from integrations import nimble_flixbus, clickhouse_client
from payments import cdp_wallet, x402_server

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
UI_FILE = UI_DIR / "index.html"
MAP_FILE = UI_DIR / "map.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Idempotent CREATE TABLE on startup so the first /plan doesn't pay for DDL.
    await clickhouse_client.init()
    yield


app = FastAPI(title="Railpass", version="0.2.0", lifespan=lifespan)


class ReplanRequest(BaseModel):
    current_plan: dict[str, Any]
    message: str


class BookRequest(BaseModel):
    plan: dict[str, Any]


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


@app.post("/book")
async def book_endpoint(req: BookRequest) -> dict:
    bookable = next((leg for leg in req.plan.get("legs", []) if leg.get("bookable")), None)
    if not bookable:
        return {"ok": False, "error": "No bookable leg in plan."}

    card = cdp_wallet.issue_virtual_card(limit_usd=bookable["cost_usd"] + 1, merchant_hint="FlixBus")
    booking = nimble_flixbus.book(
        departure_id=bookable["departure_id"],
        passenger={"name": "Demo Passenger", "email": "demo@railpass.local"},
        payment_token=card["card_id"],
    )
    settlement = x402_server.verify_and_settle(payment_header=None)
    await clickhouse_client.record_decision("book", {**req.plan, "booking": booking, "settlement": settlement})
    return {
        "ok": True,
        "booking": booking,
        "card": card,
        "settlement": settlement,
        "phase": 2,
    }


@app.get("/wallet")
def wallet_endpoint() -> dict:
    return cdp_wallet.balances()


@app.get("/metrics")
async def metrics_endpoint() -> dict:
    return await clickhouse_client.metrics()
