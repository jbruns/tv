#!/usr/bin/env python3

"""Write deterministic, synthetic M3 pilot-readiness evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from coreelec_reconciler.pilot_dry_run import SCHEMA, execute_dry_run

SYNTHETIC_DEVICE_ID = "synthetic.device"
CONFIGURATION_PATHS = ("artifacts", "inventory", "profiles", "secret-providers")
OUTPUT_FILES = frozenset(
    {
        "manifest.json",
        "execution.json",
        "artifacts.json",
        "digests.json",
        "bundle.sha256",
    }
)
OWNERSHIP_MARKER_SCHEMA = "coreelec-reconciler-m3-pilot-output-1"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic M3 pilot dry-run bundle."
    )
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _configuration_digest(root: Path, revision: str) -> str:
    tracked = _git(
        root, "ls-tree", "-r", "--name-only", revision, "--", *CONFIGURATION_PATHS
    ).splitlines()
    digest = hashlib.sha256()
    for relative in sorted(filter(None, tracked)):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(_git_bytes(root, "show", f"{revision}:{relative}"))
        digest.update(b"\0")
    return digest.hexdigest()


def _path_contains_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _is_equal_or_ancestor(candidate: Path, protected: Path) -> bool:
    return candidate == protected or candidate in protected.parents


def _ownership_marker(root: Path, output: Path) -> tuple[Path, bytes]:
    marker = output.parent / f".{output.name}.m3-pilot-owner"
    content = _canonical(
        {
            "schema": OWNERSHIP_MARKER_SCHEMA,
            "repository": str(root),
            "output": str(output),
        }
    )
    return marker, content


def _prepare_output(root: Path, requested_output: Path) -> Path:
    if _path_contains_symlink(requested_output):
        raise ValueError("output path must not contain a symlink")
    root = root.resolve(strict=True)
    output = requested_output.absolute()
    resolved_output = output.resolve(strict=False)
    if output != resolved_output:
        raise ValueError("output path must not contain a symlink")

    home = Path.home().resolve()
    protected = (Path("/"), home, root)
    if any(_is_equal_or_ancestor(resolved_output, item) for item in protected):
        raise ValueError("output must be a safe dedicated output path")
    internal_roots = (
        root / ".git",
        root / ".worktrees",
        home / ".copilot" / "session-state",
    )
    if any(
        resolved_output == item or item in resolved_output.parents
        for item in internal_roots
    ):
        raise ValueError("output must not use a repository or session root")
    if not output.parent.is_dir():
        raise ValueError("safe dedicated output parent must already exist")

    marker, expected_marker = _ownership_marker(root, resolved_output)
    if output.exists():
        if not output.is_dir() or not marker.is_file():
            raise ValueError("existing output is not harness-owned")
        if marker.read_bytes() != expected_marker:
            raise ValueError("existing output ownership marker does not match")
        entries = {entry.name for entry in output.iterdir()}
        unknown = entries - OUTPUT_FILES
        if unknown:
            raise ValueError("harness-owned output contains unknown content")
        for name in sorted(entries):
            path = output / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("harness-owned output contains unknown content")
            path.unlink()
    else:
        if marker.exists():
            if not marker.is_file() or marker.read_bytes() != expected_marker:
                raise ValueError("output ownership marker does not match")
        else:
            marker.write_bytes(expected_marker)
        output.mkdir()
    return resolved_output


def _remove_runtime(output: Path, runtime: Path) -> None:
    if runtime.parent != output or runtime.is_symlink():
        raise ValueError("synthetic runtime boundary is unsafe")
    if not runtime.exists():
        return
    for path in sorted(
        runtime.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if path.is_symlink():
            raise ValueError("synthetic runtime contains a symlink")
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
        else:
            raise ValueError("synthetic runtime contains unknown content")
    runtime.rmdir()


def generate_bundle(root: Path, output: Path) -> str:
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("source checkout must be clean")
    relevant_untracked = _git(
        root,
        "ls-files",
        "--others",
        "--",
        *CONFIGURATION_PATHS,
    )
    if relevant_untracked:
        raise ValueError("effective configuration contains untracked files")
    try:
        lock_bytes = _git_bytes(root, "show", "HEAD:uv.lock")
    except subprocess.CalledProcessError:
        raise ValueError("uv.lock is missing") from None

    output = _prepare_output(root, output)
    runtime = output / "runtime"
    runtime.mkdir()
    try:
        execution, artifacts = execute_dry_run(runtime)
    finally:
        _remove_runtime(output, runtime)

    source = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
    }
    execution_bytes = _canonical(execution)
    artifacts_bytes = _canonical(artifacts)
    manifest = {
        "schema": SCHEMA,
        "bundle_kind": "synthetic-core-execution-dry-run",
        "attempts": 1,
        "components": ["core"],
        "source": source,
        "bindings": {
            "configuration_sha256": _configuration_digest(root, "HEAD"),
            "lock_sha256": _sha256(lock_bytes),
            "scenario_inputs_sha256": _sha256(_canonical(execution["scenario_inputs"])),
        },
        "tools": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "coreelec_reconciler": importlib.metadata.version("coreelec-reconciler"),
            "uv": subprocess.run(
                ["uv", "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        },
        "execution": {
            "artifact": "execution.json",
            "artifacts": "artifacts.json",
            "exit_status": execution["exit_status"],
        },
        "identity": {
            "device_id": SYNTHETIC_DEVICE_ID,
            "resource_id": "skin.playlist.new-shows",
            "logical_address": ("special://profile/playlists/video/NewShows.xsp"),
        },
        "safety": {
            "dry_run_only": True,
            "device_contact": False,
            "secret_resolution": False,
            "synthetic_values_only": True,
            "live_use_authorized": False,
            "ownership_transfer_authorized": False,
            "skin_025_owner": "shell",
            "effects_changed": False,
        },
    }
    files = {
        "manifest.json": _canonical(manifest),
        "execution.json": execution_bytes,
        "artifacts.json": artifacts_bytes,
    }
    for name, content in files.items():
        (output / name).write_bytes(content)
    digests = {
        "schema": SCHEMA,
        "files": {name: _sha256(content) for name, content in sorted(files.items())},
    }
    digest_bytes = _canonical(digests)
    (output / "digests.json").write_bytes(digest_bytes)
    bundle_digest = _sha256(digest_bytes)
    (output / "bundle.sha256").write_text(bundle_digest + "\n", encoding="ascii")
    return bundle_digest


def main() -> int:
    arguments = _arguments()
    root = Path(__file__).resolve().parents[1]
    try:
        digest = generate_bundle(root, arguments.output)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"pilot dry run refused: {error}")
        return 2
    print(f"synthetic M3 pilot dry run: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
