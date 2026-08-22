"""Exceptions raised by the Columbia Gas of Ohio client."""

from __future__ import annotations


class ColumbiaGasError(Exception):
    """Base class for Columbia Gas of Ohio client errors."""


class InvalidAuth(ColumbiaGasError):
    """The portal rejected the supplied username/password."""


class CannotConnect(ColumbiaGasError):
    """The portal could not be reached, or returned an unexpected response."""
