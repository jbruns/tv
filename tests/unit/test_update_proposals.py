"""Proposing Stable Releases, and triaging the Artifact Patches they touch.

`propose-updates` reads every Artifact Lock, asks each record's own Release
Channel for a newer Stable Release, and writes one Update Proposal per add-on:
the rewritten Lock, the patch changes, and a body a reviewer reads. It talks
to no GitHub and no Device (ADR 0022).

These tests drive the Reconciler only through its public entry point
(ADR 0011). The channels are local fixtures served by the stub `curl`, and
the patches are tried by the real `patch`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from .conftest import ADDON_ID, ADDON_VERSION, FakeDevice, addon_lock

KODI = "https://mirrors.kodi.tv/addons/omega"
JURIALMUNKEY = (
    "https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/"
    "master/omega/zips"
)
CHANNELS = (
    "channels:\n"
    "  kodi-omega:\n"
    f"    addons_xml: {KODI}/addons.xml.gz\n"
    "  jurialmunkey-omega:\n"
    f"    addons_xml: {JURIALMUNKEY}/addons.xml\n"
)
PROFILE = "ugoos-am6b-plus/coreelec-21.3"
NEWER = "1.17.0"

UNPATCHED = "SIX = True\n"
PATCHED = "SIX = True\nPATCHED = True\n"
PATCH_NAME = "0001-say-so.patch"
PATCH = f"""\
# {ADDON_ID} {ADDON_VERSION}
#
# Upstream forgot to say so.
--- a/lib/six.py
+++ b/lib/six.py
@@ -1 +1,2 @@
 SIX = True
+PATCHED = True
"""


def manifest(
    addon_id: str,
    version: str,
    requires: Sequence[tuple[str, str]] = (),
    news: str | None = None,
) -> str:
    """An `addon.xml`, as a published Artifact and its index entry state it."""

    imports = "".join(
        f'    <import addon="{name}" version="{floor}"/>\n' for name, floor in requires
    )
    metadata = "" if news is None else f"    <news>{news}</news>\n"
    return (
        f'<addon id="{addon_id}" name="{addon_id}" version="{version}" '
        'provider-name="kodi">\n'
        f"  <requires>\n{imports}  </requires>\n"
        '  <extension point="xbmc.python.module" library="lib"/>\n'
        f'  <extension point="xbmc.addon.metadata">\n{metadata}  </extension>\n'
        "</addon>\n"
    )


def publish_index(device: FakeDevice, url: str, entries: Sequence[str]) -> None:
    """Serves a Kodi repository's `addons.xml` at `url`, gzipped if it says so."""

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<addons>\n'
        + "".join(entries)
        + "</addons>\n"
    ).encode("utf-8")
    target = device.artifacts / url.removeprefix("https://")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(body) if url.endswith(".gz") else body)


def publish_release(
    device: FakeDevice,
    version: str,
    six: str = UNPATCHED,
    addon_id: str = ADDON_ID,
    requires: Sequence[tuple[str, str]] = (),
    news: str | None = None,
    datadir: str = KODI,
) -> str:
    """Publishes a version's Artifact where its channel's convention puts it."""

    return device.publish_artifact(
        addon_id=addon_id,
        version=version,
        manifest=manifest(addon_id, version, requires, news),
        extra={"lib/six.py": six},
        url=f"{datadir}/{addon_id}/{addon_id}-{version}.zip",
    )


def pin(
    device: FakeDevice, patches: bool = False, extra: str = "", notes: str = "~"
) -> str:
    """Pins the add-on at its current version, as the Lock holds it today."""

    digest = device.publish_artifact()
    if patches:
        device.write_patch(PATCH_NAME, PATCH)
    device.write_addons(
        addon_lock(
            digest=digest,
            channels=CHANNELS,
            notes=notes,
            patches=(PATCH_NAME,) if patches else (),
            patched_files=(
                {"lib/six.py": hashlib.sha256(PATCHED.encode()).hexdigest()}
                if patches
                else None
            ),
        )
        + extra
    )
    return digest


def record(
    addon_id: str, version: str, url: str, digest: str, channel: str = "kodi-omega"
) -> str:
    """One more record for the Lock `pin` writes."""

    return (
        f"  - id: {addon_id}\n"
        f'    version: "{version}"\n'
        f"    url: {url}\n"
        f'    sha256: "{digest}"\n'
        "    role: dependency\n"
        f"    channel: {channel}\n"
        "    notes: ~\n"
    )


