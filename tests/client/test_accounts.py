"""Tests for client/accounts.py."""

from __future__ import annotations

import httpx
import respx

from client import shared
from client.accounts import list_accounts, list_meters, supported_granularities
from client.models import Account, Granularity, Meter, UtilityType

DASHBOARD_PAGE = """
<html><body>
<li class="MobileNav__portal-summary">
    <div><span>Sample</span></div>
    <div>
        <span>Account Number</span>
        <span>555000111022</span>
    </div>
    <div>
        <span class="text-xs">Service Address</span><br />
        <span>456 Sample Rd</span><br />
    </div>
</li>
<a href="/account/manageaccount">
    <span class="text-700">Manage Account</span>
    <span class="text-darkgray text-GothamMedium"> Jane Tester</span>
</a>
</body></html>
"""

DASHBOARD_PAGE_NO_SUMMARY = "<html><body>no account summary here</body></html>"

DASHBOARD_PAGE_NO_ADDRESS_OR_NAME = """
<html><body>
<li class="MobileNav__portal-summary">
    <div>
        <span>Account Number</span>
        <span>555000111022</span>
    </div>
</li>
</body></html>
"""

DASHBOARD_PAGE_NO_ACCOUNT_NUMBER_VALUE = """
<html><body>
<li class="MobileNav__portal-summary">
    <div><span>Account Number</span></div>
</li>
</body></html>
"""


@respx.mock
async def test_list_accounts_parses_account_number_address_and_name(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/dashboard").mock(return_value=httpx.Response(200, text=DASHBOARD_PAGE))

    async with httpx.AsyncClient() as client:
        result = await list_accounts(client)

    assert result == [
        Account(
            account_id="555000111022",
            service_address="456 Sample Rd",
            name="Jane Tester",
        )
    ]


@respx.mock
async def test_list_accounts_missing_summary_returns_empty(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/dashboard").mock(
        return_value=httpx.Response(200, text=DASHBOARD_PAGE_NO_SUMMARY)
    )

    async with httpx.AsyncClient() as client:
        assert await list_accounts(client) == []


@respx.mock
async def test_list_accounts_missing_address_and_name_are_none(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/dashboard").mock(
        return_value=httpx.Response(200, text=DASHBOARD_PAGE_NO_ADDRESS_OR_NAME)
    )

    async with httpx.AsyncClient() as client:
        result = await list_accounts(client)

    assert result[0].service_address is None
    assert result[0].name is None


@respx.mock
async def test_list_accounts_account_number_label_with_no_value_returns_empty(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/dashboard").mock(
        return_value=httpx.Response(200, text=DASHBOARD_PAGE_NO_ACCOUNT_NUMBER_VALUE)
    )

    async with httpx.AsyncClient() as client:
        assert await list_accounts(client) == []


async def test_list_meters_returns_single_gas_meter_matching_account():
    account = Account(
        account_id="555000111022",
        service_address="456 Sample Rd",
        name="Jane Tester",
    )

    async with httpx.AsyncClient() as client:
        result = await list_meters(client, account)

    assert result == [
        Meter(
            account_id="555000111022",
            meter_id="555000111022",
            utility_type=UtilityType.GAS,
            description="Gas",
            service_address="456 Sample Rd",
        )
    ]


async def test_supported_granularities_is_monthly_only():
    meter = Meter(account_id="555000111022", meter_id="555000111022", utility_type=UtilityType.GAS)

    async with httpx.AsyncClient() as client:
        assert await supported_granularities(client, meter) == [Granularity.MONTHLY]
