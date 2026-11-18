"""Coordinator for the Columbia Gas of Ohio integration.

Logs in to the portal, fetches the account/meter/readings/bills, and
imports historical readings into Home Assistant's long-term statistics so
usage shows up correctly in the Energy dashboard -- mirroring how the
built-in Opower integration (`homeassistant/components/opower`) feeds the
Energy dashboard from a utility portal with no native HA statistics API,
and how `ha-westerville-utilities`' coordinator does the same thing for a
different portal.

Simpler than that sibling integration in one respect: the portal has no
hourly/daily AMI data and no chunked date-range API -- `fetch_monthly`
always returns the portal's full retained history (~24 months) in one
request, so there's no backfill/incremental branching to do here. New
statistics are just whatever's newer than the last one Home Assistant
already has.

We use *external* statistics (`async_add_external_statistics`, ids of the
form `columbia_gas_ohio:<meter>`) rather than statistics tied to a sensor
entity's own id, for the same reason as the Westerville integration: entity
IDs can be renamed and don't exist yet on the very first coordinator
refresh.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

import httpx

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .client import Account, Bill, CannotConnect, InvalidAuth, Meter, authenticate
from .client.accounts import list_accounts, list_meters
from .client.bills import fetch_bills
from .client.usage import fetch_monthly
from .const import (
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type ColumbiaGasConfigEntry = ConfigEntry[ColumbiaGasCoordinator]

_CONSUMPTION_UNIT = UnitOfVolume.CENTUM_CUBIC_FEET
_CONSUMPTION_UNIT_CLASS = VolumeConverter.UNIT_CLASS


@dataclass
class MeterData:
    """Latest known state for the account's gas meter, for the sensor platform."""

    meter: Meter
    latest_value: float | None


@dataclass
class ColumbiaGasData:
    """Data handed to sensor entities after each coordinator refresh."""

    accounts: dict[str, Account]
    meters: dict[str, MeterData]
    bills: dict[str, Bill]  # account_id -> most recent bill
    last_updated: datetime = field(default_factory=dt_util.utcnow)


def _sanitize_id_part(value: str) -> str:
    """Make a value safe for use inside a statistic_id.

    Statistic ids only allow lowercase letters, digits, and underscores
    (see homeassistant.core.VALID_STATISTIC_ID).
    """
    return value.lower().replace("-", "_").strip("_")


def _statistic_id(meter: Meter) -> str:
    return f"{DOMAIN}:gas_{_sanitize_id_part(meter.meter_id)}"


def _bill_statistic_id(account: Account) -> str:
    return f"{DOMAIN}:{_sanitize_id_part(account.account_id)}_bill_amount"


def _bill_cost_statistic_id(account: Account) -> str:
    return f"{DOMAIN}:{_sanitize_id_part(account.account_id)}_bill_cost"


def _bill_cost_start(bill: Bill) -> datetime:
    """Local midnight on the bill's period_end date.

    The portal gives a bare date, parsed as UTC midnight. In a US timezone
    that instant is the previous local evening, so a bill dated the 1st
    would land in the previous month's cost.
    """
    return dt_util.start_of_local_day(bill.period_end.date())


def _with_month_anchors(
    stats: list[StatisticData], prior_start_ts: float | None, prior_sum: float
) -> list[StatisticData]:
    """Add zero-change rows at local midnight on the 1st of each month.

    A meter read monthly yields about one row a month, so a calendar
    month can hold none -- and a month with no row is absent from Home
    Assistant's monthly statistics instead of showing a change of zero.
    Each anchor repeats the cumulative sum of the row before it.

    `stats` must be sorted by start. Anchors cover the span from the
    last already-imported row (`prior_start_ts`, if any) to the last new
    row, and never go past it: the newest row has to stay a real one, or
    the next refresh would read an anchor's start as "newest imported" and
    drop real readings dated before it. A real row at the same instant
    always wins over an anchor.
    """
    if not stats:
        return stats
    starts = [s["start"] for s in stats]
    first = dt_util.utc_from_timestamp(prior_start_ts) if prior_start_ts is not None else starts[0]
    last = starts[-1]
    taken = set(starts)

    anchors: list[StatisticData] = []
    month = dt_util.as_local(first).date().replace(day=1)
    while (anchor_start := dt_util.start_of_local_day(month)) < last:
        if anchor_start > first and anchor_start not in taken:
            idx = bisect_left(starts, anchor_start)
            carried_sum = stats[idx - 1]["sum"] if idx else prior_sum
            anchors.append(StatisticData(start=anchor_start, state=0.0, sum=carried_sum))
        month = (month + timedelta(days=32)).replace(day=1)
    return sorted(stats + anchors, key=lambda s: s["start"])