@pytest.fixture
def propose(device: FakeDevice, tmp_path: Path) -> Callable[..., tuple[int, Path]]:
    """Runs `propose-updates` and returns its exit code and output directory."""

    from coreelec_reconciler import main

    out = tmp_path / "proposals"

    def run(*argv: str) -> tuple[int, Path]:
        code = main(
            [
                "propose-updates",
                "--out",
                str(out),
                "--config-root",
                str(device.config_root),
                *argv,
            ]
        )
        return code, out

    return run


def proposal(out: Path, addon_id: str = ADDON_ID) -> Path:
    return out / PROFILE / addon_id


def metadata(out: Path, addon_id: str = ADDON_ID) -> dict[str, object]:
    held = json.loads((proposal(out, addon_id) / "proposal.json").read_text())
    assert isinstance(held, dict)
    return held


def body(out: Path, addon_id: str = ADDON_ID) -> str:
    return (proposal(out, addon_id) / "body.md").read_text(encoding="utf-8")


def proposed_lock(out: Path, addon_id: str = ADDON_ID) -> str:
    return (
        proposal(out, addon_id) / "files" / "shared" / PROFILE / "addons.yaml"
    ).read_text(encoding="utf-8")


def proposed_file(out: Path, path: str, addon_id: str = ADDON_ID) -> Path:
    return proposal(out, addon_id) / "files" / "shared" / PROFILE / path


def deleted(out: Path, addon_id: str = ADDON_ID) -> list[str]:
    return (proposal(out, addon_id) / "deleted").read_text().split()


def test_a_newer_stable_release_is_proposed(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    pin(device)
    digest = publish_release(device, NEWER, news="Fixes the thing.")
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, ADDON_VERSION), manifest(ADDON_ID, NEWER)],
    )
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    lock = proposed_lock(out)
    assert f'version: "{NEWER}"' in lock
    assert f"url: {KODI}/{ADDON_ID}/{ADDON_ID}-{NEWER}.zip" in lock
    assert f'sha256: "{digest}"' in lock
    assert metadata(out) == {
        "branch": f"update/{PROFILE}/{ADDON_ID}",
        "title": f"Update {ADDON_ID} to {NEWER} in {PROFILE}",
        "draft": False,
        "key": f"{PROFILE}/{ADDON_ID}@{NEWER}",
    }
    text = body(out)
    assert f"{ADDON_VERSION} | {NEWER}" in text
    assert "Fixes the thing." in text
    assert "- [ ] A Device running this Profile was reconciled from this branch" in text
    assert deleted(out) == []
    # Nothing was contacted: a proposal is files, and the workflow opens it.
    assert device.effects == []


def test_versions_are_ordered_the_way_kodi_orders_them(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """`1.9.9` is below `1.16.0`, and `+matrix.2` is above `+matrix.1`.

    The rules are Kodi's own `CAddonVersion`: numeric runs compare as
    numbers, and a longer version is greater unless it continues with `~`.
    """

    pin(device)
    publish_release(device, "1.16.0+matrix.2")
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [
            manifest(ADDON_ID, "1.9.9"),
            manifest(ADDON_ID, "1.16.0+matrix.2"),
            manifest(ADDON_ID, "1.16.0"),
        ],
    )
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    assert 'version: "1.16.0+matrix.2"' in proposed_lock(out)


@pytest.mark.parametrize("prerelease", ["1.17.0~beta1", "1.17.0-rc1", "2.0.0alpha"])
def test_a_prerelease_is_not_proposed(
    device: FakeDevice,
    propose: Callable[..., tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
    prerelease: str,
) -> None:
    pin(device)
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, ADDON_VERSION), manifest(ADDON_ID, prerelease)],
    )
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    assert not proposal(out).exists()
    assert "no Update Proposals" in capsys.readouterr().out


