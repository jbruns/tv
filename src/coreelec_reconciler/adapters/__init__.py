"""Production SSH/SFTP adapters; intentionally not wired into bootstrap."""

from .paramiko_managed_file import ParamikoManagedFiles
from .paramiko_session import (
    CommandFailureCode,
    CommandOutcome,
    ParamikoDeviceSession,
    ParamikoSessionFactory,
    SessionError,
    SessionFailureCode,
)
from .remote_run_ownership import ParamikoRemoteAuthorityBackend
from .secrets import (
    EnvironmentSecretResolver,
    MappingHostKeyResolver,
    PinnedHostKey,
    SecretResolutionError,
)

__all__ = [
    "CommandFailureCode",
    "CommandOutcome",
    "EnvironmentSecretResolver",
    "MappingHostKeyResolver",
    "ParamikoDeviceSession",
    "ParamikoManagedFiles",
    "ParamikoRemoteAuthorityBackend",
    "ParamikoSessionFactory",
    "PinnedHostKey",
    "SecretResolutionError",
    "SessionError",
    "SessionFailureCode",
]
