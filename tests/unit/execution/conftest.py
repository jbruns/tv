import fcntl
import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def avoid_physical_disk_flushes() -> Iterator[None]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delattr(fcntl, "F_FULLFSYNC", raising=False)
        monkeypatch.setattr(os, "fsync", lambda _descriptor: None)
        yield
