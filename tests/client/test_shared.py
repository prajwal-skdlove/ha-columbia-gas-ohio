"""Tests for client/shared.py's retry-wrapped GET."""

from __future__ import annotations

import httpx
import pytest
import respx

from client import shared


@respx.mock
async def test_get_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    route = respx.get(f"{shared.BASE_URL}/flaky").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, text="ok")]
    )

    async with httpx.AsyncClient() as client:
        resp = await shared.get(client, "/flaky")

    assert resp.text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_get_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/always-down").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await shared.get(client, "/always-down")