class ColumbiaGasCoordinator(DataUpdateCoordinator[ColumbiaGasData]):
    """Fetches Columbia Gas of Ohio data and updates HA statistics."""

    config_entry: ColumbiaGasConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ColumbiaGasConfigEntry) -> None:
        options = config_entry.options
        update_interval_hours = options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(hours=update_interval_hours),
        )
        self._username: str = config_entry.data[CONF_USERNAME]
        self._password: str = config_entry.data[CONF_PASSWORD]
        # A dedicated client (not the shared HA-wide one) so this entry's
        # login-session cookies never mix with another entry's.
        self._client: httpx.AsyncClient = create_async_httpx_client(
            hass, cookies=httpx.Cookies(), follow_redirects=True, timeout=30.0
        )

    async def _async_update_data(self) -> ColumbiaGasData:
        try:
            await authenticate(self._client, self._username, self._password)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("Columbia Gas rejected the account credentials") from err
        except CannotConnect as err:
            raise UpdateFailed(f"Could not reach the Columbia Gas portal: {err}") from err

        try:
            accounts = await list_accounts(self._client)
        except httpx.HTTPError as err:
            raise UpdateFailed(f"Error listing Columbia Gas accounts: {err}") from err

        if not accounts:
            raise UpdateFailed("Logged in to Columbia Gas but found no accounts on this login")

        accounts_by_id: dict[str, Account] = {}
        meters_by_id: dict[str, MeterData] = {}
        bills_by_account: dict[str, Bill] = {}

        for account in accounts:
            accounts_by_id[account.account_id] = account

            try:
                bills = await fetch_bills(self._client, account)
            except httpx.HTTPError as err:
                _LOGGER.warning("Error fetching bills for account %s: %s", account.account_id, err)
                bills = []
            if bills:
                bills_by_account[account.account_id] = max(bills, key=lambda b: b.period_end)
                await self._async_update_bill_statistics(account, bills)

            meters = await list_meters(self._client, account)
            for meter in meters:
                try:
                    meters_by_id[meter.meter_id] = await self._async_update_meter_statistics(meter)
                except httpx.HTTPError as err:
                    _LOGGER.warning(
                        "Error fetching readings for meter %s this cycle; will retry next cycle: %s",
                        meter.meter_id, err,
                    )

        return ColumbiaGasData(
            accounts=accounts_by_id,
            meters=meters_by_id,
            bills=bills_by_account,
        )

    async def _async_update_meter_statistics(self, meter: Meter) -> MeterData:
        """Fetch the meter's usage history and import new readings as HA statistics.

        Returns the meter's latest known cumulative value (for the sensor's
        live state), regardless of whether any *new* statistics were found
        this cycle.
        """
        statistic_id = _statistic_id(meter)
        recorder = get_instance(self.hass)

        last_stat = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        prior_sum = 0.0
        last_start: float | None = None
        if last_stat:
            row = last_stat[statistic_id][0]
            prior_sum = float(row.get("sum") or 0.0)
            last_start = row["start"]

        readings = sorted(await fetch_monthly(self._client, meter), key=lambda r: r.period_start)
        if last_start is not None:
            readings = [r for r in readings if r.period_start.timestamp() > last_start]

        if not readings:
            _LOGGER.debug("Meter %s: no new readings this cycle", meter.meter_id)
            return MeterData(meter=meter, latest_value=prior_sum or None)

        running_sum = prior_sum
        stats: list[StatisticData] = []
        for reading in readings:
            running_sum += reading.value
            stats.append(StatisticData(start=reading.period_start, state=reading.value, sum=running_sum))
        stats = _with_month_anchors(stats, last_start, prior_sum)

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Columbia Gas meter {meter.meter_id}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=_CONSUMPTION_UNIT_CLASS,
            unit_of_measurement=_CONSUMPTION_UNIT,
        )
        _LOGGER.debug("Meter %s: importing %d new statistic(s)", meter.meter_id, len(stats))
        async_add_external_statistics(self.hass, metadata, stats)

        return MeterData(meter=meter, latest_value=running_sum)

    async def _async_update_bill_statistics(self, account: Account, bills: list[Bill]) -> None:
        """Import bill amounts as two cumulative statistics.

        `_bill_amount` is dated at each bill's period_start (the original
        series, kept so existing history stays valid). `_bill_cost` is
        dated at period_end, when the cost is actually incurred.
        """
        await self._async_import_bill_series(
            account,
            bills,
            statistic_id=_bill_statistic_id(account),
            name=f"Columbia Gas bill amount ({account.account_id})",
            dated_at=lambda bill: bill.period_start,
        )
        await self._async_import_bill_series(
            account,
            bills,
            statistic_id=_bill_cost_statistic_id(account),
            name=f"Columbia Gas bill cost ({account.account_id})",
            dated_at=_bill_cost_start,
        )

    async def _async_import_bill_series(
        self,
        account: Account,
        bills: list[Bill],
        *,
        statistic_id: str,
        name: str,
        dated_at: Callable[[Bill], datetime],
    ) -> None:
        """Import bill amounts as a cumulative HA statistic, month over month.

        Mirrors _async_update_meter_statistics's running-sum approach so
        bill cost is graphable in HA's history/statistics views the same
        way meter usage is.
        """
        recorder = get_instance(self.hass)

        last_stat = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        prior_sum = 0.0
        last_start: float | None = None
        if last_stat:
            row = last_stat[statistic_id][0]
            prior_sum = float(row.get("sum") or 0.0)
            last_start = row["start"]

        new_bills = sorted(bills, key=dated_at)
        if last_start is not None:
            new_bills = [b for b in new_bills if dated_at(b).timestamp() > last_start]

        if not new_bills:
            _LOGGER.debug("Account %s: no new bills for %s this cycle", account.account_id, statistic_id)
            return

        running_sum = prior_sum
        stats: list[StatisticData] = []
        for bill in new_bills:
            running_sum += bill.amount_total
            stats.append(StatisticData(start=dated_at(bill), state=bill.amount_total, sum=running_sum))
        stats = _with_month_anchors(stats, last_start, prior_sum)

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=None,
            unit_of_measurement=self.hass.config.currency or "USD",
        )
        _LOGGER.debug("Account %s: importing %d new statistic(s) for %s", account.account_id, len(stats), statistic_id)
        async_add_external_statistics(self.hass, metadata, stats)
