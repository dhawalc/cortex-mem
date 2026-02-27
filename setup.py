"""
Setup with post-install hook for OpenClaw auto-integration.

When a user runs `pip install cortex-mem`, this will:
1. Install the package
2. Check for OpenClaw
3. Auto-configure if found
4. Offer workspace migration
"""

import atexit
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.install import install


def post_install():
    """Post-install hook for OpenClaw integration."""
    try:
        # Import the plugin and run auto-install
        from cortex_mem.openclaw_plugin import auto_install
        auto_install()
    except ImportError:
        # Package not yet installed, skip
        pass
    except Exception as e:
        # Don't fail the install on auto-config errors
        print(f"Note: Auto-configuration skipped ({e})")


class PostInstallCommand(install):
    """Post-install command that runs OpenClaw auto-config."""
    
    def run(self):
        install.run(self)
        # Run post-install after the package is installed
        atexit.register(post_install)


class PostDevelopCommand(develop):
    """Post-develop command that runs OpenClaw auto-config."""
    
    def run(self):
        develop.run(self)
        atexit.register(post_install)


setup(
    cmdclass={
        'install': PostInstallCommand,
        'develop': PostDevelopCommand,
    },
)
