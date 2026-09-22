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
import fnmatch
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import TextIO

from . import kodi_settings, shortcut
from .config import DesiredState, KodiSetting, Platform, SettingsDocument
from .device import Device, DeviceError
from .playlist import render

# Where the Device states what it is. `/etc/os-release` is a defined
# `KEY=value` document, so the Guard asserts on keys rather than grepping the
# file: `coreelec` appears in `HOME_URL` and `BUG_REPORT_URL` too, and a
# substring match therefore passes on a Device whose `ID` is something else
# entirely. `/etc/release` is genuinely one line of free text.
OS_RELEASE = "/etc/os-release"
RELEASE = "/etc/release"

# `tz-data.service` is a oneshot reading `TIMEZONE` from the cache document
# and relinking `/var/run/localtime`, which `/etc/localtime` points at. A
# `systemctl start` therefore returns after `ExecStart` — nothing to poll,
# and no partial state — and the link is the unambiguous answer to whether it
# worked.
TZ_DATA_SERVICE = "tz-data.service"
TIMEZONE = "TIMEZONE"
TIMEZONE_CACHE = "/storage/.cache/timezone"
LOCALTIME = "/var/run/localtime"
ZONEINFO = "/usr/share/zoneinfo"

# The unit a Settings Document disturbs. Kodi owns most of them; a document
# that is not Kodi's names the unit that reads it here. A Profile does not
# declare this and could not be trusted with it (ADR 0013): a document that
# could state its unit could omit it, and an omitted unit is the one mistake
# nothing catches — the write lands, the document converges, verification
# passes, and the Device keeps yesterday's zone with nothing to notice.
KODI_SERVICE = "kodi.service"
SERVICE_EFFECTS = {TIMEZONE_CACHE: TZ_DATA_SERVICE}

# The skin's own rebuild trigger. `script.skinvariables` compiles a view-types
# document into an XML include inside the skin, and `Includes_Fallbacks.xml`
# defines `Action_BuildViews` as an empty include that the compiled file
# overrides to "trigger refresh ... and then not again because it will then
# overwrite the file". Writing this stub over the compiled include therefore
# arms the rebuild, and the compile disarms it by replacing the file.
#
# The skin ships that file untracked, so there is no pristine copy to restore
# and the stub is authored here (ADR 0015). Emptying the file instead would
# not work: the reference would resolve to the empty fallback and nothing
# would rebuild.
VIEW_REBUILD_STUB = """\
<?xml version="1.0" encoding="UTF-8"?>
<includes>
    <include name="Action_BuildViews">
        <onload>RunScript(script.skinvariables,action=buildviews)</onload>
    </include>
</includes>
"""

# How long a Run waits for the skin to load and compile. `start_service`
# returns when systemd started Kodi, not when the skin loaded.
REBUILD_ATTEMPTS = 240
REBUILD_DELAY = 1.0


@dataclass(frozen=True)
class DocumentChange:
    """A document the Reconciler renders whole and that differs on the Device.

    A Smart Playlist and a Shortcut Node are both of this kind: the Reconciler
    owns every byte, so the Observation is compared against the rendering and
    the whole file is replaced.
    """

    address: str
    action: str
    observed: str | None
    desired: str
    mode: str = "0644"
    effect: str | None = None

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
    """One State Address inside a document that holds many.

    `effect` is the unit the Change disturbs: `kodi.service` for a document
    Kodi rewrites from memory on exit, and whatever unit reads a `shell_vars`
    document for one of those.
    """

    document: str
    setting: KodiSetting
    action: str
    observed: str | None
    desired: str | None
    effect: str | None = None
    rebuild: str | None = None

    @property
    def address(self) -> str:
        return f"{self.document}#{self.setting.setting}"

    def report(self) -> Iterator[str]:
        # A value Desired State names rather than holds is never printed, and
        # neither is what the Device holds for it: the Observation of a
        # credential is the credential. The key is what names it, and the key
        # is documented in the open.
        if self.setting.named_by is not None:
            yield f"{self.action} {self.address}: named by {self.setting.named_by}"
            return
        observed = "(unset)" if self.observed is None else self.observed
        desired = "(cleared)" if self.desired is None else self.desired
        origin = ""
        if self.setting.transform is not None:
            origin = f" ({self.setting.transform} of {self.setting.declared})"
        yield f"{self.action} {self.address}: {observed} -> {desired}{origin}"


Change = DocumentChange | SettingChange


def _guard_identity(device: Device, expected: str) -> None:
    """A wrong Device fails here, before anything is mutated."""

    observed = device.observed_hostname()
    if observed.casefold() != expected.casefold():
        raise DeviceError(
            f"{expected} answers to the hostname {observed}: refusing to "
            f"reconcile a Device that is not {expected}"
        )


def _os_release(document: str) -> dict[str, str]:
    """`/etc/os-release` as the keys it defines, with quotes stripped.

    The reading is deliberately forgiving of everything it is not asked
    about: this document is the operating system's and the Reconciler owns
    nothing in it, so a line a future CoreELEC adds must not turn the Guard
    into a refusal. Only the keys the Profile names are then asserted on, and
    a key the document does not hold fails naming it.
    """

    values: dict[str, str] = {}
    for line in document.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[key.strip()] = raw
    return values


