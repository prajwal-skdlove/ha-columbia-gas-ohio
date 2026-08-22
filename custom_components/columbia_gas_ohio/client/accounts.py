"""Account/meter discovery for the Columbia Gas of Ohio portal.

Ported from `utility-reader`'s `providers/columbia_gas_oh/accounts.py`. The
`/dashboard` page's mobile nav sidebar (`.MobileNav__portal-summary`)
server-renders the account number and service address directly -- no JS
execution or separate API call needed. The account holder's name is
likewise server-rendered, in a `span.text-darkgray` next to the "Manage
Account" nav link.

The portal exposes no separate "meter ID" anywhere discoverable -- a
residential gas account here is exactly one meter, so `Meter.meter_id` is
just the account ID.

The `/UsageHistory*Csv/{n}` endpoints take a numeric account index (`0` for
the first/only account on a login). Only a single-account login has been
observed against the real portal, so `list_accounts` always returns index 0
for the one account found; a login with multiple linked accounts would need
this extended once that shape can actually be observed.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from .models import Account, Granularity, Meter, UtilityType
from .shared import get

_LOGGER = logging.getLogger(__name__)

# The index into /UsageHistory*Csv/{n} for the single account this
# integration supports today (see module docstring).
ACCOUNT_INDEX = 0


def _text_after_label(soup: BeautifulSoup, label: str) -> str | None:
    label_span = soup.find("span", string=label)
    if label_span is None:
        return None
    value_span = label_span.find_next_sibling("span")
    if value_span is None:
        return None
    text = value_span.get_text(strip=True)
    return text or None


async def list_accounts(client: httpx.AsyncClient) -> list[Account]:
    resp = await get(client, "/dashboard")
    soup = BeautifulSoup(resp.text, "html.parser")

    summary = soup.find("li", class_="MobileNav__portal-summary")
    if summary is None:
        _LOGGER.warning("No account summary found on the Columbia Gas dashboard for this login")
        return []

    account_id = _text_after_label(summary, "Account Number")
    if not account_id:
        _LOGGER.warning("Dashboard account summary had no parseable Account Number")
        return []

    service_address = _text_after_label(summary, "Service Address")
    if service_address:
        service_address = re.sub(r"\s+", " ", service_address).strip()

    name = None
    name_span = soup.find("span", class_="text-darkgray")
    if name_span is not None:
        name = name_span.get_text(strip=True) or None

    _LOGGER.debug("Found 1 Columbia Gas account: %s", account_id)
    return [Account(account_id=account_id, service_address=service_address, name=name)]


async def list_meters(client: httpx.AsyncClient, account: Account) -> list[Meter]:
    return [
        Meter(
            account_id=account.account_id,
            meter_id=account.account_id,
            utility_type=UtilityType.GAS,
            description="Gas",
            service_address=account.service_address,
        )
    ]


async def supported_granularities(client: httpx.AsyncClient, meter: Meter) -> list[Granularity]:
    # Confirmed via discovery: the portal exposes only monthly meter-read
    # data, no hourly/daily AMI data anywhere in the account.
    return [Granularity.MONTHLY]
