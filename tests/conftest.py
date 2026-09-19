import os
from pathlib import Path

from tests.support.offline_socket_guard import install

SUPPORT_DIRECTORY = Path(__file__).parent / "support"
REPOSITORY_ROOT = Path(__file__).parent.parent
existing_pythonpath = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = os.pathsep.join(
    filter(
        None,
        [str(SUPPORT_DIRECTORY), str(REPOSITORY_ROOT), existing_pythonpath],
    )
)
install()
