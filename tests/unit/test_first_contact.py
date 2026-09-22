"""First Contact: who may log in, and closing the password window.

Three Resources and one Effect: `authorized_keys` declared whole, CoreELEC's
own `sshd.conf`, the host key policy each entry point takes, and the
`sshd.service` restart that drops the connection asking for it (ADR 0016).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import (
    ADMINISTRATOR_ENTRY,
    ADMINISTRATOR_KEY,
    LIFECYCLE_ENTRIES,
    LIFECYCLE_ENTRY,
    LIFECYCLE_KEY,
    SSHD_CONF,
    SSHD_DOCUMENT,
    SSHD_HARDENED,
    SSHD_RECONCILED,
    SSHD_WIZARD_ENABLED,
    FakeDevice,
    write_document,
)

NAMES_THE_KEY = "COREELEC_LIFECYCLE_PUBLIC_KEY"
BLOB = LIFECYCLE_KEY.split()[1]


def declare_lifecycle_key(device: FakeDevice) -> None:
    """A Profile declaring the lifecycle entry, with `.env` holding its key."""

    device.write_profile(device.profile_body(entries=LIFECYCLE_ENTRIES))
    device.write_env(f"{NAMES_THE_KEY}='{LIFECYCLE_KEY}'\n")


def test_the_declared_document_is_the_whole_set_of_entries(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """A key nobody declares is removed, which is what revoking one means.

    The shell appends if absent, so its file can only ever grow. Declaring
    the document whole is what makes the Reconciler able to take a key away.
    """

    declare_lifecycle_key(device)
    write_document(
        device.authorized_keys,
        f"{ADMINISTRATOR_ENTRY}\nssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStray somebody\n",
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert device.authorized_keys.read_text(encoding="utf-8") == (
        f"{ADMINISTRATOR_ENTRY}\n{LIFECYCLE_ENTRY}\n"
    )


def test_the_entry_is_only_ever_the_restrict_form(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """`restrict` implies every no-* option, and the Device runs OpenSSH 9.9.

    The forced command is the only program the key may run, and it is the
    one the Profile names.
    """

    declare_lifecycle_key(device)
    assert reconcile("apply", "--room", "theater") == 0

    held = device.authorized_keys.read_text(encoding="utf-8").splitlines()
    assert held[1].startswith('restrict,command="/storage/.config/kodi-lifecycle" ')
    assert "no-agent-forwarding" not in held[1]
    assert held[1].endswith(" homeassistant-ugoos-kodi-lifecycle")


def test_a_change_is_reported_by_entry_and_never_by_key_material(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The report names the entries gained and lost, not sixty-eight bytes
    of base64 nobody reads — and the lifecycle key is named in `.env`."""

    declare_lifecycle_key(device)
    write_document(
        device.authorized_keys,
        f"{ADMINISTRATOR_ENTRY}\nssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStray somebody\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"update {device.authorized_keys}" in out
    assert "observed entries: coreelec-admin@controller, somebody" in out
    assert (
        "desired entries: coreelec-admin@controller, "
        "homeassistant-ugoos-kodi-lifecycle" in out
    )
    assert BLOB not in out


def test_an_entry_is_named_by_its_whole_comment(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A comment is everything after the key blob, and `ssh-keygen -C` will
    happily put spaces in one. Naming an entry by its last word would report
    a key as `laptop` and leave the operator guessing whose."""

    declare_lifecycle_key(device)
    write_document(
        device.authorized_keys,
        f"{ADMINISTRATOR_ENTRY}\n"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStray somebody else's laptop\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    assert (
        "observed entries: coreelec-admin@controller, somebody else's laptop"
        in capsys.readouterr().out
    )


def test_the_administrator_entry_is_derived_and_cannot_be_declared(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Profile that could name an administrator key could name the wrong
    one, so every entry it declares carries a forced command."""

    device.write_profile(
        device.profile_body(
            entries=(
                "\n    - comment: another-administrator"
                f"\n      from_env: {NAMES_THE_KEY}\n"
            )
        )
    )
    device.write_env(f"{NAMES_THE_KEY}='{LIFECYCLE_KEY}'\n")

    assert reconcile("plan", "--room", "theater") == 1
    assert "forced_command" in capsys.readouterr().err


def test_a_missing_administrator_public_key_is_named_before_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without it the Run would declare a document holding no key of its own
    and lock itself out, so it refuses while reading the Profile."""

    public = device.identity.with_name(f"{device.identity.name}.pub")
    public.unlink()

    assert reconcile("plan", "--room", "theater") == 1

    captured = capsys.readouterr()
    assert str(public) in captured.err
    assert "ugoos-theater" not in captured.out


def test_a_named_key_that_is_not_a_public_key_is_refused_naming_neither(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The line goes into a document the Device reads, so a malformed one is
    refused. The error names the `.env` key and never the value."""

    device.write_profile(device.profile_body(entries=LIFECYCLE_ENTRIES))
    device.write_env(f"{NAMES_THE_KEY}='not-a-key AAAA'\n")

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert NAMES_THE_KEY in err
    assert "not-a-key" not in err


def test_one_key_declared_twice_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two entries carrying one key say two things about what it may do."""

    device.write_profile(
        device.profile_body(
            entries=(
                LIFECYCLE_ENTRIES + "    - comment: second-lifecycle"
                f"\n      from_env: {NAMES_THE_KEY}"
                "\n      forced_command: /storage/.config/kodi-lifecycle\n"
            )
        )
    )
    device.write_env(f"{NAMES_THE_KEY}='{LIFECYCLE_KEY}'\n")

    assert reconcile("plan", "--room", "theater") == 1
    assert "declares one key twice" in capsys.readouterr().err


def test_the_wizard_enabled_pair_plans_as_two_changes_and_never_a_create(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Device that kept its password holds CoreELEC's own two keys with the
    insecure values, so hardening is two updates of a document that exists."""

    device.write_profile(device.profile_body(extra=SSHD_DOCUMENT))
    write_document(device.sshd_conf, SSHD_HARDENED)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    # The state a wizard-enabled Device presents, which is also the drift.
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"update {SSHD_CONF}#SSH_ARGS" in out
    assert f"update {SSHD_CONF}#SSHD_DISABLE_PW_AUTH: false -> true" in out
    assert "create " not in out
    assert "plan: 2 changes" in out


def test_hardening_writes_the_option_sshd_is_started_with(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """`service.coreelec.settings` writes exactly this pair from its "Disable
    SSH password" toggle, and the quotes inside `SSH_ARGS` are the point:
    `sshd` starts as `/usr/sbin/sshd -D $SSH_ARGS`, so the option and its
    argument have to survive as two words rather than three."""

    device.write_profile(device.profile_body(extra=SSHD_DOCUMENT))
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("apply", "--room", "theater") == 0

    held = device.sshd_conf.read_text(encoding="utf-8")
    assert held == SSHD_RECONCILED
    assert held.splitlines()[0] == SSHD_HARDENED.splitlines()[0]
    # What CoreELEC gives the file, not the shell's 0600: `oe.py` writes it
    # with a plain `open` and no `chmod`, and the file holds no secret.
    assert oct(device.sshd_conf.stat().st_mode & 0o777) == "0o644"


def test_the_restart_is_taken_after_the_writes_and_verified(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The daemon is restarted, not stopped around the writes: a stop would
    take the connection with it and leave nothing able to start it again.

    The restart's own exit status says nothing, so what the Run reads is the
    connection after it.
    """

    declare_lifecycle_key(device)
    device.write_profile(
        device.profile_body(entries=LIFECYCLE_ENTRIES, extra=SSHD_DOCUMENT)
    )
    write_document(device.sshd_conf, SSHD_HARDENED)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()
    device.systemctl_log.unlink()

    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("apply", "--room", "theater") == 0

    assert device.effects == [
        "restart sshd.service",
        "is-active --quiet sshd.service",
    ]
    out = capsys.readouterr().out
    assert "restarting sshd.service" in out
    assert f"sshd.service is active and {device.authorized_keys} is not empty" in out
    assert "verification: converged" in out


def test_the_restart_is_taken_only_when_the_document_changes(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Device already refusing passwords is not knocked off the network
    once a Run."""

    device.write_profile(device.profile_body(extra=SSHD_DOCUMENT))
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()
    assert "restart sshd.service" in device.effects
    device.systemctl_log.unlink()

    assert reconcile("apply", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out
    assert device.effects == []


def test_a_device_that_does_not_come_back_fails_hard_naming_the_console(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """There is no revert: it would have to travel over the connection that
    just died. A Device unreachable after its own sshd restarted is evidence
    of something wrong with it, and that diagnosis is forced."""

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setenv("FAKE_DEVICE_SYSTEMCTL_REFUSES", "is-active")
    device.write_profile(device.profile_body(extra=SSHD_DOCUMENT))
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "did not answer" in err
    assert f"local console to inspect {SSHD_CONF}" in err
    # The Change itself landed. Fail Forward: the next apply carries on from
    # here rather than undoing it.
    assert device.sshd_conf.read_text(encoding="utf-8") == SSHD_RECONCILED


def test_an_empty_authorized_keys_after_the_restart_is_a_failure(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The daemon answering is half the verification. After this restart
    there is no password left to fall back on, so a document holding no key
    is the other way the Device becomes unreachable."""

    monkeypatch.setenv("FAKE_DEVICE_EMPTIES_ON_RESTART", str(device.authorized_keys))
    device.write_profile(device.profile_body(extra=SSHD_DOCUMENT))
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert f"{device.authorized_keys} on ugoos-theater is empty" in err
    assert "local console" in err


def test_an_ordinary_run_is_strict_about_host_keys(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed host key on an ordinary Run means the Device was reimaged or
    something is wrong, and refusing is the right answer. Trust on first use
    belongs to First Contact alone (SSH-004)."""

    log = device.root / "ssh.log"
    monkeypatch.setenv("FAKE_DEVICE_SSH_LOG", str(log))

    assert reconcile("plan", "--room", "theater") == 0

    invocations = log.read_text(encoding="utf-8").splitlines()
    assert invocations
    for invocation in invocations:
        assert "StrictHostKeyChecking=yes" in invocation
        assert "BatchMode=yes" in invocation
        assert str(device.identity) in invocation


def test_first_contact_installs_the_key_and_proves_it_in_a_new_connection(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The entry point a Device with no key is reached by: one connection
    without public-key authentication, accepting the host key on first use,
    and then a *new* connection that must succeed on the key alone."""

    log = device.root / "ssh.log"
    monkeypatch.setenv("FAKE_DEVICE_SSH_LOG", str(log))
    device.authorized_keys.unlink()

    assert reconcile("bootstrap", "--room", "theater") == 0

    assert device.authorized_keys.read_text(encoding="utf-8") == (
        f"{ADMINISTRATOR_ENTRY}\n"
    )
    # The directory sshd insists on, and the mode it insists on.
    assert oct(device.authorized_keys.parent.stat().st_mode & 0o777) == "0o700"
    assert oct(device.authorized_keys.stat().st_mode & 0o777) == "0o600"

    first, *rest = log.read_text(encoding="utf-8").splitlines()
    assert "PubkeyAuthentication=no" in first
    assert "StrictHostKeyChecking=accept-new" in first
    assert str(device.identity) not in first
    # Everything after it is the ordinary key-only, strict transport.
    assert rest
    for invocation in rest:
        assert "StrictHostKeyChecking=yes" in invocation
        assert str(device.identity) in invocation

    out = capsys.readouterr().out
    assert "installed the administrator key" in out
    assert "ugoos-theater answers to a key-only connection" in out


def test_first_contact_leaves_every_other_entry_alone(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """It appends. The ordinary Run that follows owns every byte of the
    document; this one has no business removing a key while the only thing
    proving it reached the right Device is the password it was just given."""

    write_document(device.authorized_keys, f"{LIFECYCLE_ENTRY}\n")

    assert reconcile("bootstrap", "--room", "theater") == 0

    assert device.authorized_keys.read_text(encoding="utf-8") == (
        f"{LIFECYCLE_ENTRY}\n{ADMINISTRATOR_ENTRY}\n"
    )


def test_first_contact_is_idempotent(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Matching on the key material rather than the comment is what makes a
    second attempt add nothing."""

    assert reconcile("bootstrap", "--room", "theater") == 0
    assert reconcile("bootstrap", "--room", "theater") == 0

    assert device.authorized_keys.read_text(encoding="utf-8") == (
        f"{ADMINISTRATOR_ENTRY}\n"
    )


def test_first_contact_refuses_a_device_that_is_not_the_one_named(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The identity Guard every ordinary Run opens with is the first thing
    First Contact does, over the only connection it has: a Device that is not
    the one named is refused before the key is written, not after."""

    monkeypatch.setenv("FAKE_DEVICE_HOSTNAME", "ugoos-bedroom")
    before = device.authorized_keys.read_text(encoding="utf-8")

    assert reconcile("bootstrap", "--room", "theater") == 1

    captured = capsys.readouterr()
    assert "refusing to install the administrator key" in captured.err
    assert "answers to a key-only connection" not in captured.out
    assert device.authorized_keys.read_text(encoding="utf-8") == before


def test_first_contact_mutates_nothing_beyond_the_key(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Hardening the daemon and everything a Profile says are the ordinary
    Run's. This entry point is finished the moment the key works."""

    declare_lifecycle_key(device)
    device.write_profile(
        device.profile_body(entries=LIFECYCLE_ENTRIES, extra=SSHD_DOCUMENT)
    )
    write_document(device.sshd_conf, SSHD_WIZARD_ENABLED)

    assert reconcile("bootstrap", "--room", "theater") == 0

    assert device.sshd_conf.read_text(encoding="utf-8") == SSHD_WIZARD_ENABLED
    assert device.effects == []
    assert not device.playlist.exists()


def test_the_shipped_profile_declares_the_rows_this_slice_owns(
    tmp_path: Path,
) -> None:
    """What the fleet actually declares, read from the committed Profile so a
    declaration and its test cannot drift."""

    from .conftest import shipped_profile

    profile = shipped_profile()
    keys = profile["authorized_keys"]
    assert keys["document"] == "/storage/.ssh/authorized_keys"
    assert keys["entries"] == [
        {
            "comment": "homeassistant-ugoos-kodi-lifecycle",
            "from_env": NAMES_THE_KEY,
            "forced_command": "/storage/.config/kodi-lifecycle",
        }
    ]

    sshd = [
        document
        for document in profile["settings_documents"]
        if document.get("document") == SSHD_CONF
    ]
    assert sshd == [
        {
            "document": SSHD_CONF,
            "dialect": "shell_vars",
            "mode": "0644",
            "settings": [
                {"setting": "SSH_ARGS", "value": "-o 'PasswordAuthentication no'"},
                {"setting": "SSHD_DISABLE_PW_AUTH", "value": "true"},
            ],
        }
    ]
    # Unused, but the signature keeps this test beside the others that need a
    # temporary tree.
    assert tmp_path.exists()


def test_the_administrator_key_file_is_read_whole_and_must_be_one_line(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two keys in the file is a question about which one goes on the Device,
    and guessing is how the wrong administrator ends up authorized."""

    public = device.identity.with_name(f"{device.identity.name}.pub")
    public.write_text(ADMINISTRATOR_KEY * 2, encoding="utf-8")

    assert reconcile("plan", "--room", "theater") == 1
    assert "exactly one line" in capsys.readouterr().err
