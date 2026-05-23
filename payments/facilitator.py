"""Local x402 facilitator config. Phase 1 stub."""
from __future__ import annotations

FACILITATOR_URL = "http://localhost:4021"
NETWORK = "base-sepolia"


def status() -> dict:
    return {"facilitator_url": FACILITATOR_URL, "network": NETWORK, "ready": True, "source": "stub"}
