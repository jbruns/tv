"""Fixed server-side compare-and-swap managed-file mutations."""

import base64
import zlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.domain.canonical_json import canonical_document_bytes
from coreelec_reconciler.domain.execution import NormalizedResourceState, Presence


class ManagedMutationCode(StrEnum):
    APPLIED = "applied"
    PRECONDITION_CHANGED = "precondition_changed"
    UNSAFE = "unsafe"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ManagedMutationResult:
    code: ManagedMutationCode


class CommandRunner(Protocol):
    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> object: ...


class ManagedMutationHelper(Protocol):
    def supported(self) -> bool: ...

    def mutate(
        self,
        operation: str,
        path: str,
        operation_id: str,
        binding_digest: str,
        expected: NormalizedResourceState,
        *,
        content: bytes | None = None,
        mode: int | None = None,
        staged_path: str | None = None,
        expected_staged: NormalizedResourceState | None = None,
    ) -> ManagedMutationResult: ...


_HELPER = b"""import base64, ctypes, errno, hashlib, json, os, stat, sys
APPLIED = 0
INVALID = 64
UNSAFE = 65
PRECONDITION = 66
UNSUPPORTED = 67
AMBIGUOUS = 68
MAX_FILE_SIZE = 16 * 1024 * 1024
descriptors = []
mutated = False

def fail(code):
    raise SystemExit(code)

def text(value, maximum=4096):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or chr(0) in value
    ):
        fail(INVALID)
    return value

def digest(value):
    value = text(value, 71)
    if len(value) != 71 or not value.startswith("sha256:") or any(
        character not in "0123456789abcdef" for character in value[7:]
    ):
        fail(INVALID)
    return value

def mode_value(value):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > 0o7777
    ):
        fail(INVALID)
    return value

def expected_value(value):
    if not isinstance(value, dict) or set(value) != {
        "content_digest", "entry_kind", "managed_mode", "presence"
    }:
        fail(INVALID)
    presence = value["presence"]
    if presence == "absent":
        if any(value[key] is not None for key in (
            "content_digest", "entry_kind", "managed_mode"
        )):
            fail(INVALID)
    elif presence == "present":
        if value["entry_kind"] != "regular":
            fail(INVALID)
        digest(value["content_digest"])
        mode_value(value["managed_mode"])
    else:
        fail(INVALID)
    return value

def bound_stage(path, binding):
    token = binding[7:]
    name = path.rsplit("/", 1)[-1]
    return (
        name.endswith("." + token + ".stage")
        or ("/runs/" + token + "/stage/") in path
    )

def parent(path):
    path = text(path)
    if not path.startswith("/"):
        fail(INVALID)
    components = path.split("/")[1:]
    if not components or any(component in ("", ".", "..") for component in components):
        fail(INVALID)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    descriptors.append(descriptor)
    for component in components[:-1]:
        descriptor = os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=descriptor,
        )
        descriptors.append(descriptor)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            fail(UNSAFE)
    return descriptor, components[-1]

def absent(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False

def opened(directory, name, expected):
    if expected["presence"] == "absent":
        return None if absent(directory, name) else False
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return False
    descriptors.append(descriptor)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != expected["managed_mode"]
        or metadata.st_size > MAX_FILE_SIZE
    ):
        return False
    value = hashlib.sha256()
    remaining = metadata.st_size
    while remaining:
        chunk = os.read(descriptor, min(65536, remaining))
        if not chunk:
            return False
        value.update(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        return False
    if "sha256:" + value.hexdigest() != expected["content_digest"]:
        return False
    return descriptor

def still_named(descriptor, directory, name):
    try:
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    pinned = os.fstat(descriptor)
    return (
        stat.S_ISREG(named.st_mode)
        and named.st_dev == pinned.st_dev
        and named.st_ino == pinned.st_ino
    )

def write_all(descriptor, payload):
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            fail(AMBIGUOUS)
        view = view[written:]

def create(directory, name, payload, desired_mode):
    global mutated
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        desired_mode,
        dir_fd=directory,
    )
    descriptors.append(descriptor)
    mutated = True
    write_all(descriptor, payload)
    os.fchmod(descriptor, desired_mode)
    os.fsync(descriptor)
    return descriptor

def renameat2(directory, source, destination, flags):
    global mutated
    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if function is None:
        fail(UNSUPPORTED)
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(
        directory,
        source.encode(),
        directory,
        destination.encode(),
        flags,
    ) != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOENT):
            fail(PRECONDITION)
        if error in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            fail(UNSUPPORTED)
        fail(AMBIGUOUS)
    mutated = True

def rename_no_replace(directory, source, destination):
    renameat2(directory, source, destination, 1)

def exchange(directory, first, second):
    renameat2(directory, first, second, 2)

def replace(
    directory,
    source,
    source_descriptor,
    source_expected,
    destination,
    destination_value,
    destination_expected,
):
    if not still_named(source_descriptor, directory, source):
        fail(PRECONDITION)
    if destination_value is None:
        rename_no_replace(directory, source, destination)
        return True
    if not still_named(destination_value, directory, destination):
        fail(PRECONDITION)
    exchange(directory, source, destination)
    captured = opened(directory, source, destination_expected)
    installed = opened(directory, destination, source_expected)
    valid = (
        isinstance(captured, int)
        and isinstance(installed, int)
        and os.fstat(captured).st_ino == os.fstat(destination_value).st_ino
        and os.fstat(captured).st_dev == os.fstat(destination_value).st_dev
        and os.fstat(installed).st_ino == os.fstat(source_descriptor).st_ino
        and os.fstat(installed).st_dev == os.fstat(source_descriptor).st_dev
    )
    if not valid:
        if (
            isinstance(captured, int)
            and isinstance(installed, int)
            and still_named(captured, directory, source)
            and still_named(installed, directory, destination)
        ):
            exchange(directory, source, destination)
            return False
        fail(AMBIGUOUS)
    if not still_named(captured, directory, source):
        fail(AMBIGUOUS)
    os.unlink(source, dir_fd=directory)
    return True

def remove_expected(directory, name, expected, binding, operation_id):
    descriptor = opened(directory, name, expected)
    if descriptor is None:
        return
    if not isinstance(descriptor, int) or not still_named(descriptor, directory, name):
        fail(PRECONDITION)
    suffix = hashlib.sha256((binding + operation_id).encode()).hexdigest()[:32]
    tombstone = "." + name + "." + suffix + ".remove"
    if not absent(directory, tombstone):
        fail(PRECONDITION)
    rename_no_replace(directory, name, tombstone)
    captured = opened(directory, tombstone, expected)
    if (
        not isinstance(captured, int)
        or os.fstat(captured).st_ino != os.fstat(descriptor).st_ino
        or os.fstat(captured).st_dev != os.fstat(descriptor).st_dev
    ):
        if absent(directory, name) and isinstance(captured, int):
            rename_no_replace(directory, tombstone, name)
            fail(PRECONDITION)
        fail(AMBIGUOUS)
    if not still_named(captured, directory, tombstone):
        fail(AMBIGUOUS)
    os.unlink(tombstone, dir_fd=directory)
    os.fsync(directory)

try:
    request = json.loads(sys.stdin.buffer.read())
    if not isinstance(request, dict) or set(request) != {
        "binding_digest", "content", "expected", "expected_staged", "mode",
        "operation", "operation_id", "path", "staged_path"
    }:
        fail(INVALID)
    operation = text(request["operation"], 32)
    if operation == "probe":
        renameat2_available = getattr(
            ctypes.CDLL(None, use_errno=True), "renameat2", None
        ) is not None
        supported = (
            renameat2_available
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
            and os.unlink in os.supports_dir_fd
        )
        fail(APPLIED if supported else UNSUPPORTED)
    if operation not in ("stage", "chmod", "remove", "replace", "restore", "cleanup"):
        fail(INVALID)
    binding = digest(request["binding_digest"])
    text(request["operation_id"], 512)
    expected = expected_value(request["expected"])
    directory, name = parent(request["path"])

    if operation == "stage":
        if not bound_stage(request["path"], binding):
            fail(INVALID)
        payload = base64.b64decode(
            text(request["content"], MAX_FILE_SIZE * 2),
            validate=True,
        )
        desired_mode = mode_value(request["mode"])
        if expected["presence"] != "absent":
            fail(PRECONDITION)
        if not absent(directory, name):
            staged_expected = {
                "content_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "entry_kind": "regular",
                "managed_mode": desired_mode,
                "presence": "present",
            }
            if isinstance(opened(directory, name, staged_expected), int):
                fail(APPLIED)
            fail(PRECONDITION)
        create(directory, name, payload, desired_mode)
    elif operation == "chmod":
        descriptor = opened(directory, name, expected)
        if not isinstance(descriptor, int):
            fail(PRECONDITION)
        os.fchmod(descriptor, mode_value(request["mode"]))
        mutated = True
        os.fsync(descriptor)
    elif operation in ("remove", "cleanup"):
        remove_expected(
            directory,
            name,
            expected,
            binding,
            request["operation_id"],
        )
    elif operation == "replace":
        staged_path = text(request["staged_path"])
        if not bound_stage(staged_path, binding):
            fail(INVALID)
        staged_directory, staged_name = parent(staged_path)
        if (
            os.fstat(staged_directory).st_dev != os.fstat(directory).st_dev
            or os.fstat(staged_directory).st_ino != os.fstat(directory).st_ino
        ):
            fail(UNSAFE)
        staged = opened(
            staged_directory,
            staged_name,
            expected_value(request["expected_staged"]),
        )
        destination = opened(directory, name, expected)
        if not isinstance(staged, int) or destination is False:
            fail(PRECONDITION)
        if not replace(
            directory,
            staged_name,
            staged,
            expected_value(request["expected_staged"]),
            name,
            destination,
            expected,
        ):
            fail(PRECONDITION)
        os.fsync(directory)
    else:
        payload_value = request["content"]
        if payload_value is None:
            remove_expected(
                directory,
                name,
                expected,
                binding,
                request["operation_id"],
            )
        else:
            payload = base64.b64decode(
                text(payload_value, MAX_FILE_SIZE * 2),
                validate=True,
            )
            desired_mode = mode_value(request["mode"])
            suffix = hashlib.sha256(
                (request["binding_digest"] + request["operation_id"]).encode()
            ).hexdigest()[:32]
            staged_name = "." + name + "." + suffix + ".restore"
            if not absent(directory, staged_name):
                fail(PRECONDITION)
            destination = opened(directory, name, expected)
            if destination is False:
                fail(PRECONDITION)
            staged = create(directory, staged_name, payload, desired_mode)
            staged_expected = {
                "content_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "entry_kind": "regular",
                "managed_mode": desired_mode,
                "presence": "present",
            }
            if not replace(
                directory,
                staged_name,
                staged,
                staged_expected,
                name,
                destination,
                expected,
            ):
                if still_named(staged, directory, staged_name):
                    os.unlink(staged_name, dir_fd=directory)
                fail(PRECONDITION)
            os.fsync(directory)
except SystemExit:
    raise
except (FileNotFoundError, FileExistsError):
    fail(PRECONDITION if not mutated else AMBIGUOUS)
except (NotADirectoryError, PermissionError):
    fail(UNSAFE if not mutated else AMBIGUOUS)
except OSError as error:
    if not mutated and error.errno in (errno.ELOOP, errno.ENOTDIR):
        fail(UNSAFE)
    fail(AMBIGUOUS if mutated else PRECONDITION)
except (ValueError, TypeError, KeyError, json.JSONDecodeError):
    fail(INVALID)
finally:
    close_failed = False
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            close_failed = True
    if close_failed and not mutated:
        fail(UNSAFE)
raise SystemExit(APPLIED)
"""


