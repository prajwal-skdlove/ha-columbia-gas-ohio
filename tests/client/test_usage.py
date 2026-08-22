"""Tests for client/usage.py."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from client import shared
from client.models import Granularity, Meter, UtilityType
from client.usage import fetch_monthly

USAGE_CSV = """Date,Type of Read,Avg Temp,Number of Days,Units Used, Yearly Usage, Bill Amount, Cost per Day
8/4/2026,ACTUAL READING,75.90,29,0.00,0%,$56.42,$1.95
6/4/2026,ACTUAL READING,63.60,30,8.00,-60%,$61.65,$2.06
9/4/2024,ACTUAL READING,74.80,30,0.00,0%,$51.00,$1.70
"""

USAGE_CSV_WITH_UNPARSEABLE_ROW = """Date,Type of Read,Avg Temp,Number of Days,Units Used, Yearly Usage, Bill Amount, Cost per Day
8/4/2026,ACTUAL READING,75.90,29,0.00,0%,$56.42,$1.95
not-a-date,ACTUAL READING,,,not-a-number,0%,$1.00,$1.00
"""

EMPTY_CSV = "Date,Type of Read,Avg Temp,Number of Days,Units Used, Yearly Usage, Bill Amount, Cost per Day\n"

NO_HEADER_CSV = ""


def _meter() -> Meter:
    return Meter(account_id="555000111022", meter_id="555000111022", utility_type=UtilityType.GAS)


@respx.mock
async def test_fetch_monthly_parses_period_and_value(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/UsageHistoryAllCsv/0").mock(return_value=httpx.Response(200, text=USAGE_CSV))

    async with httpx.AsyncClient() as client:
        readings = await fetch_monthly(client, _meter())

    assert len(readings) == 3
    newest = next(r for r in readings if r.period_end == datetime(2026, 8, 4, tzinfo=UTC))
    assert newest.period_start == datetime(2026, 7, 6, tzinfo=UTC)  # 29 days before
    assert newest.value == 0.0
    assert newest.unit == "Ccf"
    assert newest.granularity == Granularity.MONTHLY

    june = next(r for r in readings if r.period_end == datetime(2026, 6, 4, tzinfo=UTC))
    assert june.value == 8.0


@respx.mock
async def test_fetch_monthly_skips_unparseable_rows(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/UsageHistoryAllCsv/0").mock(
        return_value=httpx.Response(200, text=USAGE_CSV_WITH_UNPARSEABLE_ROW)
    )

    async with httpx.AsyncClient() as client:
        readings = await fetch_monthly(client, _meter())

    assert len(readings) == 1


@respx.mock
async def test_fetch_monthly_empty_csv(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/UsageHistoryAllCsv/0").mock(return_value=httpx.Response(200, text=EMPTY_CSV))

    async with httpx.AsyncClient() as client:
        assert await fetch_monthly(client, _meter()) == []


@respx.mock
async def test_fetch_monthly_no_header_yields_empty(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/UsageHistoryAllCsv/0").mock(return_value=httpx.Response(200, text=NO_HEADER_CSV))

    async with httpx.AsyncClient() as client:
        assert await fetch_monthly(client, _meter()) == []
