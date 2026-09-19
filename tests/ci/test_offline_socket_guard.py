import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import offline_socket_guard

SUPPORT_DIRECTORY = Path(__file__).parents[1] / "support"


def test_guard_rejects_direct_socket_creation() -> None:
    offline_socket_guard.install()

    with pytest.raises(
        offline_socket_guard.UnexpectedSocketError,
        match="unexpected socket use",
    ):
        socket.socket()


def test_guard_rejects_convenience_connection_helpers() -> None:
    offline_socket_guard.install()

    with pytest.raises(
        offline_socket_guard.UnexpectedSocketError,
        match="unexpected socket use",
    ):
        socket.create_connection(("example.invalid", 443))


def test_guard_is_inherited_by_python_subprocesses() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            [
                str(SUPPORT_DIRECTORY),
                str(Path(__file__).parents[2]),
                environment.get("PYTHONPATH"),
            ],
        )
    )

    result = subprocess.run(
        [sys.executable, "-c", "import socket; socket.socket()"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "UnexpectedSocketError: unexpected socket use" in result.stderr
