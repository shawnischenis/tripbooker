"""x402 middleware. Phase 1 stub.

Real version returns 402 with payment terms on first call, accepts the
signed retry, then runs the booking. Fee fires only on confirmed booking.
"""
from __future__ import annotations

AGENT_FEE_USD = 1.50


def payment_terms(amount_usd: float = AGENT_FEE_USD) -> dict:
    return {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": "USDC",
        "amount_usd": amount_usd,
        "pay_to": "0xAGENT0000000000000000000000000000000000",
        "description": "hop agent fee — confirmed booking only.",
    }


def verify_and_settle(payment_header: str | None) -> dict:
    return {
        "settled": True,
        "amount_usd": AGENT_FEE_USD,
        "tx_hash": "0xstubsettlementhash",
        "network": "base-sepolia",
        "source": "stub",
    }
