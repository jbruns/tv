"""Observe, plan, apply, verify.

A Run reads the Device, diffs each Resource against Desired State, optionally
applies the Changes, and then re-reads to confirm Convergence. There is no run
store and no rollback: an interrupted Run fails forward and the same command
run again is what reaches Convergence (ADR 0009).
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TextIO

from .config import DesiredState, SmartPlaylist
from .device import Device, DeviceError
from .playlist import render


@dataclass(frozen=True)
class Change:
    playlist: SmartPlaylist
    action: str
    observed: str | None
    desired: str

    def diff(self) -> Iterator[str]:
        return difflib.unified_diff(
            (self.observed or "").splitlines(keepends=True),
            self.desired.splitlines(keepends=True),
            fromfile="observed",
            tofile="desired",
            n=3,
        )


def _guard_identity(device: Device, expected: str) -> None:
    """A wrong Device fails here, before anything is mutated."""

    observed = device.observed_hostname()
    if observed.casefold() != expected.casefold():
        raise DeviceError(
            f"{expected} answers to the hostname {observed}: refusing to "
            f"reconcile a Device that is not {expected}"
        )


def _plan(device: Device, desired: DesiredState) -> list[Change]:
    changes = []
    for playlist in desired.playlists:
        wanted = render(playlist)
        observed = device.read(playlist.path)
        if observed == wanted:
            continue
        changes.append(
            Change(
                playlist=playlist,
                action="create" if observed is None else "update",
                observed=observed,
                desired=wanted,
            )
        )
    return changes


def run(desired: DesiredState, *, apply: bool, out: TextIO) -> None:
    """Reconciles `desired`, raising DeviceError when it cannot be reached."""

    device = Device(hostname=desired.hostname, transport=desired.transport)
    print(
        f"device {desired.hostname} (room {desired.room}, profile {desired.profile})",
        file=out,
    )
    _guard_identity(device, desired.hostname)

    changes = _plan(device, desired)
    for change in changes:
        print(f"{change.action} {change.playlist.path}", file=out)
        for line in change.diff():
            print(line.rstrip("\n"), file=out)

    count = (
        "no changes"
        if not changes
        else f"{len(changes)} change" + ("s" if len(changes) > 1 else "")
    )
    if not apply:
        print(f"plan: {count}", file=out)
        return

    for change in changes:
        device.write(change.playlist.path, change.desired)
    print(f"applied {count}", file=out)

    for change in changes:
        if device.read(change.playlist.path) != change.desired:
            raise DeviceError(
                f"{change.playlist.path} on {desired.hostname} still differs "
                "from its Desired State after being written"
            )
    print("verification: converged", file=out)