def test_a_carried_patch_is_rewritten_and_recorded(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    pin(device, patches=True)
    publish_release(device, NEWER, six="NEW = True\nSIX = True\n")
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    patch = proposed_file(out, f"patches/{ADDON_ID}/{PATCH_NAME}")
    assert patch.read_text(encoding="utf-8") == PATCH.replace(
        f"# {ADDON_ID} {ADDON_VERSION}", f"# {ADDON_ID} {NEWER}"
    )
    produced = "NEW = True\nSIX = True\nPATCHED = True\n"
    recorded = hashlib.sha256(produced.encode()).hexdigest()
    assert f'lib/six.py: "{recorded}"' in proposed_lock(out)
    text = body(out)
    assert f"`{PATCH_NAME}`: Carried" in text
    # The upstream diff of the file the patch touches, unpatched to unpatched.
    assert "+NEW = True" in text
    assert metadata(out)["draft"] is False


def test_a_note_with_a_paragraph_break_stays_in_its_record(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    pin(device, patches=True, notes=">-\n      First paragraph.\n\n      Second one.")
    publish_release(device, NEWER, six="NEW = True\nSIX = True\n")
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    lock = proposed_lock(out)
    assert "      First paragraph.\n\n      Second one.\n    patches:\n" in lock
    assert lock.count("patched_files:") == 1


def test_an_obsolete_patch_is_removed(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """Upstream now holds the corrected text, so the patch reverse-applies."""

    pin(device, patches=True)
    publish_release(device, NEWER, six=PATCHED)
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    assert deleted(out) == [f"shared/{PROFILE}/patches/{ADDON_ID}/{PATCH_NAME}"]
    lock = proposed_lock(out)
    assert "patches:" not in lock
    assert "patched_files:" not in lock
    assert f"`{PATCH_NAME}`: Obsolete" in body(out)
    assert metadata(out)["draft"] is False


def test_a_stale_patch_makes_the_proposal_a_draft(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    pin(device, patches=True)
    publish_release(device, NEWER, six="SIX = False\n")
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    assert metadata(out)["draft"] is True
    text = body(out)
    assert f"`{PATCH_NAME}`: Stale" in text
    # The reject hunk a human rewrites the patch from.
    assert "+PATCHED = True" in text
    assert "-SIX = True" in text and "+SIX = False" in text
    # The patch is left as written, asserting the version it was written for.
    assert not proposed_file(out, f"patches/{ADDON_ID}/{PATCH_NAME}").exists()
    assert deleted(out) == []
    assert f'version: "{NEWER}"' in proposed_lock(out)


def test_a_new_requirement_one_channel_satisfies_is_added(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    pin(device)
    publish_release(device, NEWER, requires=[("script.module.new", "1.0.0")])
    digest = publish_release(device, "1.0.1", addon_id="script.module.new")
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, NEWER), manifest("script.module.new", "1.0.1")],
    )
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    lock = proposed_lock(out)
    assert (
        "  - id: script.module.new\n"
        '    version: "1.0.1"\n'
        f"    url: {KODI}/script.module.new/script.module.new-1.0.1.zip\n"
        f'    sha256: "{digest}"\n'
        "    role: dependency\n"
        "    channel: kodi-omega\n"
        "    notes: ~\n"
    ) in lock
    assert metadata(out)["draft"] is False
    assert "script.module.new" in body(out)


def test_a_new_requirement_two_channels_offer_makes_a_draft(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """Which publisher a new dependency should come from is a human's call."""

    pin(device)
    publish_release(device, NEWER, requires=[("script.module.new", "1.0.0")])
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, NEWER), manifest("script.module.new", "1.0.1")],
    )
    publish_index(
        device, f"{JURIALMUNKEY}/addons.xml", [manifest("script.module.new", "1.2.0")]
    )

    code, out = propose()

    assert code == 0
    assert metadata(out)["draft"] is True
    assert "script.module.new" not in proposed_lock(out)
    text = body(out)
    assert "script.module.new" in text
    assert "kodi-omega" in text and "jurialmunkey-omega" in text


def test_a_new_requirement_is_not_settled_while_a_channel_is_unreachable(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """The channel that did not answer might have offered it too."""

    pin(device)
    publish_release(device, NEWER, requires=[("script.module.new", "1.0.0")])
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, NEWER), manifest("script.module.new", "1.0.1")],
    )

    code, out = propose()

    assert code == 1
    assert metadata(out)["draft"] is True
    assert "script.module.new" not in proposed_lock(out)
    assert "jurialmunkey-omega" in body(out)


