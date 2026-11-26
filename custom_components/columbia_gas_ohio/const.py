"""Constants for the Columbia Gas of Ohio integration."""

from __future__ import annotations

DOMAIN = "columbia_gas_ohio"

CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
# Off by default: attributes are stored in Home Assistant's history database
# and are visible to dashboards, voice assistants and anything else that can
# read states, so the service address and account holder's name stay out
# of them unless the user opts in.
CONF_EXPOSE_ACCOUNT_DETAILS = "expose_account_details"

# The portal's usage/billing history only advances once a month (one meter
# read per billing cycle) -- polling more often than this just re-requests
# data that hasn't changed yet.
DEFAULT_UPDATE_INTERVAL_HOURS = 24
DEFAULT_EXPOSE_ACCOUNT_DETAILS = False
