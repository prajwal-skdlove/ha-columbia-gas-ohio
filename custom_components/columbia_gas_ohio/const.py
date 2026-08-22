"""Constants for the Columbia Gas of Ohio integration."""

from __future__ import annotations

DOMAIN = "columbia_gas_ohio"

CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"

# The portal's usage/billing history only advances once a month (one meter
# read per billing cycle) -- polling more often than this just re-requests
# data that hasn't changed yet.
DEFAULT_UPDATE_INTERVAL_HOURS = 24
