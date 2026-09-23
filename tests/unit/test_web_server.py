"""The JSON-RPC endpoint Home Assistant reaches the Device through.

Eight `guisettings.xml` addresses the shell writes whenever it holds a web
password. Seven agree with the Recovery Baseline. The eighth, the EventServer,
is a Divergent Address: its only consumer was the shell's `kodi-send` view
rebuild, which ADR 0015 retired, so the Profile declares it off.

These read the committed files, so a declaration and its test cannot drift.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .conftest import shipped_profile

REPOSITORY = Path(__file__).resolve().parents[2]
BASELINE = (
    REPOSITORY
    / "config"
    / "shared"
    / "ugoos-am6b-plus"
    / "coreelec-21.3"
    / "provision.conf"
)
GUISETTINGS = "/storage/.kodi/userdata/guisettings.xml"


def declared() -> dict[str, dict[str, Any]]:
    """Every `services.*` setting the shipped guisettings.xml declares."""

    documents = [
        document
        for document in shipped_profile()["settings_documents"]
        if document.get("document") == GUISETTINGS
    ]
    assert len(documents) == 1
    return {
        setting["setting"]: setting
        for setting in documents[0]["settings"]
        if setting["setting"].startswith("services.")
    }


def shell_writes() -> dict[str, str]:
    """What `provision-coreelec.sh` writes for each `services.*` address."""

    shell = (REPOSITORY / "provision-coreelec.sh").read_text(encoding="utf-8")
    return dict(re.findall(r'"(services\.[a-z]+)": (.+?),\n', shell))


def baseline(key: str) -> str:
    held = [
        line.removeprefix(f"{key}=").strip()
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{key}=")
    ]
    assert len(held) == 1
    return held[0]


def test_the_shipped_profile_declares_every_address_the_shell_writes() -> None:
    assert set(declared()) == set(shell_writes())
    assert len(declared()) == 8


def test_the_shipped_web_server_agrees_with_the_recovery_baseline() -> None:
    """Rule 3 of ADR 0012: a shell run after an `apply` changes nothing here."""

    settings = declared()
    shell = shell_writes()
    for literal in (
        "services.esallinterfaces",
        "services.webserver",
        "services.webserverauthentication",
        "services.webserverssl",
    ):
        assert shell[literal] == f'"{settings[literal]["value"]}"'
    assert shell["services.webserverport"] == 'config("KODI_WEB_PORT")'
    assert settings["services.webserverport"]["value"] == baseline("KODI_PORT")
    assert shell["services.webserverusername"] == 'config("KODI_WEB_USER")'
    assert settings["services.webserverusername"]["value"] == baseline("KODI_USER")


def test_the_web_password_is_named_and_never_held() -> None:
    assert declared()["services.webserverpassword"] == {
        "setting": "services.webserverpassword",
        "from_env": "KODI_WEB_PASSWORD",
    }
    assert shell_writes()["services.webserverpassword"] == (
        'secret("KODI_WEB_PASSWORD")'
    )


def test_the_eventserver_is_off_and_says_why_the_shell_disagrees() -> None:
    """The divergence is derived from the shell, not asserted about it. If the
    shell ever stopped writing `true`, the declaration would have to go."""

    eventserver = declared()["services.esenabled"]
    assert eventserver["value"] == "false"
    assert eventserver["divergent"].strip()
    assert shell_writes()["services.esenabled"] == '"true"'
    # Off-Device reach was never possible, so turning it off breaks nothing
    # off the Device.
    assert declared()["services.esallinterfaces"]["value"] == "false"


def test_only_the_eventserver_diverges() -> None:
    """An undeclared disagreement must still fail rule 3."""

    divergent = [setting for setting, held in declared().items() if "divergent" in held]
    assert divergent == ["services.esenabled"]
