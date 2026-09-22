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

import datetime
import difflib
import fnmatch
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import TextIO

from . import artifact, authorized_keys, kodi_settings, shortcut
from .config import (
    AddonArtifact,
    Addresses,
    DesiredState,
    KodiSetting,
    Platform,
    SettingsDocument,
)
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
LOCALTIME = "/var/run/localtime"
ZONEINFO = "/usr/share/zoneinfo"

# The unit a Settings Document disturbs. Kodi owns most of them; a document
# that is not Kodi's names the unit that reads it here. A Profile does not
# declare this and could not be trusted with it (ADR 0013): a document that
# could state its unit could omit it, and an omitted unit is the one mistake
# nothing catches — the write lands, the document converges, verification
# passes, and the Device keeps yesterday's zone with nothing to notice.
#
# Which document that is, though, is the Profile's. The Reconciler knows the
# meaning of an address; the Profile holds the address itself (ADR 0018).
KODI_SERVICE = "kodi.service"

# `sshd.conf` is CoreELEC's own document, read by `sshd.service` as an
# `EnvironmentFile`. Its Effect is not the stop-and-start above: a stop would
# take the connection issuing it and leave nothing able to start it again.
# `sshd` is `ExecStart=/usr/sbin/sshd -D $SSH_ARGS`, so the new option only
# takes at start; `ExecReload` sends SIGHUP and the daemon re-execs from its
# original argv, so a reload would not pick it up; and the daemon is not
# socket-activated, so our session is a child in the unit's cgroup. A restart
# is therefore both necessary and fatal to the connection that asks for it,
# and the Run reconnects afterwards (ADR 0016).
SSHD_SERVICE = "sshd.service"

