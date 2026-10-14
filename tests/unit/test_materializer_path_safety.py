from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "packages/contracts/src", ROOT / "packages/installer-core/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from vgo_installer.materializer import (
    copy_dir_replace,
    copy_file,
    copy_tree,
    materialize_internal_skill_corpus,
)


def _directory_link(link: Path, target: Path, kind: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if kind == "junction":
        if os.name != "nt":
            pytest.skip("directory junctions are Windows-only")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            pytest.skip(f"directory junctions are unavailable: {result.stderr.strip()}")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symbolic links are unavailable: {exc}")


@pytest.mark.parametrize("kind", ["symlink", "junction"])
@pytest.mark.parametrize("linked_parent", [False, True])
def test_replace_refuses_linked_destination_and_parent(
    tmp_path: Path, kind: str, linked_parent: bool
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "package.txt").write_text("new package\n", encoding="utf-8")
    target_root = tmp_path / "host"
    external = tmp_path / "external"
    external.mkdir()
    external_destination = external / "demo" if linked_parent else external
    external_destination.mkdir(exist_ok=True)
    marker = external_destination / "user.txt"
    marker.write_text("user data\n", encoding="utf-8")
    link = target_root / "skills" if linked_parent else target_root / "skills/demo"
    _directory_link(link, external, kind)
    destination = target_root / "skills/demo"
    assert destination.resolve().is_relative_to(tmp_path.resolve())
    tracked: list[Path | str] = []

    with pytest.raises(RuntimeError, match="link|reparse|outside"):
        copy_dir_replace(
            source,
            destination,
            target_root=target_root,
            track_created_path=tracked.append,
            record_owned_tree_root=tracked.append,
        )

    assert marker.read_text(encoding="utf-8") == "user data\n"
    assert not (external_destination / "package.txt").exists()
    assert not tracked


@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_file_copy_refuses_linked_parent(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source.txt"
    source.write_text("package\n", encoding="utf-8")
    target_root = tmp_path / "host"
    external = tmp_path / "external"
    external.mkdir()
    destination = target_root / "commands/vibe.md"
    external_file = external / "vibe.md"
    external_file.write_text("user data\n", encoding="utf-8")
    _directory_link(target_root / "commands", external, kind)

    with pytest.raises(RuntimeError, match="link|reparse|outside"):
        copy_file(source, destination, target_root=target_root)

    assert external_file.read_text(encoding="utf-8") == "user data\n"


def test_file_copy_refuses_leaf_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("package\n", encoding="utf-8")
    target_root = tmp_path / "host"
    target_root.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("user data\n", encoding="utf-8")
    destination = target_root / "package.txt"
    try:
        destination.symlink_to(external)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="link|reparse|outside"):
        copy_file(source, destination, target_root=target_root)

    assert external.read_text(encoding="utf-8") == "user data\n"


@pytest.mark.parametrize("operation", ["directory", "file", "tree"])
def test_materialization_refuses_paths_outside_declared_root(
    tmp_path: Path, operation: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "package.txt"
    source_file.write_text("package\n", encoding="utf-8")
    target_root = tmp_path / "host"
    destination = target_root / "../external"
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "user.txt"
    marker.write_text("user data\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside"):
        if operation == "directory":
            copy_dir_replace(source, destination, target_root=target_root)
        elif operation == "file":
            copy_file(source_file, destination / "user.txt", target_root=target_root)
        else:
            copy_tree(source, destination, target_root=target_root)

    assert marker.read_text(encoding="utf-8") == "user data\n"
    assert not (external / "package.txt").exists()


def test_replace_preserves_staging_for_nested_source(tmp_path: Path) -> None:
    target_root = tmp_path / "host"
    destination = target_root / "package"
    source = destination / "source"
    source.mkdir(parents=True)
    (source / "package.txt").write_text("new package\n", encoding="utf-8")
    (destination / "retired.txt").write_text("retired\n", encoding="utf-8")

    copy_dir_replace(source, destination, target_root=target_root)

    assert (destination / "package.txt").read_text(encoding="utf-8") == "new package\n"
    assert not (destination / "retired.txt").exists()
    assert not (destination / "source").exists()


@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_disabled_corpus_cleanup_refuses_linked_parent(tmp_path: Path, kind: str) -> None:
    target_root = tmp_path / "host"
    external = tmp_path / "external"
    corpus = external / "vibe/bundled/skills"
    corpus.mkdir(parents=True)
    marker = corpus / "user.txt"
    marker.write_text("user data\n", encoding="utf-8")
    _directory_link(target_root / "skills", external, kind)
    assert corpus.resolve().is_relative_to(tmp_path.resolve())

    with pytest.raises(RuntimeError, match="link|reparse|outside"):
        materialize_internal_skill_corpus(
            tmp_path / "repo",
            target_root,
            {"internal_skill_corpus": {"enabled": False}},
            copy_dir_replace_fn=lambda source, destination: pytest.fail("unexpected copy"),
        )

    assert marker.read_text(encoding="utf-8") == "user data\n"
