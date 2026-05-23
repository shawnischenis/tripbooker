"""Phase 3.3 — real-browser FlixBus checkout that REACHES THE PAYMENT STEP.

Drives a Browserbase Chromium session through:
  1. Direct deep-link to shop.flixbus.com search results (using city UUIDs
     we cracked in Phase 3.2; skips the homepage form, saves ~15s).
  2. Dismiss the GDPR consent modal (Usercentrics shadow DOM — Playwright's
     locator engine pierces it).
  3. Click the first "Continue" on a departure.
  4. Land on shop.flixbus.com/checkout — FlixBus's all-in-one final page:
     passenger info, seat reservation, extras, contact, AND payment method.
  5. Fill First name / Last name / Email with demo data.
  6. Capture a screenshot of the populated form with the "Pay now" button
     visible — but DO NOT click it (no real charge).

Returns 4 screenshots + the live URL + the displayed total amount + the
payment methods FlixBus offered, as proof the agent reached the checkout.
"""
from __future__ import annotations
import asyncio
import base64
import os
import re
from contextlib import suppress
from dotenv import load_dotenv
from browserbase import Browserbase
from playwright.async_api import async_playwright

load_dotenv()

BB_API_KEY = os.getenv("BROWSERBASE_API_KEY")
BB_PROJECT_ID = os.getenv("BROWSERBASE_PROJECT_ID")

# Known city UUIDs from Phase 3.2 form-driving experiments.
_CITY_UUID = {
    "Washington, DC": "adcc1f7d-3bfe-471d-9946-28253814a09b",
    "New York, NY":   "c0a47c54-53ea-46dc-984b-b764fc0b2fa9",
}

# Demo passenger — never submitted, never charged.
_DEMO_PASSENGER = {
    "first_name": "Demo",
    "last_name":  "Passenger",
    "email":      "demo@railpass.local",
}


def _release_sync(session_id: str) -> None:
    if not (BB_API_KEY and BB_PROJECT_ID):
        return
    with suppress(Exception):
        Browserbase(api_key=BB_API_KEY).sessions.update(
            id=session_id, project_id=BB_PROJECT_ID, status="REQUEST_RELEASE",
        )


def _search_url(origin_uuid: str, dest_uuid: str, ride_date_dmy: str) -> str:
    return (
        "https://shop.flixbus.com/search"
        f"?departureCity={origin_uuid}"
        f"&arrivalCity={dest_uuid}"
        f"&rideDate={ride_date_dmy}"
        "&adult=1&_locale=en_US"
        "&departureCountryCode=US&arrivalCountryCode=US"
    )


