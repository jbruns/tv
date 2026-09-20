#!/usr/bin/env python3

"""Write deterministic, synthetic M3 pilot-readiness evidence."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "coreelec-reconciler-m3-pilot-dry-run-1"
SYNTHETIC_DEVICE_ID = "synthetic-device"
CONFIGURATION_PATHS = ("artifacts", "inventory", "profiles", "secret-providers")
CORE_SEQUENCE: tuple[dict[str, Any], ...] = (
    {
        "id": "absent-create",
        "expected_status": "converged",
        "expected_trace": ["stage-write", "atomic-replace"],
    },
    {
        "id": "formatting-noop",
        "expected_status": "noop",
        "expected_trace": [],
    },
    {
        "id": "semantic-drift",
        "expected_status": "converged",
        "expected_trace": ["stage-write", "atomic-replace"],
    },
    {
        "id": "mode-drift",
        "expected_status": "converged",
        "expected_trace": ["chmod"],
    },
    {
        "id": "malformed-xml",
        "expected_status": "converged",
        "expected_trace": ["stage-write", "atomic-replace"],
    },
    {
        "id": "explicit-removal",
        "expected_status": "converged",
        "expected_trace": ["remove"],
        "approval": "reviewed-removal-approval",
    },
    {
        "id": "recreate-and-kodi",
        "expected_status": "converged",
        "expected_trace": ["stage-write", "atomic-replace"],
        "kodi_usability": "operator-attestation-required",
    },
    {
        "id": "immediate-noop",
        "expected_status": "noop",
        "expected_trace": [],
    },
)


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

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    source = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
    }
    sequence = {
        "schema": SCHEMA,
        "mode": "description-only",
        "device_contact": False,
        "secret_resolution": False,
        "scenarios": [
            {"ordinal": index, **scenario}
            for index, scenario in enumerate(CORE_SEQUENCE, start=1)
        ],
    }
    manifest = {
        "schema": SCHEMA,
        "bundle_kind": "synthetic-core-dry-run",
        "attempts": 1,
        "components": ["core"],
        "source": source,
        "bindings": {
            "configuration_sha256": _configuration_digest(root, "HEAD"),
            "lock_sha256": _sha256(lock_bytes),
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
        "sequence": "sequence.json",
    }
    files = {
        "manifest.json": _canonical(manifest),
        "sequence.json": _canonical(sequence),
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
        digest = generate_bundle(root, arguments.output.resolve())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"pilot dry run refused: {error}")
        return 2
    print(f"synthetic M3 pilot dry run: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
