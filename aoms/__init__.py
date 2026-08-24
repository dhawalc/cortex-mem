"""Core contracts and application services for AOMS v2."""

from aoms.application import AOMSApplication
from aoms.settings import AOMSSettings
from aoms.version import __version__

__all__ = ["AOMSApplication", "AOMSSettings", "__version__"]
