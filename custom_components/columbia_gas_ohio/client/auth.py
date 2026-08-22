"""Login flow for the Columbia Gas of Ohio portal at
myaccount.columbiagasohio.com.

Ported from `utility-reader`'s `providers/columbia_gas_oh/auth.py`. Plain
form POST (no CSRF token, no JS/AJAX auth) confirmed against the real login
page: GET `/login` for a session cookie, then POST
`Username`/`Password`/`rememberme`/`ReturnUrl` to that same `/login` path.
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from .exceptions import CannotConnect, InvalidAuth
from .shared import BASE_URL, get

_LOGGER = logging.getLogger(__name__)


def _has_login_form(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", {"name": "Password"}) is not None


async def authenticate(client: httpx.AsyncClient, username: str, password: str) -> None:
    """Log in to the Columbia Gas portal, populating `client`'s cookie jar.

    Never logs `username`/`password`.
    """
    try:
        await get(client, "/login")
    except httpx.HTTPError as err:
        raise CannotConnect(f"Could not reach the Columbia Gas login page: {err}") from err

    payload = {
        "ReturnUrl": "/",
        "Username": username,
        "Password": password,
        "rememberme": "false",
    }
    _LOGGER.debug("Submitting Columbia Gas login")
    try:
        login_resp = await client.post(f"{BASE_URL}/login", data=payload)
        login_resp.raise_for_status()
    except httpx.HTTPError as err:
        raise CannotConnect(f"Columbia Gas login request failed: {err}") from err

    if _has_login_form(login_resp.text):
        raise InvalidAuth("Columbia Gas rejected the supplied username/password")

    _LOGGER.debug("Columbia Gas login succeeded")
