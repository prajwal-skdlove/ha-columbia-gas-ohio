"""Async client for the Columbia Gas of Ohio
(myaccount.columbiagasohio.com) utility portal.

Ported from the `utility-reader` project's `providers/columbia_gas_oh/`
adapter (https://github.com/prajwal-skdlove/utility-reader) -- see that
project's PLAN.md for how the portal's behavior was reverse-engineered.
"""

from __future__ import annotations

from .auth import authenticate
from .exceptions import CannotConnect, ColumbiaGasError, InvalidAuth
from .models import Account, Bill, Granularity, Meter, Reading, UtilityType

__all__ = [
    "Account",
    "Bill",
    "CannotConnect",
    "ColumbiaGasError",
    "Granularity",
    "InvalidAuth",
    "Meter",
    "Reading",
    "UtilityType",
    "authenticate",
]
