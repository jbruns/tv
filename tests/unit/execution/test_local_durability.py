from pathlib import Path

import pytest

from coreelec_reconciler.execution.local_durability import (
    DurabilityError,
    PosixLocalDurability,
)


def test_write_private_rejects_a_symlinked_parent_component(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(DurabilityError):
        PosixLocalDurability().write_private(
            str(linked / "nested" / "secret"),
            b"secret",
        )


def test_file_and_directory_sync_reject_symlink_final_components(
    tmp_path: Path,
) -> None:
    file = tmp_path / "file"
    file.write_bytes(b"content")
    file_link = tmp_path / "file-link"
    file_link.symlink_to(file)
    directory = tmp_path / "directory"
    directory.mkdir()
    directory_link = tmp_path / "directory-link"
    directory_link.symlink_to(directory, target_is_directory=True)
    durability = PosixLocalDurability()

    with pytest.raises(DurabilityError):
        durability.full_sync_file(str(file_link))
    with pytest.raises(DurabilityError):
        durability.sync_directory(str(directory_link))


def test_atomic_replace_rejects_symlink_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"new")
    target = tmp_path / "target"
    target.write_bytes(b"old")
    destination = tmp_path / "destination"
    destination.symlink_to(target)

    with pytest.raises(DurabilityError):
        PosixLocalDurability().atomic_replace(str(source), str(destination))
    assert target.read_bytes() == b"old"
