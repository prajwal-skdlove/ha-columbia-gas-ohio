"""Confirms the test harness can discover and import the integration at all."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.columbia_gas_ohio.const import DOMAIN


async def test_domain_constant() -> None:
    assert DOMAIN == "columbia_gas_ohio"


async def test_component_is_discoverable(recorder_mock, hass: HomeAssistant) -> None:
    """If this fails, custom_components/ isn't wired up for the test harness.

    recorder_mock must be listed before hass: manifest.json declares
    recorder as a hard dependency, and this plugin's recorder setup must
    resolve before the hass fixture is instantiated, not after.
    """
    result = await async_setup_component(hass, DOMAIN, {})
    assert result is True
