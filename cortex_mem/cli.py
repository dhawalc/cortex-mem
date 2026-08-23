"""Compatibility import for the AOMS v2 command-line entry point."""

from aoms.cli import main

__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    main()
