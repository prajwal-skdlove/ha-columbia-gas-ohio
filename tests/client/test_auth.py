"""Tests for client/auth.py: the plain form-POST login flow."""

from __future__ import annotations

import httpx
import pytest
import respx

from client import shared
from client.auth import authenticate
from client.exceptions import CannotConnect, InvalidAuth

LOGIN_PAGE = """
<html><body>
<form id="CustomerPortalLogin" method="post" action="/login">
    <input type="hidden" name="ReturnUrl" value="/" />
    <input type="text" name="Username" />
    <input type="password" name="Password" />
    <input type="checkbox" name="rememberme" value="true" />
</form>
</body></html>
"""

DASHBOARD_AFTER_LOGIN = "<html><body><div>Welcome</div></body></html>"


@respx.mock
async def test_authenticate_success(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))
    post_route = respx.post(f"{shared.BASE_URL}/login").mock(
        return_value=httpx.Response(200, text=DASHBOARD_AFTER_LOGIN)
    )

    async with httpx.AsyncClient() as client:
        await authenticate(client, "user@example.com", "hunter2")

    sent = post_route.calls.last.request
    body = sent.content.decode()
    assert "Username=user%40example.com" in body
    assert "hunter2" in body  # sent to the portal, never logged


@respx.mock
async def test_authenticate_raises_invalid_auth_when_login_form_persists(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))
    respx.post(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))

    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidAuth):
            await authenticate(client, "user@example.com", "wrong")


@respx.mock
async def test_authenticate_raises_cannot_connect_on_http_error_fetching_login_page(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        with pytest.raises(CannotConnect):
            await authenticate(client, "u", "p")


@respx.mock
async def test_authenticate_raises_cannot_connect_on_http_error_posting_login(monkeypatch):
    monkeypatch.setattr(shared, "REQUEST_DELAY_SECONDS", 0)
    respx.get(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(200, text=LOGIN_PAGE))
    respx.post(f"{shared.BASE_URL}/login").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        with pytest.raises(CannotConnect):
            await authenticate(client, "u", "p")
