"""Monthly meter-read usage for the Columbia Gas of Ohio portal, from the
`/UsageHistoryAllCsv/{account_index}` export (see `accounts.py` for where
`account_index` comes from).

Ported from `utility-reader`'s `providers/columbia_gas_oh/usage.py`. The
CSV has one row per meter read: `Date` (the read date, i.e. the period's
*end*), `Number of Days` since the previous read, `Units Used` (Ccf), plus
`Bill Amount`/`Cost per Day` -- both dropped here since `bills.py` pulls the
authoritative bill amount/due date from the separate billing-history
export, which is occasionally a few cents off from this CSV's `Bill Amount`
column (observed live).

Unlike Westerville's AMI data, the endpoint returns whatever history the
portal currently retains in one response (confirmed ~24 months, no
date-range params) -- so there's no backfill/incremental split to make
here; the coordinator dedupes against Home Assistant's own last-imported
statistic instead (see coordinator.py).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime, timedelta

import httpx

from .accounts import ACCOUNT_INDEX
from .models import Granularity, Meter, Reading
from .shared import USAGE_UNIT, get

_LOGGER = logging.getLogger(__name__)


def _parse_usage_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return []
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


async def fetch_monthly(client: httpx.AsyncClient, meter: Meter) -> list[Reading]:
    """Fetch the meter's full monthly usage history (one request)."""
    resp = await get(client, f"/UsageHistoryAllCsv/{ACCOUNT_INDEX}")
    rows = _parse_usage_csv(resp.text)
    if not rows:
        _LOGGER.debug("Meter %s: empty usage history CSV; nothing to sync", meter.meter_id)
        return []

    readings: list[Reading] = []
    for row in rows:
        try:
            period_end = datetime.strptime(row["Date"], "%m/%d/%Y").replace(tzinfo=UTC)
            days = int(float(row["Number of Days"].replace(",", "") or 0))
            value = float(row["Units Used"].replace(",", ""))
        except (KeyError, ValueError):
            _LOGGER.debug("Skipping unparseable usage history row: %s", row)
            continue

        period_start = period_end - timedelta(days=days) if days else period_end
        readings.append(
            Reading(
                meter_id=meter.meter_id,
                granularity=Granularity.MONTHLY,
                period_start=period_start,
                period_end=period_end,
                value=value,
                unit=USAGE_UNIT,
            )
        )

    _LOGGER.debug("Meter %s: parsed %d monthly reading(s)", meter.meter_id, len(readings))
    return readings
