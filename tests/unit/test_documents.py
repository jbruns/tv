"""A document the Profile ships as a file, and the Device holds byte for byte.

The Kodi lifecycle gateway is forty lines of POSIX `sh`. Embedded in
`profile.yaml` it could be neither linted nor read as shell, so the Profile
names a file beside itself instead, and a Run renders that file whole.

A missing source is a configuration mistake, named before any Device contact
rather than halfway through a Run.

These tests drive the Reconciler through its public entry point only
(ADR 0011).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import FakeDevice, shipped_profile, write_document

REPOSITORY = Path(__file__).resolve().parents[2]
PROFILE_DIRECTORY = (
    REPOSITORY / "config" / "shared" / "ugoos-am6b-plus" / "coreelec-21.3"
)
GATEWAY = "/storage/.config/kodi-lifecycle"
FORCED_COMMAND_OWNER = "homeassistant-ugoos-kodi-lifecycle"

SOURCE = "documents/kodi-lifecycle"
BODY = """\
#!/bin/sh
set -eu
printf 'stopped\\n'
"""


def gateway(device: FakeDevice) -> Path:
    return device.root / "storage" / ".config" / "kodi-lifecycle"


def declaring(device: FakeDevice, *entries: str) -> str:
    """The Profile, declaring `entries` as its whole-file documents."""

    return device.profile_body(documents="\n" + "".join(entries))


def entry(path: Path | str, source: str = SOURCE, mode: str = "0700") -> str:
    return f'  - document: {path}\n    source: {source}\n    mode: "{mode}"\n'


def test_a_document_reaches_the_device_as_its_source_with_its_mode(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_source(SOURCE, BODY)
    device.write_profile(declaring(device, entry(gateway(device))))

    assert reconcile("apply", "--room", "theater") == 0

    assert gateway(device).read_bytes() == BODY.encode("utf-8")
    assert gateway(device).stat().st_mode & 0o777 == 0o700
    out = capsys.readouterr().out
    assert f"create {gateway(device)}" in out
    assert "verification: converged" in out

    assert reconcile("plan", "--room", "theater") == 0

    assert "plan: no changes" in capsys.readouterr().out


def test_a_document_nothing_reads_takes_no_effect(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Kodi does not read the gateway, so writing it does not stop Kodi."""

    assert reconcile("apply", "--room", "theater") == 0
    device.systemctl_log.unlink()
    device.write_source(SOURCE, BODY)
    device.write_profile(declaring(device, entry(gateway(device))))

    assert reconcile("apply", "--room", "theater") == 0

    assert gateway(device).exists()
    assert device.effects == []


def test_a_document_that_drifted_is_rewritten_whole(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_source(SOURCE, BODY)
    device.write_profile(declaring(device, entry(gateway(device))))
    write_document(gateway(device), BODY.replace("stopped", "running"))

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"update {gateway(device)}" in out
    assert "-printf 'running\\n'" in out
    assert "+printf 'stopped\\n'" in out

    assert reconcile("apply", "--room", "theater") == 0

    assert gateway(device).read_text(encoding="utf-8") == BODY


def test_a_missing_source_is_named_before_the_device_is_contacted(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = device.root / "ssh.log"
    monkeypatch.setenv("FAKE_DEVICE_SSH_LOG", str(log))
    device.write_profile(declaring(device, entry(gateway(device))))

    assert reconcile("apply", "--room", "theater") == 1

    assert SOURCE in capsys.readouterr().err
    assert not log.exists()
    assert not gateway(device).exists()


@pytest.mark.parametrize("source", ["../kodi-lifecycle", "/etc/passwd"])
def test_a_source_outside_the_profile_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    source: str,
) -> None:
    """A Profile is copyable as a unit only if nothing it names is elsewhere."""

    device.write_profile(declaring(device, entry(gateway(device), source=source)))

    assert reconcile("plan", "--room", "theater") == 1

    assert source in capsys.readouterr().err


def test_a_document_states_its_source(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        declaring(device, f'  - document: {gateway(device)}\n    mode: "0700"\n')
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "source" in capsys.readouterr().err


def test_a_document_path_must_be_absolute(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_source(SOURCE, BODY)
    device.write_profile(declaring(device, entry("storage/kodi-lifecycle")))

    assert reconcile("plan", "--room", "theater") == 1

    assert "absolute" in capsys.readouterr().err


def test_a_document_declared_twice_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two sources for one path is a question about which bytes the Device holds."""

    device.write_source(SOURCE, BODY)
    device.write_profile(
        declaring(device, entry(gateway(device)), entry(gateway(device)))
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "twice" in capsys.readouterr().err


def shipped_gateway() -> dict[str, str]:
    declared = [
        document
        for document in shipped_profile()["documents"]
        if document["document"] == GATEWAY
    ]
    assert len(declared) == 1
    held: dict[str, str] = declared[0]
    return held


def test_the_shipped_gateway_is_the_forced_command_of_home_assistants_key() -> None:
    """The key line is the Reconciler's, and it names this path."""

    entries = shipped_profile()["authorized_keys"]["entries"]
    forced = [
        held["forced_command"]
        for held in entries
        if held["comment"] == FORCED_COMMAND_OWNER
    ]
    assert forced == [GATEWAY]
    assert shipped_gateway() == {
        "document": GATEWAY,
        "source": SOURCE,
        "mode": "0700",
    }


def test_the_shipped_gateway_is_what_the_recovery_baseline_renders() -> None:
    """Rule 3 of ADR 0012: a shell run after an `apply` changes nothing here.

    The renderer is the shell's own, invoked the way its deploy invokes it,
    so the parity is derived rather than asserted.
    """

    rendered = subprocess.run(
        [
            "bash",
            "-c",
            "source lib/coreelec-lifecycle.sh && "
            "coreelec_lifecycle_render_wrapper /usr/bin/systemctl",
        ],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    shipped = (PROFILE_DIRECTORY / shipped_gateway()["source"]).read_text(
        encoding="utf-8"
    )
    assert shipped == rendered