def _guard_platform(device: Device, platform: Platform) -> None:
    """The Device is what the Profile claims, or the Run refuses here.

    This runs with the hostname Guard, before anything is planned, so a Run
    aimed at a Device of the wrong operating system, the wrong version or the
    wrong SoC family stops before it has written anything.
    """

    document = device.read(OS_RELEASE)
    if document is None:
        raise DeviceError(
            f"{device.hostname} does not hold {OS_RELEASE}, so it cannot be "
            f"confirmed to be {platform.id}"
        )
    held = _os_release(document)
    for key, expected in (
        ("ID", platform.id),
        ("VERSION_ID", platform.version),
        ("COREELEC_DEVICE", platform.device),
    ):
        observed = held.get(key)
        if observed != expected:
            raise DeviceError(
                f"{OS_RELEASE} on {device.hostname} holds {key}="
                f"{observed if observed is not None else '(unset)'} and the "
                f"Profile declares {expected}: refusing to reconcile it"
            )

    release = device.read(RELEASE)
    if release is None or platform.release_contains not in release:
        line = "nothing" if release is None else release.strip() or "an empty line"
        raise DeviceError(
            f"{RELEASE} on {device.hostname} holds {line} and the Profile "
            f"declares it contains {platform.release_contains}: refusing to "
            "reconcile it"
        )


def _effect(declared: SettingsDocument) -> str | None:
    """The unit a Change to `declared` disturbs, or None when no service reads it."""

    if declared.dialect in kodi_settings.KODI_DIALECTS:
        return KODI_SERVICE
    return SERVICE_EFFECTS.get(declared.document)


def _locate(device: Device, declared: SettingsDocument) -> SettingsDocument:
    """`declared` with its path resolved, when the Profile states a pattern.

    Exactly one match, or an error naming the glob and everything it found.
    Zero is as much a mistake as several: a changed television or HDMI path
    leaves the old peripheral document beside the new one, and picking either
    would write a power policy for hardware that is not there. The symptom —
    the television stops answering its own remote — is diagnosed nowhere near
    a Run, so the Run refuses instead.
    """

    if not declared.is_glob:
        return declared
    directory, _, pattern = declared.document.rpartition("/")
    matched = [
        name
        for name in device.list_directory(directory)
        if fnmatch.fnmatchcase(name, pattern)
    ]
    if len(matched) != 1:
        found = ", ".join(matched) if matched else "nothing"
        raise DeviceError(
            f"{declared.document} on {device.hostname} names exactly one "
            f"document, and it matched {found}"
        )
    return replace(declared, document=f"{directory}/{matched[0]}", is_glob=False)


def _read_settings_document(device: Device, declared: SettingsDocument) -> str | None:
    """The settings document, rejected here rather than half-written later.

    The dialect is the one the Profile declares. A document that does not read
    as that dialect fails naming itself, because reading it in the wrong
    dialect would report every declared address as unset and then plan every
    one of them as a `create`.
    """

    document = device.read(declared.document)
    try:
        kodi_settings.validate(document, declared.dialect)
    except kodi_settings.SettingsError as error:
        raise DeviceError(
            f"{declared.document} on {device.hostname} cannot be read as a "
            f"{declared.dialect} settings document: {error}"
        ) from error
    return document


def _observe(
    device: Device, declared: SettingsDocument, document: str | None, setting: str
) -> str | None:
    """The Observation of one address, or an error naming the document.

    A document may read as its dialect and still hold something at a declared
    address that is not a value — a JSON path landing on an object, say. That
    is a refusal naming the address, not a Change: overwriting it would
    discard whatever the add-on put there.
    """

    try:
        return kodi_settings.observe(document, declared.dialect, setting)
    except kodi_settings.SettingsError as error:
        raise DeviceError(
            f"{declared.document} on {device.hostname} cannot be read at "
            f"{setting}: {error}"
        ) from error


def _rendered(
    device: Device,
    address: str,
    desired: str,
    *,
    mode: str = "0644",
    effect: str | None = None,
) -> DocumentChange | None:
    """The Change a rendered document needs, or None when it already agrees."""

    observed = device.read(address)
    if observed == desired:
        return None
    return DocumentChange(
        address=address,
        action="create" if observed is None else "update",
        observed=observed,
        desired=desired,
        mode=mode,
        effect=effect,
    )