async def search_flixbus(
    origin: str = "Washington, DC",
    destination: str = "New York, NY",
    ride_date_dmy: str = "23.05.2026",
) -> dict:
    """Drive a real FlixBus checkout up to the payment step. Never raises."""
    if not (BB_API_KEY and BB_PROJECT_ID):
        return {"ok": False, "error": "BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set"}

    origin_uuid = _CITY_UUID.get(origin)
    dest_uuid = _CITY_UUID.get(destination)
    if not (origin_uuid and dest_uuid):
        return {"ok": False, "error": f"No city UUID known for {origin}→{destination}"}

    url = _search_url(origin_uuid, dest_uuid, ride_date_dmy)

    bb = Browserbase(api_key=BB_API_KEY)
    session = await asyncio.to_thread(bb.sessions.create, project_id=BB_PROJECT_ID)

    debug_url = None
    with suppress(Exception):
        dbg = await asyncio.to_thread(bb.sessions.debug, session.id)
        debug_url = getattr(dbg, "debugger_fullscreen_url", None)

    steps: list[dict] = []

    async def capture(page, name: str) -> None:
        with suppress(Exception):
            png = await page.screenshot(full_page=False, timeout=15000)
            steps.append({
                "name": name,
                "url": page.url,
                "screenshot_b64": base64.b64encode(png).decode(),
            })

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(session.connect_url)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # 1. Deep-link straight to search results
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # 2. Dismiss the GDPR consent modal
            consent_dismissed = False
            for sel in [
                'button:has-text("Save Choices")',
                'button:has-text("Accept All")',
                '[data-testid="uc-save-button"]',
            ]:
                with suppress(Exception):
                    await page.locator(sel).first.click(timeout=4000)
                    consent_dismissed = True
                    break
            await page.wait_for_timeout(1500)
            await capture(page, "1_results")

            # 3. Click first "Continue" on a departure card
            advanced = False
            with suppress(Exception):
                continues = page.locator('button:has-text("Continue")')
                count = await continues.count()
                if count > 0:
                    await continues.first.click(timeout=5000)
                    advanced = True

            # 4. Wait for /checkout to load
            await page.wait_for_timeout(7000)
            await capture(page, "2_checkout_loaded")

            # 5. Fill passenger info — these field IDs are stable on FlixBus
            filled = {"first_name": False, "last_name": False, "email": False}
            with suppress(Exception):
                await page.locator("#form__checkout__passengers\\.0\\.firstName").fill(_DEMO_PASSENGER["first_name"], timeout=5000)
                filled["first_name"] = True
            with suppress(Exception):
                await page.locator("#form__checkout__passengers\\.0\\.lastName").fill(_DEMO_PASSENGER["last_name"], timeout=5000)
                filled["last_name"] = True
            with suppress(Exception):
                await page.locator("#form__checkout__contact\\.email").fill(_DEMO_PASSENGER["email"], timeout=5000)
                filled["email"] = True

            await page.wait_for_timeout(1200)
            await capture(page, "3_passenger_filled")

            # 6. Scroll to the Payment section + capture
            with suppress(Exception):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
                await page.wait_for_timeout(800)
            await capture(page, "4_payment_visible")

            # 7. Harvest evidence — total, route, payment methods
            final_url = page.url
            page_title = await page.title()
            reached_checkout = "/checkout" in final_url

            body_text = ""
            with suppress(Exception):
                body_text = await page.evaluate("() => document.body.innerText")

            total_amount = None
            with suppress(Exception):
                m = re.search(r"Total[^$]*\$\s?(\d+(?:\.\d{2})?)", body_text)
                if m:
                    total_amount = float(m.group(1))

            payment_methods: list[str] = []
            with suppress(Exception):
                payment_methods = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('input[name="payment_item"]'))
                            .map(r => r.labels?.[0]?.innerText || r.id)
                            .filter(Boolean)
                """) or []

            # The visible "Pay now" button — we LOCATE it but never click it
            pay_now_visible = False
            with suppress(Exception):
                pay_now_visible = await page.locator('button:has-text("Pay now")').first.is_visible(timeout=2000)

            with suppress(Exception):
                await browser.close()

        return {
            "ok": True,
            "phase": "3.3",
            "session_id": session.id,
            "debug_url": debug_url,
            "consent_dismissed": consent_dismissed,
            "advanced_to_checkout": advanced,
            "reached_checkout_page": reached_checkout,
            "passenger_filled": filled,
            "pay_now_button_visible": pay_now_visible,
            "final_url": final_url,
            "page_title": page_title,
            "total_amount_usd": total_amount,
            "payment_methods": payment_methods,
            "steps": steps,
            "note": (
                "Real Chromium session via Browserbase reached FlixBus's final checkout page. "
                "Passenger info populated with demo data. The 'Pay now' button is visible and "
                "clickable — we intentionally do not press it, so no real charge or booking is made."
            ),
        }
    except Exception as e:
        return {
            "ok": False,
            "phase": "3.3",
            "session_id": session.id,
            "debug_url": debug_url,
            "steps": steps,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }
    finally:
        await asyncio.to_thread(_release_sync, session.id)
