"""Datadog LLM Observability tracing. Phase 1 stub.

Wraps every model call + external API call so we can show traces in the demo.
"""
from __future__ import annotations
from functools import wraps
from typing import Any, Callable


def trace(name: str | None = None, kind: str = "span") -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def log_event(event: str, data: dict) -> None:
    return None