def test_a_dependency_bump_a_floor_forces_rides_in_that_proposal(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """A dependency the proposal moves gets no proposal of its own."""

    old = publish_release(device, "1.0.0", addon_id="script.module.dep")
    pin(
        device,
        extra=record(
            "script.module.dep",
            "1.0.0",
            f"{KODI}/script.module.dep/script.module.dep-1.0.0.zip",
            old,
        ),
    )
    publish_release(device, NEWER, requires=[("script.module.dep", "1.1.0")])
    digest = publish_release(device, "1.1.0", addon_id="script.module.dep")
    publish_index(
        device,
        f"{KODI}/addons.xml.gz",
        [manifest(ADDON_ID, NEWER), manifest("script.module.dep", "1.1.0")],
    )
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    lock = proposed_lock(out)
    assert f'version: "{NEWER}"' in lock
    assert f'sha256: "{digest}"' in lock
    assert not proposal(out, "script.module.dep").exists()
    assert "script.module.dep" in body(out)


def test_an_unreachable_channel_is_skipped_and_fails_the_run(
    device: FakeDevice,
    propose: Callable[..., tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = publish_release(
        device, "0.0.1", addon_id="script.module.other", datadir=JURIALMUNKEY
    )
    pin(
        device,
        extra=record(
            "script.module.other",
            "0.0.1",
            f"{JURIALMUNKEY}/script.module.other/script.module.other-0.0.1.zip",
            other,
            channel="jurialmunkey-omega",
        ),
    )
    publish_release(device, NEWER)
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])

    code, out = propose()

    assert code == 1
    assert f'version: "{NEWER}"' in proposed_lock(out)
    assert f"{JURIALMUNKEY}/addons.xml" in capsys.readouterr().err


def test_a_declined_version_is_not_proposed_again(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """Closing a proposal unmerged is the record that stops it (ADR 0022)."""

    pin(device)
    publish_release(device, NEWER)
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose("--declined", f"{PROFILE}/{ADDON_ID}@{NEWER}")

    assert code == 0
    assert not proposal(out).exists()


def test_a_github_channel_proposes_the_tag_archive(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """`weather.ha`'s only Release Channel is its publisher's tags."""

    channels = "channels:\n  weather-ha:\n    github_tags: owner/weather\n"
    tags = "https://api.github.com/repos/owner/weather/tags"
    tagged = "https://codeload.github.com/owner/weather/zip/refs/tags"
    old = device.publish_artifact(root="weather-1.0.0", url=f"{tagged}/1.0.0")
    device.write_addons(
        addon_lock(
            digest=old,
            url=f"{tagged}/1.0.0",
            version="1.0.0",
            channel="weather-ha",
            channels=channels,
        )
    )
    digest = device.publish_artifact(
        root="weather-1.1.0", version="1.1.0", url=f"{tagged}/1.1.0"
    )
    target = device.artifacts / tags.removeprefix("https://")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([{"name": "1.1.0"}, {"name": "1.1.1-beta"}, {"name": "1.0.0"}])
    )

    code, out = propose()

    assert code == 0
    lock = proposed_lock(out)
    assert f"url: {tagged}/1.1.0" in lock
    assert f'sha256: "{digest}"' in lock


def test_the_proposed_lock_is_one_the_reconciler_reads(
    device: FakeDevice,
    propose: Callable[..., tuple[int, Path]],
    reconcile: Callable[..., int],
) -> None:
    """A proposal is accepted by reconciling a Device from its branch."""

    pin(device, patches=True)
    publish_release(device, NEWER, six="NEW = True\nSIX = True\n")
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])
    _, out = propose()
    for source in (proposal(out) / "files").rglob("*"):
        if source.is_file():
            relative = source.relative_to(proposal(out) / "files")
            (device.config_root / relative).write_bytes(source.read_bytes())
    device.create_addon_database()

    assert reconcile("apply", "--room", "theater") == 0

    installed = device.addons / ADDON_ID / "lib" / "six.py"
    assert installed.read_text() == "NEW = True\nSIX = True\nPATCHED = True\n"


def test_a_repository_moving_a_channel_says_so(
    device: FakeDevice, propose: Callable[..., tuple[int, Path]]
) -> None:
    """The Action never edits the `channels:` map; a human does (ADR 0022)."""

    def repository(version: str, directory: str) -> str:
        return (
            f'<addon id="{ADDON_ID}" name="r" version="{version}" provider-name="r">\n'
            '  <extension point="xbmc.addon.repository">\n'
            f"    <dir><info>{directory}/addons.xml</info></dir>\n"
            "  </extension>\n"
            "</addon>\n"
        )

    digest = device.publish_artifact(manifest=repository(ADDON_VERSION, JURIALMUNKEY))
    device.write_addons(addon_lock(digest=digest, role="repository", channels=CHANNELS))
    device.publish_artifact(
        version=NEWER,
        manifest=repository(NEWER, "https://example.invalid/moved"),
        url=f"{KODI}/{ADDON_ID}/{ADDON_ID}-{NEWER}.zip",
    )
    publish_index(device, f"{KODI}/addons.xml.gz", [manifest(ADDON_ID, NEWER)])
    publish_index(device, f"{JURIALMUNKEY}/addons.xml", [])

    code, out = propose()

    assert code == 0
    text = body(out)
    assert f"no longer publishes {JURIALMUNKEY}/addons.xml" in text
    assert "Release Channels the Lock names that moved: jurialmunkey-omega." in text
    assert "channels:" not in proposed_lock(out).split("addons:")[1]
