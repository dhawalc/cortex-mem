#!/usr/bin/env python3
"""Standalone backup watchdog for cron; exits non-zero when a check FAILs.

Shares its implementation with ``cortex-mem backup-status`` so the scheduled
check and the interactive one can never disagree about what "healthy" means.

    aoms-backup-status.py [--json] [--strict] [--skip-remote]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aoms.ops.backup_status import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
