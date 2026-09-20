import fcntl
import os

import pytest


@pytest.fixture(autouse=True)
def avoid_physical_disk_flushes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(fcntl, "F_FULLFSYNC", raising=False)
    monkeypatch.setattr(os, "fsync", lambda _descriptor: None)
