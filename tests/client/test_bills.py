"""Tests for client/bills.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from client import shared
from client.bills import fetch_bills
from client.models import Account

BILLING_CSV = """Bill Date,Type,Description,Amount
8/5/2026,Bill,Bill due on 2026-08-19,$56.42
7/7/2026,Bill,Bill due on 2026-07-21,$56.42
6/5/2026,Bill,Bill due on 2026-06-19,$61.65
"""

BILLING_CSV_WITH_NON_BILL_ROW = """Bill Date,Type,Description,Amount
8/5/2026,Bill,Bill due on 2026-08-19,$56.42
7/20/2026,Payment,Payment received,$56.42
"""

BILLING_CSV_MALFORMED = """Bill Date,Type,Description,Amount
not-a-date,Bill,Bill due on 2026-08-19,$56.42
"""

EMPTY_CSV = "Bill Date,Type,Description,Amount\n"

NO_HEADER_CSV = ""


def _account() -> Account:
    return Account(account_id="555000111022")


@respx.mock
async def test_fetch_bills_parses_amount_and_due_date(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=BILLING_CSV))

    async with httpx.AsyncClient() as client:
        bills = await fetch_bills(client, _account())

    assert len(bills) == 3
    newest = next(b for b in bills if b.period_end == datetime(2026, 8, 5, tzinfo=UTC))
    assert newest.amount_total == 56.42
    assert newest.due_date == datetime(2026, 8, 19, tzinfo=UTC)
    assert newest.period_start == datetime(2026, 7, 7, tzinfo=UTC)


@respx.mock
async def test_fetch_bills_oldest_bill_uses_fallback_period_start(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=BILLING_CSV))

    async with httpx.AsyncClient() as client:
        bills = await fetch_bills(client, _account())

    oldest = next(b for b in bills if b.period_end == datetime(2026, 6, 5, tzinfo=UTC))
    assert oldest.period_start == datetime(2026, 6, 5, tzinfo=UTC) - timedelta(days=30)


@respx.mock
async def test_fetch_bills_skips_non_bill_rows(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(
        return_value=httpx.Response(200, text=BILLING_CSV_WITH_NON_BILL_ROW)
    )

    async with httpx.AsyncClient() as client:
        bills = await fetch_bills(client, _account())

    assert len(bills) == 1
    assert bills[0].amount_total == 56.42


@respx.mock
async def test_fetch_bills_skips_malformed_rows(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(
        return_value=httpx.Response(200, text=BILLING_CSV_MALFORMED)
    )

    async with httpx.AsyncClient() as client:
        assert await fetch_bills(client, _account()) == []


@respx.mock
async def test_fetch_bills_empty_csv(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=EMPTY_CSV))

    async with httpx.AsyncClient() as client:
        assert await fetch_bills(client, _account()) == []


@respx.mock
async def test_fetch_bills_no_header_yields_empty(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/BillingHistoryAllCsv").mock(return_value=httpx.Response(200, text=NO_HEADER_CSV))

    async with httpx.AsyncClient() as client:
        assert await fetch_bills(client, _account()) == []
