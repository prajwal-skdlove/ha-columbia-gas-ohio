"""Tests for ColumbiaGasCoordinator: auth error mapping and statistics
import.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.columbia_gas_ohio.client import CannotConnect, InvalidAuth
from custom_components.columbia_gas_ohio.client.models import Account, Meter, UtilityType
from custom_components.columbia_gas_ohio.const import DOMAIN
from custom_components.columbia_gas_ohio.coordinator import (
    ColumbiaGasCoordinator,
    _bill_statistic_id,
    _statistic_id,
)

BASE_URL = "https://myaccount.columbiagasohio.com"

LOGIN_PAGE = """
<html><body>
<form id="CustomerPortalLogin" method="post" action="/login">
    <input type="text" name="Username" />
    <input type="password" name="Password" />
</form>
</body></html>
"""
DASHBOARD_AFTER_LOGIN = "<html><body><div>Welcome</div></body></html>"

DASHBOARD_PAGE = """
<html><body>
<li class="MobileNav__portal-summary">
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

USAGE_CSV = """Date,Type of Read,Avg Temp,Number of Days,Units Used, Yearly Usage, Bill Amount, Cost per Day
8/4/2026,ACTUAL READING,75.90,29,10.00,0%,$56.42,$1.95
"""

BILLING_CSV = """Bill Date,Type,Description,Amount
8/5/2026,Bill,Bill due on 2026-08-19,$56.42
"""


def _mock_happy_path() -> None:
    respx.get(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))
    respx.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, text=DASHBOARD_AFTER_LOGIN))
    respx.get(f"{BASE_URL}/dashboard").mock(return_value=httpx.Response(200, text=DASHBOARD_PAGE))
    respx.get(f"{BASE_URL}/UsageHistoryAllCsv/0").mock(return_value=httpx.Response(200, text=USAGE_CSV))
    respx.get(f"{BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=BILLING_CSV))


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "hunter2"},
    )
    entry.add_to_hass(hass)
    return entry


@respx.mock
async def test_first_refresh_imports_monthly_and_bill_statistics(recorder_mock, hass: HomeAssistant) -> None:
    _mock_happy_path()
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)

    assert coordinator.last_update_success is True
    assert "555000111022" in coordinator.data.meters
    assert coordinator.data.meters["555000111022"].latest_value == 10.0
    assert "555000111022" in coordinator.data.bills
    assert coordinator.data.bills["555000111022"].amount_total == 56.42

    meter_stats = await hass.async_add_executor_job(
        get_last_statistics, hass, 1, "columbia_gas_ohio:gas_555000111022", True, {"sum"}
    )
    assert meter_stats["columbia_gas_ohio:gas_555000111022"][0]["sum"] == 10.0

    bill_stats = await hass.async_add_executor_job(
        get_last_statistics, hass, 1, "columbia_gas_ohio:555000111022_bill_amount", True, {"sum"}
    )
    assert bill_stats["columbia_gas_ohio:555000111022_bill_amount"][0]["sum"] == 56.42


@respx.mock
async def test_second_refresh_does_not_reimport_unchanged_data(recorder_mock, hass: HomeAssistant) -> None:
    _mock_happy_path()
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    first_stats = await hass.async_add_executor_job(
        get_last_statistics, hass, 1, "columbia_gas_ohio:gas_555000111022", True, {"sum"}
    )
    first_sum = first_stats["columbia_gas_ohio:gas_555000111022"][0]["sum"]

    # Nothing changed on the portal between refreshes -- the same monthly
    # row comes back again (the endpoint always returns full history). The
    # running sum must not double-count it.
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    second_stats = await hass.async_add_executor_job(
        get_last_statistics, hass, 1, "columbia_gas_ohio:gas_555000111022", True, {"sum"}
    )
    second_sum = second_stats["columbia_gas_ohio:gas_555000111022"][0]["sum"]

    assert second_sum == first_sum == 10.0


async def test_invalid_auth_raises_config_entry_auth_failed(recorder_mock, hass: HomeAssistant, monkeypatch) -> None:
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    async def _raise_invalid_auth(*args, **kwargs):
        raise InvalidAuth("bad credentials")

    monkeypatch.setattr("custom_components.columbia_gas_ohio.coordinator.authenticate", _raise_invalid_auth)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_cannot_connect_raises_update_failed(recorder_mock, hass: HomeAssistant, monkeypatch) -> None:
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    async def _raise_cannot_connect(*args, **kwargs):
        raise CannotConnect("portal unreachable")

    monkeypatch.setattr("custom_components.columbia_gas_ohio.coordinator.authenticate", _raise_cannot_connect)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_no_accounts_raises_update_failed(recorder_mock, hass: HomeAssistant, monkeypatch) -> None:
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    async def _noop_authenticate(*args, **kwargs):
        return None

    async def _empty_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr("custom_components.columbia_gas_ohio.coordinator.authenticate", _noop_authenticate)
    monkeypatch.setattr("custom_components.columbia_gas_ohio.coordinator.list_accounts", _empty_accounts)

    with pytest.raises(UpdateFailed, match="no accounts"):
        await coordinator._async_update_data()


def test_statistic_id_sanitizes_dashes_in_account_id() -> None:
    meter = Meter(account_id="104758-000001", meter_id="900000001", utility_type=UtilityType.GAS)
    assert _statistic_id(meter) == "columbia_gas_ohio:gas_900000001"

    account = Account(account_id="104758-000001")
    assert _bill_statistic_id(account) == "columbia_gas_ohio:104758_000001_bill_amount"


async def test_options_configure_update_interval(recorder_mock, hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "hunter2"},
        options={"update_interval_hours": 6},
    )
    entry.add_to_hass(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    assert coordinator.update_interval.total_seconds() == 6 * 3600


async def test_options_default_when_unset(recorder_mock, hass: HomeAssistant) -> None:
    entry = _entry(hass)
    coordinator = ColumbiaGasCoordinator(hass, entry)

    assert coordinator.update_interval.total_seconds() == 24 * 3600