_COMMAND = (
    "/usr/bin/python3 -c "
    "'import binascii,zlib;exec(zlib.decompress(binascii.unhexlify(\""
    + zlib.compress(_HELPER, level=9).hex()
    + "\")))'"
)


class FixedManagedMutationHelper:
    def __init__(self, commands: CommandRunner) -> None:
        self._commands = commands

    def supported(self) -> bool:
        result = self._execute(
            "probe",
            "/",
            "probe",
            "sha256:" + "0" * 64,
            _absent_state(),
        )
        return result.code is ManagedMutationCode.APPLIED

    def mutate(
        self,
        operation: str,
        path: str,
        operation_id: str,
        binding_digest: str,
        expected: NormalizedResourceState,
        *,
        content: bytes | None = None,
        mode: int | None = None,
        staged_path: str | None = None,
        expected_staged: NormalizedResourceState | None = None,
    ) -> ManagedMutationResult:
        return self._execute(
            operation,
            path,
            operation_id,
            binding_digest,
            expected,
            content=content,
            mode=mode,
            staged_path=staged_path,
            expected_staged=expected_staged,
        )

    def _execute(
        self,
        operation: str,
        path: str,
        operation_id: str,
        binding_digest: str,
        expected: NormalizedResourceState,
        *,
        content: bytes | None = None,
        mode: int | None = None,
        staged_path: str | None = None,
        expected_staged: NormalizedResourceState | None = None,
    ) -> ManagedMutationResult:
        request = canonical_document_bytes(
            {
                "binding_digest": binding_digest,
                "content": (
                    base64.b64encode(content).decode("ascii")
                    if content is not None
                    else None
                ),
                "expected": _state_value(expected),
                "expected_staged": (
                    _state_value(expected_staged)
                    if expected_staged is not None
                    else None
                ),
                "mode": mode,
                "operation": operation,
                "operation_id": operation_id,
                "path": path,
                "staged_path": staged_path,
            }
        )
        outcome = self._commands.execute(_COMMAND, stdin=request, timeout=30.0)
        if getattr(outcome, "failure", None) is not None:
            return ManagedMutationResult(ManagedMutationCode.AMBIGUOUS)
        exit_status = getattr(outcome, "exit_status", None)
        code = {
            0: ManagedMutationCode.APPLIED,
            64: ManagedMutationCode.PRECONDITION_CHANGED,
            65: ManagedMutationCode.UNSAFE,
            66: ManagedMutationCode.PRECONDITION_CHANGED,
            67: ManagedMutationCode.UNSUPPORTED,
            68: ManagedMutationCode.AMBIGUOUS,
        }.get(
            exit_status if isinstance(exit_status, int) else -1,
            ManagedMutationCode.AMBIGUOUS,
        )
        return ManagedMutationResult(code)


def _state_value(state: NormalizedResourceState) -> dict[str, object]:
    return {
        "content_digest": state.content_digest,
        "entry_kind": state.entry_kind,
        "managed_mode": state.managed_mode,
        "presence": state.presence.value,
    }


def _absent_state() -> NormalizedResourceState:
    return NormalizedResourceState(Presence.ABSENT, None, None, None)
