"""The CoreELEC Reconciler.

`main` is the package's public entry point; nothing else here is public and
tests may not import past it (ADR 0011).
"""

from __future__ import annotations

from .cli import main

__all__ = ["main"]
