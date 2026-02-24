"""OpenClaw auto-integration plugin for cortex-mem.

Discovered via the ``openclaw.plugins`` entry-point group.
When a user installs cortex-mem and has OpenClaw, this plugin
auto-configures OpenClaw to use cortex-mem as its memory backend.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("cortex_mem.openclaw_plugin")

OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", "~/.openclaw/config.yaml")).expanduser()


def auto_install():
    """Run post-install integration with OpenClaw (interactive)."""
    # 1. Start service if not running
    try:
        import httpx

        r = httpx.get("http://localhost:9100/health", timeout=2.0)
        if r.status_code != 200:
            raise Exception("unhealthy")
    except Exception:
        print("Starting cortex-mem service...")
        subprocess.run([sys.executable, "-m", "cortex_mem.cli", "start", "--daemon"], check=False)

    # 2. Check if OpenClaw exists
    if not OPENCLAW_CONFIG.exists():
        print("OpenClaw config not found — skipping auto-configuration.")
        print("Install OpenClaw first, then run:  cortex-mem migrate ~/.openclaw/workspace")
        return

    # 3. Auto-configure OpenClaw
    try:
        import yaml  # type: ignore[import-untyped]

        config = yaml.safe_load(OPENCLAW_CONFIG.read_text()) or {}
        config.setdefault("memory", {})
        config["memory"]["provider"] = "cortex-mem"
        config["memory"]["url"] = "http://localhost:9100"
        OPENCLAW_CONFIG.write_text(yaml.dump(config, default_flow_style=False))
        print("OpenClaw configured to use cortex-mem")
    except Exception as exc:
        logger.warning("Could not configure OpenClaw: %s", exc)

    # 4. Offer workspace migration
    workspace = Path("~/.openclaw/workspace").expanduser()
    if workspace.exists():
        response = input("Migrate existing OpenClaw memory? [Y/n] ").strip()
        if response.lower() != "n":
            subprocess.run(
                [sys.executable, "-m", "cortex_mem.cli", "migrate", str(workspace)],
                check=False,
            )


class MemoryPlugin:
    """Entry-point object for openclaw.plugins discovery."""

    name = "cortex-mem"

    @staticmethod
    def activate():
        auto_install()


if __name__ == "__main__":
    auto_install()
