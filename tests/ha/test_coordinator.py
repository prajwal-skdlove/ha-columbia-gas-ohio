"""Tests for ColumbiaGasCoordinator: auth error mapping and statistics
import.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
import respx

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.columbia_gas_ohio.client import CannotConnect, InvalidAuth
from custom_components.columbia_gas_ohio.client.models import Account, Meter, UtilityType
from custom_components.columbia_gas_ohio.const import DOMAIN
from custom_components.columbia_gas_ohio.coordinator import (
    ColumbiaGasCoordinator,
    _bill_cost_statistic_id,
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


def _mock_happy_path(usage_csv: str = USAGE_CSV, billing_csv: str = BILLING_CSV) -> respx.Route:
    respx.get(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))
    respx.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, text=DASHBOARD_AFTER_LOGIN))
    respx.get(f"{BASE_URL}/dashboard").mock(return_value=httpx.Response(200, text=DASHBOARD_PAGE))
    respx.get(f"{BASE_URL}/UsageHistoryAllCsv/0").mock(return_value=httpx.Response(200, text=usage_csv))
    return respx.get(f"{BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=billing_csv))


def _billing_csv(*bills: tuple[str, str]) -> str:
    rows = "".join(f"{bill_date},Bill,Bill due on 2026-10-15,${amount}\n" for bill_date, amount in bills)
    return "Bill Date,Type,Description,Amount\n" + rows


ALL_FOUR_BILLS = _billing_csv(
    ("9/29/2026", "200.00"), ("8/30/2026", "150.00"), ("7/31/2026", "120.00"), ("7/1/2026", "100.00")
)
NEWEST_TWO_BILLS = _billing_csv(("9/29/2026", "200.00"), ("8/30/2026", "150.00"))
# Two readings starting Jul 6 and Oct 5, so the months between hold no row.
SPARSE_USAGE_CSV = USAGE_CSV + "11/3/2026,ACTUAL READING,50.00,29,20.00,0%,$80.00,$2.75\n"


def _local_midnight(day: date) -> float:
    return dt_util.start_of_local_day(day).timestamp()


async def _stored_sums(hass: HomeAssistant, statistic_id: str) -> dict[float, float]:
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return {row["start"]: row["sum"] for row in rows.get(statistic_id, [])}


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
async def test_bill_cost_statistic_is_dated_at_period_end_local_midnight(recorder_mock, hass: HomeAssistant) -> None:
    _mock_happy_path()
    coordinator = ColumbiaGasCoordinator(hass, _entry(hass))

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)

    cost_id = _bill_cost_statistic_id(Account(account_id="555000111022"))
    assert cost_id == "columbia_gas_ohio:555000111022_bill_cost"
    cost_stats = await hass.async_add_executor_job(get_last_statistics, hass, 1, cost_id, True, {"sum"})
    row = cost_stats[cost_id][0]
    assert row["sum"] == 56.42
    # BILLING_CSV's only bill is dated 8/5/2026.
    assert row["start"] == dt_util.start_of_local_day(date(2026, 8, 5)).timestamp()


@respx.mock
async def test_sparse_monthly_readings_get_first_of_month_anchors(recorder_mock, hass: HomeAssistant) -> None:
    sparse_csv = USAGE_CSV + "11/3/2026,ACTUAL READING,50.00,29,20.00,0%,$80.00,$2.75\n"
    _mock_happy_path(sparse_csv)
    coordinator = ColumbiaGasCoordinator(hass, _entry(hass))

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)

    statistic_id = "columbia_gas_ohio:gas_555000111022"
    rows = await hass.async_add_executor_job(get_last_statistics, hass, 10, statistic_id, True, {"sum"})
    by_start = {row["start"]: row["sum"] for row in rows[statistic_id]}
    # Readings start Jul 6 (sum 10) and Oct 5 (sum 30); Aug 1, Sep 1 and Oct 1 hold none.
    for anchor in (date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)):
        assert by_start[dt_util.start_of_local_day(anchor).timestamp()] == 10.0
    assert max(by_start.values()) == 30.0
    assert len(by_start) == 5

    # A second refresh with unchanged data must not add or alter anything.
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    again = await hass.async_add_executor_job(get_last_statistics, hass, 10, statistic_id, True, {"sum"})
    assert {row["start"]: row["sum"] for row in again[statistic_id]} == by_start


@respx.mock
async def test_bill_cost_is_rebuilt_with_bills_the_portal_no_longer_returns(
    recorder_mock, hass: HomeAssistant, monkeypatch
) -> None:
    # Four bills 30 days apart. Later the portal only returns the newest two.
    bill_route = _mock_happy_path(billing_csv=ALL_FOUR_BILLS)
    coordinator = ColumbiaGasCoordinator(hass, _entry(hass))
    cost_id = _bill_cost_statistic_id(Account(account_id="555000111022"))

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    assert (await _stored_sums(hass, cost_id))[_local_midnight(date(2026, 9, 29))] == 570.0

    # Recreate what the previous release left behind: a cost series that
    # only holds what the portal still returns.
    get_instance(hass).async_clear_statistics([cost_id])
    await async_wait_recording_done(hass)
    bill_route.mock(return_value=httpx.Response(200, text=NEWEST_TWO_BILLS))

    async def _no_older_bills(self, account, bills):
        return []

    monkeypatch.setattr(ColumbiaGasCoordinator, "_async_bills_missing_from_portal", _no_older_bills)
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    assert (await _stored_sums(hass, cost_id))[_local_midnight(date(2026, 9, 29))] == 350.0
    monkeypatch.undo()

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    rebuilt = await _stored_sums(hass, cost_id)

    # The older bills are back and every later sum, anchors included, shifted.
    assert rebuilt[_local_midnight(date(2026, 7, 1))] == 100.0
    assert rebuilt[_local_midnight(date(2026, 7, 31))] == 220.0
    assert rebuilt[_local_midnight(date(2026, 8, 1))] == 220.0
    assert rebuilt[_local_midnight(date(2026, 8, 30))] == 370.0
    assert rebuilt[_local_midnight(date(2026, 9, 1))] == 370.0
    assert rebuilt[_local_midnight(date(2026, 9, 29))] == 570.0
    assert max(rebuilt.values()) == 570.0

    # The rebuild happens once: another refresh changes nothing.
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    assert await _stored_sums(hass, cost_id) == rebuilt


@respx.mock
async def test_month_anchors_are_backfilled_across_existing_history_once(
    recorder_mock, hass: HomeAssistant, monkeypatch
) -> None:
    # Import history the way the previous release did: without anchors.
    monkeypatch.setattr(
        "custom_components.columbia_gas_ohio.coordinator._with_month_anchors",
        lambda stats, prior_start_ts, prior_sum: stats,
    )
    _mock_happy_path(SPARSE_USAGE_CSV, ALL_FOUR_BILLS)
    coordinator = ColumbiaGasCoordinator(hass, _entry(hass))
    meter_id = "columbia_gas_ohio:gas_555000111022"
    amount_id = "columbia_gas_ohio:555000111022_bill_amount"
    cost_id = _bill_cost_statistic_id(Account(account_id="555000111022"))

    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    assert len(await _stored_sums(hass, meter_id)) == 2
    assert len(await _stored_sums(hass, cost_id)) == 4
    amount_rows_before = len(await _stored_sums(hass, amount_id))
    monkeypatch.undo()

    # Nothing new on the portal, yet the stored history gains its anchors.
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    meter_sums = await _stored_sums(hass, meter_id)
    cost_sums = await _stored_sums(hass, cost_id)
    assert len(meter_sums) == 5
    assert len(cost_sums) == 6
    assert len(await _stored_sums(hass, amount_id)) > amount_rows_before
    for anchor in (date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)):
        assert meter_sums[_local_midnight(anchor)] == 10.0
    assert cost_sums[_local_midnight(date(2026, 8, 1))] == 220.0
    assert cost_sums[_local_midnight(date(2026, 9, 1))] == 370.0
    # Never past the newest real row.
    assert max(meter_sums) == datetime(2026, 10, 5, tzinfo=UTC).timestamp()
    assert max(cost_sums) == _local_midnight(date(2026, 9, 29))

    # Idempotent: every later refresh adds nothing.
    stored = (meter_sums, cost_sums, await _stored_sums(hass, amount_id))
    for _ in range(2):
        await coordinator.async_refresh()
        await async_wait_recording_done(hass)
    assert (
        await _stored_sums(hass, meter_id),
        await _stored_sums(hass, cost_id),
        await _stored_sums(hass, amount_id),
    ) == stored


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
