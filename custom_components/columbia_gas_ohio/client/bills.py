"""Bill history for the Columbia Gas of Ohio portal, from the
`/BillingHistoryAllCsv` export.

Ported from `utility-reader`'s `providers/columbia_gas_oh/bills.py`. The
CSV has no billing-period-start column, only a bill date and a due date --
so, same approach as the Westerville client, `period_start` is approximated
as the *previous* (older) bill's date, falling back to 30 days before the
bill date for the oldest bill fetched.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx

from .models import Account, Bill
from .shared import get

_LOGGER = logging.getLogger(__name__)

_FALLBACK_PERIOD_DAYS = 30
_DUE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_billing_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return []
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


async def fetch_bills(client: httpx.AsyncClient, account: Account) -> list[Bill]:
    resp = await get(client, "/BillingHistoryAllCsv")
    rows = _parse_billing_csv(resp.text)
    if not rows:
        _LOGGER.debug("No bill history for account %s; nothing to sync", account.account_id)
        return []

    parsed: list[tuple[datetime, float, datetime | None]] = []
    for row in rows:
        if row.get("Type") != "Bill":
            _LOGGER.debug("Skipping non-bill billing-history row: %s", row)
            continue
        try:
            bill_date = datetime.strptime(row["Bill Date"], "%m/%d/%Y").replace(tzinfo=UTC)
            amount = float(row["Amount"].replace("$", "").replace(",", ""))
        except (KeyError, ValueError):
            _LOGGER.debug("Skipping unparseable bill row: %s", row)
            continue

        due_date = None
        due_match = _DUE_DATE_RE.search(row.get("Description", ""))
        if due_match:
            due_date = datetime.strptime(due_match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)

        parsed.append((bill_date, amount, due_date))

    # Portal returns most-recent-first; keep that assumption explicit rather
    # than relying on incoming order.
    parsed.sort(key=lambda r: r[0], reverse=True)

    bills: list[Bill] = []
    for i, (bill_date, amount, due_date) in enumerate(parsed):
        period_start = parsed[i + 1][0] if i + 1 < len(parsed) else bill_date - timedelta(days=_FALLBACK_PERIOD_DAYS)
        bills.append(
            Bill(
                account_id=account.account_id,
                period_start=period_start,
                period_end=bill_date,
                amount_total=amount,
                due_date=due_date,
            )
        )

    _LOGGER.debug("Account %s: parsed %d bill(s)", account.account_id, len(bills))
    return bills