# How long the Run waits for the daemon it just restarted to answer again.
RECONNECT_ATTEMPTS = 20
RECONNECT_DELAY = 1.0

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
    summary: tuple[str, ...] = ()

    def report(self) -> Iterator[str]:
        yield f"{self.action} {self.address}"
        # A document whose content nobody reads is reported by name instead.
        # `authorized_keys` is the one: sixty-eight characters of base64 per
        # entry says nothing, and the entries it gains and loses say
        # everything.
        if self.summary:
            yield from self.summary
            return
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

    `restart` is the unit a Change restarts *after* the writes rather than
    stopping around them, because stopping it would take the connection the
    Run is made of.
    """

    document: str
    setting: KodiSetting
    action: str
    observed: str | None
    desired: str | None
    effect: str | None = None
    rebuild: str | None = None
    restart: str | None = None

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


@dataclass(frozen=True)
class AddonChange:
    """One add-on that is not installed at its pinned version, or not enabled.

    Installed and enabled are one Resource, because there is no add-on this
    fleet wants present but disabled or enabled but absent. Appearing in the
    Artifact Lock is the statement that both are true (ADR 0018).

    `observed` is the version `addon.xml` declares, which is what Kodi itself
    believes, and None when the add-on is not on the Device at all.
    `enabled` is what the `installed` table holds — `True`, `False`, or None
    when the table holds no row for it.
    """

    addon: AddonArtifact
    directory: str
    action: str
    observed: str | None
    enabled: bool | None
    effect: str | None = KODI_SERVICE

    @property
    def address(self) -> str:
        return self.directory

    @property
    def ships(self) -> bool:
        """Whether this Change fetches and replaces the tree, or only enables."""

        return self.observed != self.addon.version

    def report(self) -> Iterator[str]:
        yield f"{self.action} {self.directory}"
        observed = "(absent)" if self.observed is None else self.observed
        yield f"version: {observed} -> {self.addon.version}"
        if self.enabled is not True:
            held = "(no row)" if self.enabled is None else "0"
            yield f"enabled: {held} -> 1"


Change = DocumentChange | SettingChange | AddonChange


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


def _effect(addresses: Addresses, declared: SettingsDocument) -> str | None:
    """The unit a Change to `declared` disturbs, or None when no service reads it."""

    if declared.dialect in kodi_settings.KODI_DIALECTS:
        return KODI_SERVICE
    if declared.document == addresses.timezone_cache:
        return TZ_DATA_SERVICE
    return None


def _restart(addresses: Addresses, declared: SettingsDocument) -> str | None:
    """The unit a Change to `declared` restarts *after* the writes, if any."""

    return SSHD_SERVICE if declared.document == addresses.sshd_conf else None


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


def _entries(document: str | None) -> str:
    """The entries a rendering of `authorized_keys` holds, named by comment."""

    return ", ".join(authorized_keys.summarise(document)) or "none"


# Exactly the statements Kodi issues itself. `SyncInstalled` inserts only
# `(addonID, enabled, installDate)` and `EnableAddon` updates only
# `enabled` and `disabledReason`, so every other column takes its declared
# default and a future schema that adds a defaulted column still works
# (ADR 0018).
#
# The update runs first and the insert is conditional on it having matched
# nothing, so one program converges a row that exists, a row that is
# disabled, and an add-on the table has never heard of. `changes()` counts
# the rows the update *matched*, not the ones whose values moved.
ENABLE_ADDON = (
    "BEGIN;"
    " UPDATE installed SET enabled=1, disabledReason=0 WHERE addonID='{id}';"
    " INSERT INTO installed(addonID, enabled, installDate)"
    " SELECT '{id}', 1, '{installed}' WHERE changes()=0;"
    " COMMIT;"
)

# What `SELECT enabled` answers with when the table holds no row at all.
NO_ROW = ""


def _observe_addon(
    device: Device, addresses: Addresses, addon: AddonArtifact
) -> tuple[str | None, bool | None]:
    """What the Device holds for one add-on: its declared version, and enabled.

    The whole Observation is one small file and one row. Hashing the
    installed tree cannot work — the tree is the *expanded* archive, so its
    hash is never the Artifact's — and a receipt the Reconciler wrote can
    disagree with reality, while `addon.xml` is what Kodi itself believes
    (ADR 0017).
    """

    directory = f"{addresses.addons}/{addon.id}"
    manifest = device.read(f"{directory}/addon.xml")
    version: str | None = None
    if manifest is not None:
        try:
            held_id, version = artifact.declared(manifest)
        except artifact.ArtifactError as error:
            raise DeviceError(
                f"{directory}/addon.xml on {device.hostname} cannot be read: {error}"
            ) from error
        if held_id != addon.id:
            raise DeviceError(
                f"{directory} on {device.hostname} holds the add-on {held_id}: "
                "refusing to replace a directory that is not the add-on it is named for"
            )

    held = device.sqlite(
        addresses.addon_database,
        f"SELECT enabled FROM installed WHERE addonID='{addon.id}';",
    ).strip()
    if held == NO_ROW:
        return version, None
    return version, held == "1"


def _plan_addons(device: Device, desired: DesiredState, changes: list[Change]) -> None:
    """One Change per add-on that is not installed at its pin, or not enabled."""

    for addon in desired.addons:
        version, enabled = _observe_addon(device, desired.addresses, addon)
        if version == addon.version and enabled is True:
            continue
        changes.append(
            AddonChange(
                addon=addon,
                directory=f"{desired.addresses.addons}/{addon.id}",
                action="create" if version is None else "update",
                observed=version,
                enabled=enabled,
            )
        )


def _plan(device: Device, desired: DesiredState) -> list[Change]:
    changes: list[Change] = []

    # Who may log in is planned first, so a Run that also hardens the daemon
    # has put the keys in place before the daemon is restarted.
    keys = desired.authorized_keys
    rendered = authorized_keys.render(keys)
    observed = device.read(keys.document)
    if observed != rendered:
        changes.append(
            DocumentChange(
                address=keys.document,
                action="create" if observed is None else "update",
                observed=observed,
                desired=rendered,
                mode=keys.mode,
                summary=(
                    f"observed entries: {_entries(observed)}",
                    f"desired entries: {_entries(rendered)}",
                ),
            )
        )

    # An add-on is planned before the documents that configure it, and
    # applied in that order too: a setting for an add-on that is not there
    # yet is a setting Kodi discards.
    _plan_addons(device, desired, changes)

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
                    effect=_effect(desired.addresses, declared),
                    rebuild=declared.compiles_to,
                    restart=_restart(desired.addresses, declared),
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


def _await_rebuild(device: Device, compiled: str, out: TextIO) -> None:
    """Waits until the add-on has compiled the include over the stub.

    Having written the stub, the Run knows exactly what it is waiting to stop
    seeing, so "changed from what we wrote" is an edge rather than a guess.
    The parse is what catches a read taken mid-write, which returns a partial
    or empty file.
    """

    print(f"waiting for {compiled}", file=out)
    for attempt in range(REBUILD_ATTEMPTS):
        if attempt:
            time.sleep(REBUILD_DELAY)
        observed = device.read(compiled)
        if observed is None or observed == VIEW_REBUILD_STUB:
            continue
        try:
            ElementTree.fromstring(observed)
        except ElementTree.ParseError:
            continue
        print(f"rebuilt {compiled}", file=out)
        return
    raise DeviceError(
        f"{compiled} on {device.hostname} was not rebuilt within "
        f"{REBUILD_ATTEMPTS}s of Kodi starting"
    )


def _verify_timezone(
    device: Device, addresses: Addresses, changes: list[Change], out: TextIO
) -> None:
    """The link `tz-data.service` just wrote names the declared zone.

    The unit reads `TIMEZONE` from the document the Run wrote, so the zone
    the Run declared and the link the unit produced are two ends of the same
    fact and comparing them is the whole verification. This is the opposite
    of the view rebuild: one synchronous call with an unambiguous answer.
    """

    for change in changes:
        if (
            not isinstance(change, SettingChange)
            or change.document != addresses.timezone_cache
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


def _restart_transport(
    device: Device, unit: str, document: str, conf: str, out: TextIO
) -> None:
    """Restarts the daemon carrying this connection, and comes back.

    The restart drops the connection that issues it, so its exit status says
    nothing and is not read. What the Run reads is the connection after it:
    the daemon answering again, under the option it was restarted for, is the
    whole verification. `authorized_keys` is checked with it because an empty
    one is the other way a Device becomes unreachable, and after this restart
    there is no password left to fall back on.

    A failure here is fatal and has no revert: a revert would have to travel
    over the connection that just died. A Device that cannot be reached after
    its own `sshd` restarted is evidence of something wrong with the Device,
    the storage media, or the way it was imaged, and that diagnosis is forced
    rather than softened (ADR 0016).
    """

    print(f"restarting {unit}", file=out)
    device.restart_service_expecting_loss(unit)
    for attempt in range(RECONNECT_ATTEMPTS):
        if attempt:
            time.sleep(RECONNECT_DELAY)
        if not device.service_is_active(unit):
            continue
        if device.read(document):
            print(f"{unit} is active and {document} is not empty", file=out)
            return
        raise DeviceError(
            f"{document} on {device.hostname} is empty after {unit} restarted, "
            f"so no key can log in. Use the local console: {conf} now "
            "refuses password authentication"
        )
    raise DeviceError(
        f"{device.hostname} did not answer within "
        f"{int(RECONNECT_ATTEMPTS * RECONNECT_DELAY)}s of {unit} restarting. "
        f"Use the local console to inspect {conf}"
    )


def _install(
    device: Device,
    addresses: Addresses,
    change: AddonChange,
    prepared: dict[str, bytes],
    out: TextIO,
) -> None:
    """Puts the add-on's tree in place and writes its row enabled.

    Kodi is stopped, which is what makes both halves safe: a directory cannot
    be replaced under a running Kodi, and `installed` is written immediately
    on change rather than flushed from memory at exit, so a stopped Kodi has
    nothing to lose (ADR 0018).
    """

    addon = change.addon
    tree = prepared.get(addon.id)
    if tree is not None:
        print(f"shipping {addon.id} {addon.version}", file=out)
        device.replace_directory(change.directory, tree)
    device.sqlite(
        addresses.addon_database,
        ENABLE_ADDON.format(
            id=addon.id,
            installed=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def _prepare(changes: list[Change], out: TextIO) -> dict[str, bytes]:
    """Every Artifact this Run ships, fetched and proven before Kodi stops.

    Downloading under a stopped Kodi would hold the television down for the
    length of the transfer, and an Artifact that fails to fetch or fails its
    pin would do it for nothing. Everything that can fail on the controller
    fails here, before the Run has taken an Effect or written a byte.
    """

    prepared: dict[str, bytes] = {}
    for change in changes:
        if not isinstance(change, AddonChange) or not change.ships:
            continue
        addon = change.addon
        print(f"fetching {addon.id} {addon.version}", file=out)
        prepared[addon.id] = artifact.prepare(
            addon.url, addon.sha256, addon.id, addon.version
        )
    return prepared


def _apply(
    device: Device, desired: DesiredState, changes: list[Change], out: TextIO
) -> None:
    prepared = _prepare(changes, out)
    units = sorted({change.effect for change in changes if change.effect is not None})
    for unit in units:
        print(f"stopping {unit}", file=out)
        device.stop_service(unit)

    applied: list[Change] = []
    armed: list[str] = []
    failure: DeviceError | None = None
    try:
        for change in changes:
            if isinstance(change, AddonChange):
                _install(device, desired.addresses, change, prepared, out)
                applied.append(change)
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
        for compiled in sorted(
            {
                change.rebuild
                for change in changes
                if isinstance(change, SettingChange) and change.rebuild is not None
            }
        ):
            print(f"arming {compiled}", file=out)
            device.write(compiled, VIEW_REBUILD_STUB)
            armed.append(compiled)
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
        for unit in sorted(
            {
                change.restart
                for change in changes
                if isinstance(change, SettingChange) and change.restart is not None
            }
        ):
            _restart_transport(
                device,
                unit,
                desired.authorized_keys.document,
                desired.addresses.sshd_conf,
                out,
            )
        if TZ_DATA_SERVICE in units:
            _verify_timezone(device, desired.addresses, changes, out)
        for compiled in armed:
            _await_rebuild(device, compiled, out)

    if failure is not None:
        raise failure


def bootstrap(desired: DesiredState, *, out: TextIO) -> None:
    """First Contact: reach a Device that has no key yet, and leave one.

    Three steps, in this order and no other: install the administrator key
    over a password session, prove key-only authentication in a *new*
    connection, and only then report success. The install refuses a Device
    that does not answer to the name the Room Overlay gives it before it
    writes anything, which is the same Guard every ordinary Run opens with,
    asked over the only connection there is at that point. The proof is that
    Guard again, over the key.

    Nothing else is done here. Hardening the daemon, declaring who else may
    log in, and everything a Profile says are the ordinary Run's, and this
    entry point is finished the moment the key works.
    """

    device = Device(hostname=desired.hostname, transport=desired.transport)
    keys = desired.authorized_keys
    administrator = keys.entries[0]
    print(
        f"first contact {desired.hostname} (room {desired.room}, "
        f"profile {desired.profile})",
        file=out,
    )
    print(
        f"installing {administrator.comment or 'the administrator key'} "
        f"in {keys.document}; ssh will ask for the Device's root password",
        file=out,
    )
    device.install_administrator_key(
        keys.document, authorized_keys.administrator_entry(administrator)
    )
    print("installed the administrator key", file=out)
    _guard_identity(device, desired.hostname)
    _guard_platform(device, desired.platform)
    print(
        f"{desired.hostname} answers to a key-only connection: "
        "run apply to converge it",
        file=out,
    )


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
