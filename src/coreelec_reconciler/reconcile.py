"""Observe, plan, apply, verify.

A Run reads the Device, diffs each Resource against Desired State, optionally
applies the Changes, and then re-plans to confirm Convergence. There is no run
store and no rollback: an interrupted Run fails forward and the same command
run again is what reaches Convergence (ADR 0009).

Some Changes require an Effect — a disruptive consequence such as restarting
Kodi. The Run takes each Effect once, around the whole apply, and gives it
back even when a Change failed partway: never leave the television dead.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TextIO

from . import kodi_settings
from .config import DesiredState, KodiSetting, KodiSettings, SmartPlaylist
from .device import Device, DeviceError
from .playlist import render

KODI_SERVICE = "kodi.service"


@dataclass(frozen=True)
class PlaylistChange:
    """A Smart Playlist document that differs from its Desired State."""

    playlist: SmartPlaylist
    action: str
    observed: str | None
    desired: str
    effect: str | None = None

    @property
    def address(self) -> str:
        return self.playlist.path

    def report(self) -> Iterator[str]:
        yield f"{self.action} {self.address}"
        for line in difflib.unified_diff(
            (self.observed or "").splitlines(keepends=True),
            self.desired.splitlines(keepends=True),
            fromfile="observed",
            tofile="desired",
            n=3,
        ):
            yield line.rstrip("\n")


@dataclass(frozen=True)
class SettingChange:
    """One Kodi setting inside a document Kodi rewrites from memory on exit."""

    document: str
    setting: KodiSetting
    action: str
    observed: str | None
    desired: str
    effect: str | None = KODI_SERVICE

    @property
    def address(self) -> str:
        return f"{self.document}#{self.setting.setting}"

    def report(self) -> Iterator[str]:
        observed = "(unset)" if self.observed is None else self.observed
        yield f"{self.action} {self.address}: {observed} -> {self.desired}"


Change = PlaylistChange | SettingChange


def _guard_identity(device: Device, expected: str) -> None:
    """A wrong Device fails here, before anything is mutated."""

    observed = device.observed_hostname()
    if observed.casefold() != expected.casefold():
        raise DeviceError(
            f"{expected} answers to the hostname {observed}: refusing to "
            f"reconcile a Device that is not {expected}"
        )


def _read_settings_document(device: Device, path: str) -> str | None:
    """The settings document, rejected here rather than half-written later."""

    document = device.read(path)
    try:
        kodi_settings.validate(document)
    except kodi_settings.SettingsError as error:
        raise DeviceError(
            f"{path} on {device.hostname} cannot be read as a Kodi settings "
            f"document: {error}"
        ) from error
    return document


def _plan(device: Device, desired: DesiredState) -> list[Change]:
    changes: list[Change] = []
    for playlist in desired.playlists:
        wanted = render(playlist)
        observed_file = device.read(playlist.path)
        if observed_file == wanted:
            continue
        changes.append(
            PlaylistChange(
                playlist=playlist,
                action="create" if observed_file is None else "update",
                observed=observed_file,
                desired=wanted,
            )
        )

    declared = desired.kodi_settings
    document = _read_settings_document(device, declared.document)
    for setting in declared.settings:
        observed = kodi_settings.observe(document, setting.setting)
        if observed == setting.value:
            continue
        changes.append(
            SettingChange(
                document=declared.document,
                setting=setting,
                action="create" if observed is None else "update",
                observed=observed,
                desired=setting.value,
            )
        )
    return changes


def _summarise(changes: list[Change]) -> str:
    if not changes:
        return "no changes"
    return f"{len(changes)} change" + ("s" if len(changes) > 1 else "")


def _write_settings(device: Device, declared: KodiSettings) -> None:
    """Converges every declared setting in one write of the document.

    Both the Observation and the set of settings written are taken after the
    service stopped, never from the Plan: Kodi rewrites the document from
    memory as it exits, so a setting that looked converged while Kodi ran may
    have reverted by the time the write happens.
    """

    observed = _read_settings_document(device, declared.document)
    wanted = {setting.setting: setting.value for setting in declared.settings}
    device.write(
        declared.document, kodi_settings.rewrite(observed, wanted), mode="0600"
    )


def _apply(
    device: Device, desired: DesiredState, changes: list[Change], out: TextIO
) -> None:
    units = sorted({change.effect for change in changes if change.effect is not None})
    for unit in units:
        print(f"stopping {unit}", file=out)
        device.stop_service(unit)

    applied: list[Change] = []
    failure: DeviceError | None = None
    try:
        for change in changes:
            if isinstance(change, PlaylistChange):
                device.write(change.playlist.path, change.desired)
                applied.append(change)
        settings = [change for change in changes if isinstance(change, SettingChange)]
        if settings:
            _write_settings(device, desired.kodi_settings)
            applied.extend(settings)
    except DeviceError as error:
        failure = error

    if len(applied) == len(changes):
        print(f"applied {_summarise(changes)}", file=out)
    else:
        print(f"applied {len(applied)} of {_summarise(changes)}", file=out)
        for change in changes:
            if change not in applied:
                print(f"not applied {change.address}", file=out)

    for unit in units:
        # Fail Forward: the television comes back up even when a Change failed.
        print(f"starting {unit}", file=out)
        try:
            device.start_service(unit)
        except DeviceError as error:
            if failure is None:
                failure = error
            else:
                print(f"error: {error}", file=out)

    if failure is not None:
        raise failure


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
        for line in change.report():
            print(line, file=out)

    if not apply:
        print(f"plan: {_summarise(changes)}", file=out)
        return

    _apply(device, desired, changes, out)

    # Verification is Convergence: the planning the Run started with, run
    # again, must find nothing left to do.
    remaining = _plan(device, desired)
    if remaining:
        addresses = ", ".join(change.address for change in remaining)
        raise DeviceError(
            f"{addresses} on {desired.hostname} still differs from its "
            "Desired State after being applied"
        )
    print("verification: converged", file=out)
