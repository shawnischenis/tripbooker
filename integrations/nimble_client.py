"""Shared Nimble Web API client.

Wraps `POST https://sdk.nimbleway.com/v1/extract`. Used by wmata, njt,
and nimble_lyft to scrape live page data. Callers are expected to catch
NimbleError and fall back to seeded data.
"""
from __future__ import annotations
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

NIMBLE_API_URL = "https://sdk.nimbleway.com/v1/extract"
NIMBLE_API_KEY = os.getenv("NIMBLE_API_KEY")
DEFAULT_TIMEOUT = 35.0


class NimbleError(Exception):
    """Raised on any Nimble call failure — network, auth, parse, or non-200."""


async def extract(
    url: str,
    *,
    render: bool = True,
    formats: list[str] | None = None,
    render_options: dict | None = None,
    browser_actions: list[dict] | None = None,
    country: str = "US",
    timeout: float = DEFAULT_TIMEOUT,
    **extra: object,
) -> dict:
    if not NIMBLE_API_KEY:
        raise NimbleError("NIMBLE_API_KEY not set in environment")

    payload: dict = {
        "url": url,
        "render": render,
        "formats": formats or ["html", "markdown"],
        "country": country,
    }
    if render_options:
        payload["render_options"] = render_options
    if browser_actions:
        payload["browser_actions"] = browser_actions
    payload.update(extra)

    headers = {
        "Authorization": f"Bearer {NIMBLE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(NIMBLE_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise NimbleError(f"timeout after {timeout}s") from e
    except httpx.HTTPError as e:
        raise NimbleError(f"network error: {type(e).__name__}") from e

    if r.status_code != 200:
        raise NimbleError(f"HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if body.get("status") != "success":
        raise NimbleError(f"nimble status={body.get('status')}: {body.get('warnings', '')[:200]}")
    return body
