"""Shared constants/helpers for the Columbia Gas of Ohio client.

Ported from the `utility-reader` project's
`providers/columbia_gas_oh/_shared.py` (async'd for Home Assistant) -- see
that project's PLAN.md for how these facts about the portal were originally
discovered. Login is a plain form POST with no CSRF token; usage/billing
history come from direct CSV export endpoints
(`/UsageHistoryAllCsv/{account_index}`, `/BillingHistoryAllCsv`) rather than
HTML tables. Both return whatever history the portal currently retains in
one response (no date-range params, no pagination) -- about 24 months on
the account discovery was run against.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://myaccount.columbiagasohio.com"

REQUEST_DELAY_SECONDS = 0.3
USAGE_UNIT = "Ccf"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
)
async def get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    """GET a Columbia Gas portal path with politeness delay + retry."""
    url = f"{BASE_URL}{path}"
    _LOGGER.debug("GET %s", url)
    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    resp = await client.get(url)
    resp.raise_for_status()
    _LOGGER.debug("GET %s -> %s (%d bytes)", url, resp.status_code, len(resp.content))
    return resp
