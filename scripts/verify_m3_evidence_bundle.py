#!/usr/bin/env python3

"""Independently verify a synthetic M3 pilot dry-run evidence bundle."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "coreelec-reconciler-m3-pilot-dry-run-1"
EXPECTED_SCENARIOS = (
    ("absent-create", "converged", ("stage-write", "atomic-replace")),
    ("formatting-noop", "noop", ()),
    ("semantic-drift", "converged", ("stage-write", "atomic-replace")),
    ("mode-drift", "converged", ("chmod",)),
    ("malformed-xml", "converged", ("stage-write", "atomic-replace")),
    ("explicit-removal", "converged", ("remove",)),
    ("recreate-and-kodi", "converged", ("stage-write", "atomic-replace")),
    ("immediate-noop", "noop", ()),
)
EXPECTED_FILES = {"manifest.json", "sequence.json", "digests.json", "bundle.sha256"}
CONFIGURATION_PATHS = ("artifacts", "inventory", "profiles", "secret-providers")
FORBIDDEN_TEXT = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "Traceback (most recent call last)",
    "raw_exception",
)
PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\)")


class VerificationError(ValueError):
    pass


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an M3 evidence bundle.")
    parser.add_argument("bundle", type=Path)
    return parser.parse_args()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _configuration_digest(root: Path) -> str:
    paths = _git(root, "ls-files", "--", *CONFIGURATION_PATHS).splitlines()
    digest = hashlib.sha256()
    for relative in sorted(filter(None, paths)):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{path.name} is not valid JSON") from error
    if not isinstance(value, dict) or _canonical(value) != path.read_bytes():
        raise VerificationError(f"{path.name} is not canonical JSON")
    return value


def _reject_contamination(bundle: Path) -> None:
    for path in bundle.iterdir():
        if not path.is_file():
            raise VerificationError("nested or non-file bundle content is forbidden")
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        if PRIVATE_PATH.search(text) or any(value in text for value in FORBIDDEN_TEXT):
            raise VerificationError("bundle contains private or raw exception content")
        lowered = text.casefold()
        if any(
            marker in lowered
            for marker in (
                '"password":',
                '"private_key":',
                '"secret_value":',
                '"credential_value":',
            )
        ):
            raise VerificationError("bundle contains secret-bearing fields")


def verify_bundle(bundle: Path, root: Path) -> str:
    if not bundle.is_dir():
        raise VerificationError("bundle directory is missing")
    names = {path.name for path in bundle.iterdir()}
    if names != EXPECTED_FILES:
        raise VerificationError("bundle files are missing or unexpected")
    _reject_contamination(bundle)

    manifest = _object(bundle / "manifest.json")
    sequence = _object(bundle / "sequence.json")
    digests = _object(bundle / "digests.json")
    if set(manifest) != {
        "schema",
        "bundle_kind",
        "attempts",
        "components",
        "source",
        "bindings",
        "identity",
        "safety",
        "sequence",
    }:
        raise VerificationError("manifest fields are invalid")
    if set(sequence) != {
        "schema",
        "mode",
        "device_contact",
        "secret_resolution",
        "scenarios",
    }:
        raise VerificationError("sequence fields are invalid")
    if manifest.get("schema") != SCHEMA or sequence.get("schema") != SCHEMA:
        raise VerificationError("schema mismatch")
    if manifest.get("bundle_kind") != "synthetic-core-dry-run":
        raise VerificationError("bundle is not the synthetic core dry run")
    if manifest.get("attempts") != 1 or manifest.get("components") != ["core"]:
        raise VerificationError("stitched or duplicate attempt evidence is forbidden")

    source = manifest.get("source")
    bindings = manifest.get("bindings")
    if not isinstance(source, dict) or not isinstance(bindings, dict):
        raise VerificationError("source binding is missing")
    expected_source = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
    }
    if source != expected_source:
        raise VerificationError("source commit or tree mismatch")
    if bindings != {
        "configuration_sha256": _configuration_digest(root),
        "lock_sha256": _sha256((root / "uv.lock").read_bytes()),
    }:
        raise VerificationError("configuration or lock mismatch")

    identity = manifest.get("identity")
    if identity != {
        "device_id": "synthetic-device",
        "resource_id": "skin.playlist.new-shows",
        "logical_address": "special://profile/playlists/video/NewShows.xsp",
    }:
        raise VerificationError("real or invalid Device identity is forbidden")
    safety = manifest.get("safety")
    expected_safety = {
        "dry_run_only": True,
        "device_contact": False,
        "secret_resolution": False,
        "synthetic_values_only": True,
        "live_use_authorized": False,
        "ownership_transfer_authorized": False,
        "skin_025_owner": "shell",
        "effects_changed": False,
    }
    if safety != expected_safety:
        raise VerificationError("dry-run safety boundary is invalid")

    scenarios = sequence.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(EXPECTED_SCENARIOS):
        raise VerificationError("core scenario set is incomplete")
    observed: list[tuple[str, str, tuple[str, ...]]] = []
    ordinals: list[int] = []
    for item in scenarios:
        if not isinstance(item, dict):
            raise VerificationError("scenario entry is invalid")
        identifier = item.get("id")
        status = item.get("expected_status")
        trace = item.get("expected_trace")
        ordinal = item.get("ordinal")
        if (
            not isinstance(identifier, str)
            or not isinstance(status, str)
            or not isinstance(trace, list)
            or not all(isinstance(value, str) for value in trace)
            or not isinstance(ordinal, int)
        ):
            raise VerificationError("scenario semantics are invalid")
        allowed_fields = {"ordinal", "id", "expected_status", "expected_trace"}
        if identifier == "explicit-removal":
            allowed_fields.add("approval")
            if item.get("approval") != "reviewed-removal-approval":
                raise VerificationError("removal approval semantics are invalid")
        if identifier == "recreate-and-kodi":
            allowed_fields.add("kodi_usability")
            if item.get("kodi_usability") != "operator-attestation-required":
                raise VerificationError("Kodi attestation semantics are invalid")
        if set(item) != allowed_fields:
            raise VerificationError("scenario fields are invalid")
        observed.append((identifier, status, tuple(trace)))
        ordinals.append(ordinal)
    if tuple(observed) != EXPECTED_SCENARIOS:
        raise VerificationError("scenario semantics or ordering is invalid")
    if ordinals != list(range(1, len(EXPECTED_SCENARIOS) + 1)):
        raise VerificationError("scenario ordinals are missing or duplicated")
    if (
        sequence.get("mode") != "description-only"
        or sequence.get("device_contact") is not False
        or sequence.get("secret_resolution") is not False
    ):
        raise VerificationError("sequence is not an offline description")

    expected_digests = {
        name: _sha256((bundle / name).read_bytes())
        for name in ("manifest.json", "sequence.json")
    }
    if digests != {"schema": SCHEMA, "files": expected_digests}:
        raise VerificationError("artifact digest mismatch")
    digest_bytes = (bundle / "digests.json").read_bytes()
    bundle_digest = (bundle / "bundle.sha256").read_text(encoding="ascii")
    if bundle_digest != _sha256(digest_bytes) + "\n":
        raise VerificationError("bundle digest mismatch")
    return bundle_digest.strip()


def main() -> int:
    arguments = _arguments()
    root = Path(__file__).resolve().parents[1]
    try:
        digest = verify_bundle(arguments.bundle.resolve(), root)
    except (OSError, subprocess.CalledProcessError, VerificationError) as error:
        print(f"evidence bundle rejected: {error}")
        return 2
    print(f"evidence bundle verified: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
