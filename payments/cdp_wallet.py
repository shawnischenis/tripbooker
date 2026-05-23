"""Agent CDP wallet + virtual card issuance. Phase 1 stub.

Real version funds the agent wallet on Base Sepolia and issues a
single-use virtual card for FlixBus checkout.
"""
from __future__ import annotations

AGENT_WALLET_ADDRESS = "0xAGENT0000000000000000000000000000000000"
USER_WALLET_ADDRESS = "0xUSER00000000000000000000000000000000000"


def balances() -> dict:
    return {
        "agent": {"address": AGENT_WALLET_ADDRESS, "usdc": 50.00, "network": "base-sepolia"},
        "user": {"address": USER_WALLET_ADDRESS, "usdc": 25.00, "network": "base-sepolia"},
    }


def issue_virtual_card(limit_usd: float, merchant_hint: str = "FlixBus") -> dict:
    return {
        "card_id": "vc_stub_phase1",
        "last4": "4242",
        "limit_usd": limit_usd,
        "merchant_hint": merchant_hint,
        "status": "active",
    }
