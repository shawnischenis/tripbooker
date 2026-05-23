"""ClickHouse client — stores everything we want to chart or replay later.

Tables (created lazily on first use, idempotent):
  - price_observations: one row per FlixBus departure quote we see; drives
    the price-history chart in Phase 6 demo.
  - decisions: one row per plan/replan/book event; full plan JSON payload.
  - mode_selections: one row per OpenAI mode-selection call; lets us
    cache + replay reasoning.

All writes are async-safe (sync CH client wrapped in asyncio.to_thread) and
fail-soft — if CH is unreachable, returns {ok: False, error: ...} but does
not raise.
"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timezone
import clickhouse_connect
from dotenv import load_dotenv

load_dotenv()

CH_HOST = os.getenv("CLICKHOUSE_HOST")
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")

_client: "clickhouse_connect.driver.Client | None" = None
_init_done = False
_init_lock = asyncio.Lock()

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS price_observations (
        corridor    LowCardinality(String),
        operator    LowCardinality(String),
        mode        LowCardinality(String),
        price_usd   Float32,
        depart      DateTime,
        observed_at DateTime DEFAULT now(),
        source      LowCardinality(String)
    ) ENGINE = MergeTree
    ORDER BY (corridor, operator, observed_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        ts          DateTime DEFAULT now(),
        kind        LowCardinality(String),
        origin      String,
        destination String,
        constraints String,
        total_usd   Float32,
        payload     String
    ) ENGINE = MergeTree
    ORDER BY ts
    """,
    """
    CREATE TABLE IF NOT EXISTS mode_selections (
        ts                  DateTime DEFAULT now(),
        origin              String,
        destination         String,
        constraints         String,
        budget_usd          Float32,
        recommended_chain   String,
        rationale           String,
        source              LowCardinality(String),
        model               String,
        raw_json            String
    ) ENGINE = MergeTree
    ORDER BY ts
    """,
]


def _connect() -> "clickhouse_connect.driver.Client | None":
    global _client
    if _client is None and CH_HOST:
        _client = clickhouse_connect.get_client(
            host=CH_HOST,
            user=CH_USER,
            password=CH_PASSWORD,
            secure=True,
            connect_timeout=10,
            query_limit=0,
        )
    return _client


async def init() -> dict:
    """Create the three tables if missing. Idempotent; safe to call any time."""
    global _init_done
    if _init_done:
        return {"ok": True, "cached": True}
    async with _init_lock:
        if _init_done:
            return {"ok": True, "cached": True}
        client = _connect()
        if client is None:
            return {"ok": False, "error": "CLICKHOUSE_HOST not set"}
        try:
            for stmt in _DDL:
                await asyncio.to_thread(client.command, stmt)
            _init_done = True
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def _parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


async def record_price(
    corridor: str,
    operator: str,
    mode: str,
    price_usd: float,
    depart: str,
    source: str = "stub",
) -> dict:
    return await record_prices([{
        "corridor": corridor, "operator": operator, "mode": mode,
        "price_usd": price_usd, "depart": depart, "source": source,
    }])


async def record_prices(rows: list[dict]) -> dict:
    """Batch insert. Each row: {corridor, operator, mode, price_usd, depart, source}.
    A single insert avoids concurrent-write races in the sync clickhouse-connect client."""
    if not rows:
        return {"ok": True, "inserted": 0}
    client = _connect()
    if client is None:
        return {"ok": False, "error": "no CH client"}
    try:
        await init()
        data = [
            [
                r["corridor"], r["operator"], r["mode"],
                float(r["price_usd"]), _parse_iso(r["depart"]), r.get("source", "stub"),
            ]
            for r in rows
        ]
        await asyncio.to_thread(
            client.insert,
            "price_observations",
            data,
            column_names=["corridor", "operator", "mode", "price_usd", "depart", "source"],
        )
        return {"ok": True, "inserted": len(data)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def record_decision(kind: str, plan: dict) -> dict:
    client = _connect()
    if client is None:
        return {"ok": False, "error": "no CH client"}
    try:
        await init()
        intent = plan.get("intent", {})
        await asyncio.to_thread(
            client.insert,
            "decisions",
            [[
                kind,
                str(intent.get("origin", "")),
                str(intent.get("destination", "")),
                json.dumps(intent.get("constraints", [])),
                float(plan.get("total_usd", 0) or 0),
                json.dumps(plan, default=str),
            ]],
            column_names=["kind", "origin", "destination", "constraints", "total_usd", "payload"],
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def record_mode_selection(intent_dict: dict, modes: dict) -> dict:
    client = _connect()
    if client is None:
        return {"ok": False, "error": "no CH client"}
    try:
        await init()
        await asyncio.to_thread(
            client.insert,
            "mode_selections",
            [[
                str(intent_dict.get("origin", "")),
                str(intent_dict.get("destination", "")),
                json.dumps(intent_dict.get("constraints", [])),
                float(intent_dict.get("max_budget_usd", 0) or 0),
                str(modes.get("recommended_chain", "")),
                str(modes.get("rationale", "")),
                str(modes.get("source", "unknown")),
                str(modes.get("model", "")),
                json.dumps(modes, default=str),
            ]],
            column_names=["origin", "destination", "constraints", "budget_usd",
                          "recommended_chain", "rationale", "source", "model", "raw_json"],
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def metrics() -> dict:
    """Counts + a couple of useful aggregates for the /metrics endpoint."""
    client = _connect()
    if client is None:
        return {"ok": False, "error": "no CH client"}
    try:
        counts = {}
        for tbl in ("price_observations", "decisions", "mode_selections"):
            r = await asyncio.to_thread(client.query, f"SELECT count() FROM {tbl}")
            counts[tbl] = r.result_set[0][0]
        recent_decisions = await asyncio.to_thread(
            client.query,
            "SELECT ts, kind, origin, destination, total_usd "
            "FROM decisions ORDER BY ts DESC LIMIT 5"
        )
        recent_modes = await asyncio.to_thread(
            client.query,
            "SELECT ts, origin, destination, recommended_chain, source "
            "FROM mode_selections ORDER BY ts DESC LIMIT 5"
        )
        return {
            "ok": True,
            "counts": counts,
            "recent_decisions": [
                {"ts": str(r[0]), "kind": r[1], "origin": r[2], "destination": r[3], "total_usd": r[4]}
                for r in recent_decisions.result_set
            ],
            "recent_modes": [
                {"ts": str(r[0]), "origin": r[1], "destination": r[2], "recommended_chain": r[3], "source": r[4]}
                for r in recent_modes.result_set
            ],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def price_history(corridor: str = "WAS-EWR", days: int = 7) -> list[dict]:
    client = _connect()
    if client is None:
        return []
    try:
        await init()
        r = await asyncio.to_thread(
            client.query,
            "SELECT observed_at, operator, price_usd FROM price_observations "
            "WHERE corridor = %(c)s AND observed_at >= now() - INTERVAL %(d)s DAY "
            "ORDER BY observed_at",
            parameters={"c": corridor, "d": days},
        )
        return [{"observed_at": str(row[0]), "operator": row[1], "price_usd": float(row[2])}
                for row in r.result_set]
    except Exception:
        return []
