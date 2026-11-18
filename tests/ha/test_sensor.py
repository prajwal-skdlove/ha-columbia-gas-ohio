"""Tests for sensor.py: meter usage and bill sensor entities, via a full
config entry setup (exercises __init__.py + coordinator.py + sensor.py
together).
"""

from __future__ import annotations

import httpx
import respx

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.columbia_gas_ohio.const import DOMAIN

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


@respx.mock
async def test_meter_and_bill_sensors_created_on_entry_setup(recorder_mock, hass: HomeAssistant) -> None:
    # The test hass is metric, which converts a gas sensor from Ccf to m3
    # (10 Ccf -> 28.3). Columbia Gas customers are US customary.
    hass.config.units = US_CUSTOMARY_SYSTEM
    _mock_happy_path()
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "user@example.com", "password": "hunter2"}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    meter_state = hass.states.get("sensor.gas_555000111022_usage")
    assert meter_state is not None
    assert meter_state.state == "10.0"
    assert meter_state.attributes["device_class"] == SensorDeviceClass.GAS
    assert meter_state.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING
    assert meter_state.attributes["unit_of_measurement"] == UnitOfVolume.CENTUM_CUBIC_FEET

    bill_state = hass.states.get("sensor.columbia_gas_account_555000111022_latest_bill")
    assert bill_state is not None
    assert bill_state.state == "56.42"
    assert bill_state.attributes["device_class"] == SensorDeviceClass.MONETARY
    assert bill_state.attributes["due_date"] == "2026-08-19T00:00:00+00:00"
    # Only bill in the fixture -- period_start falls back to 30 days before
    # the bill date (see client/bills.py's _FALLBACK_PERIOD_DAYS).
    assert bill_state.attributes["days_in_period"] == 30
    assert bill_state.attributes["cost_per_day"] == round(56.42 / 30, 2)
    assert bill_state.attributes["service_address"] == "456 Sample Rd"
    assert bill_state.attributes["account_holder"] == "Jane Tester"


@respx.mock
async def test_unload_entry_removes_entities(recorder_mock, hass: HomeAssistant) -> None:
    _mock_happy_path()
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "user@example.com", "password": "hunter2"}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.gas_555000111022_usage") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # Unload marks the entity unavailable rather than removing its state
    # outright (HA keeps it around, restorable, until the entity/entry is
    # actually deleted) -- that's the real, correct behavior here.
    state = hass.states.get("sensor.gas_555000111022_usage")
    assert state is not None
    assert state.state == "unavailable"
