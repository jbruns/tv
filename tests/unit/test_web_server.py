"""The JSON-RPC endpoint Home Assistant reaches the Device through.

Eight `guisettings.xml` addresses configure it. The EventServer is off:
nothing consumes it, since the view rebuild uses the skin's own trigger
(ADR 0015) and Home Assistant speaks JSON-RPC.

These read the committed files, so a declaration and its test cannot drift.
"""

from __future__ import annotations

from typing import Any

from .conftest import shipped_profile

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


def test_the_web_password_is_named_and_never_held() -> None:
    assert declared()["services.webserverpassword"] == {
        "setting": "services.webserverpassword",
        "from_env": "KODI_WEB_PASSWORD",
    }


def test_the_eventserver_is_off() -> None:
    assert declared()["services.esenabled"]["value"] == "false"
    assert declared()["services.esallinterfaces"]["value"] == "false"
