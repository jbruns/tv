"""Stable, secret-safe configuration diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Diagnostic:
    source: str
    line: int
    column: int
    path: tuple[str | int, ...]
    code: str
    message: str
    subject_id: str | None = None