def _plan(device: Device, desired: DesiredState) -> list[Change]:
    changes: list[Change] = []
    for playlist in desired.playlists:
        change = _rendered(device, playlist.path, render(playlist))
        if change is not None:
            changes.append(change)

    # A node file is read when the skin loads, and the skin's own shortcut
    # editor holds the list it read, so a file written under a running Kodi is
    # neither live nor safe from being written back. The Run takes the stop it
    # was taking anyway.
    for node in desired.shortcut_nodes:
        change = _rendered(
            device,
            node.document,
            shortcut.render(node),
            mode="0600",
            effect=KODI_SERVICE,
        )
        if change is not None:
            changes.append(change)

    for declared in desired.documents:
        document = _read_settings_document(device, declared)
        for setting in declared.settings:
            observed = _observe(device, declared, document, setting.setting)
            if observed == setting.value:
                continue
            changes.append(
                SettingChange(
                    document=declared.document,
                    setting=setting,
                    # A Cleared Address only reaches here holding a value, so
                    # it is always an `update`; nothing is ever created to
                    # hold no value.
                    action="create" if observed is None else "update",
                    observed=observed,
                    desired=setting.value,
                    effect=_effect(declared),
                    rebuild=declared.compiles_to,
                )
            )
    return changes


def _summarise(changes: list[Change]) -> str:
    if not changes:
        return "no changes"
    return f"{len(changes)} change" + ("s" if len(changes) > 1 else "")


def _write_settings(device: Device, declared: SettingsDocument) -> None:
    """Converges every declared setting in one write of the document.

    Both the Observation and the set of settings written are taken after the
    service stopped, never from the Plan: Kodi rewrites a Settings Document
    from memory as it exits, so a setting that looked converged while Kodi ran
    may have reverted by the time the write happens.
    """

    observed = _read_settings_document(device, declared)
    wanted = {setting.setting: setting.value for setting in declared.settings}
    device.write(
        declared.document,
        kodi_settings.rewrite(observed, declared.dialect, wanted),
        mode=declared.mode,
    )


def _await_rebuild(device: Device, artifact: str, out: TextIO) -> None:
    """Waits until the add-on has compiled `artifact` over the stub.

    Having written the stub, the Run knows exactly what it is waiting to stop
    seeing, so "changed from what we wrote" is an edge rather than a guess.
    The parse is what catches a read taken mid-write, which returns a partial
    or empty file.
    """

    print(f"waiting for {artifact}", file=out)
    for attempt in range(REBUILD_ATTEMPTS):
        if attempt:
            time.sleep(REBUILD_DELAY)
        observed = device.read(artifact)
        if observed is None or observed == VIEW_REBUILD_STUB:
            continue
        try:
            ElementTree.fromstring(observed)
        except ElementTree.ParseError:
            continue
        print(f"rebuilt {artifact}", file=out)
        return
    raise DeviceError(
        f"{artifact} on {device.hostname} was not rebuilt within "
        f"{REBUILD_ATTEMPTS}s of Kodi starting"
    )


def _verify_timezone(device: Device, changes: list[Change], out: TextIO) -> None:
    """The link `tz-data.service` just wrote names the declared zone.

    The unit reads `TIMEZONE` from the document the Run wrote, so the zone
    the Run declared and the link the unit produced are two ends of the same
    fact and comparing them is the whole verification. This is the opposite
    of the view rebuild: one synchronous call with an unambiguous answer.
    """

    for change in changes:
        if (
            not isinstance(change, SettingChange)
            or change.document != TIMEZONE_CACHE
            or change.setting.setting != TIMEZONE
            or change.desired is None
        ):
            continue
        zone = change.desired
        observed = device.read_link(LOCALTIME)
        if observed != f"{ZONEINFO}/{zone}":
            raise DeviceError(
                f"{LOCALTIME} on {device.hostname} names "
                f"{observed if observed is not None else 'no zone'} and the "
                f"declared timezone is {zone}"
            )
        print(f"{LOCALTIME} names {zone}", file=out)


def _apply(
    device: Device, desired: DesiredState, changes: list[Change], out: TextIO
) -> None:
    units = sorted({change.effect for change in changes if change.effect is not None})
    for unit in units:
        print(f"stopping {unit}", file=out)
        device.stop_service(unit)

    applied: list[Change] = []
    armed: list[str] = []
    failure: DeviceError | None = None
    try:
        for change in changes:
            if isinstance(change, DocumentChange):
                device.write(change.address, change.desired, mode=change.mode)
                applied.append(change)
        for declared in desired.documents:
            settings = [
                change
                for change in changes
                if isinstance(change, SettingChange)
                and change.document == declared.document
            ]
            if not settings:
                continue
            _write_settings(device, declared)
            applied.extend(settings)
        # The compiled artifact is stale the moment its source changed. Arming
        # is a file write while Kodi is stopped; the restart below is what
        # fires it (ADR 0015).
        for artifact in sorted(
            {
                change.rebuild
                for change in changes
                if isinstance(change, SettingChange) and change.rebuild is not None
            }
        ):
            print(f"arming {artifact}", file=out)
            device.write(artifact, VIEW_REBUILD_STUB)
            armed.append(artifact)
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

    if failure is None:
        if TZ_DATA_SERVICE in units:
            _verify_timezone(device, changes, out)
        for artifact in armed:
            _await_rebuild(device, artifact, out)

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
    _guard_platform(device, desired.platform)

    # A document the Profile names by pattern is resolved once, before any
    # Change is planned and so before anything is written.
    desired = replace(
        desired,
        documents=tuple(_locate(device, declared) for declared in desired.documents),
    )

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
