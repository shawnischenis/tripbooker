"""Trip intent — parsed from user input."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class Intent(BaseModel):
    origin: str = "Rockville, MD"
    destination: str = "New York, NY"
    arrive_by: datetime = Field(default_factory=lambda: datetime.fromisoformat("2026-05-25T16:00:00"))
    max_budget_usd: float = 80.0
    constraints: list[str] = Field(default_factory=list)
    """Free-form constraint tags. Vocabulary recognized by mode-selection:
    'no_drive', 'fast'. Additional tags are passed through to the model."""


def parse(text: str | None) -> Intent:
    """Phase 1: hardcoded. Phase 4 plugs in real LLM-driven parsing."""
    return Intent()
