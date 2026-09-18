"""Evidence-only typed progress presentation."""

import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import TextIO


class ProgressKind(StrEnum):
    MILESTONE = "milestone"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressKind
    message: str


def present_progress(
    event: ProgressEvent, *, stream: TextIO = sys.stderr, quiet: bool = False
) -> None:
    if not quiet:
        print(f"[{event.kind}] {event.message}", file=stream)
