from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_SRC = ROOT / 'packages' / 'contracts' / 'src'
INSTALLER_SRC = ROOT / 'packages' / 'installer-core' / 'src'
for src in (CONTRACTS_SRC, INSTALLER_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

from vgo_contracts.discoverable_entry_surface import load_discoverable_entry_surface
import vgo_installer.discoverable_wrappers as discoverable_wrappers
from vgo_installer.discoverable_wrappers import build_wrapper_descriptors


def test_build_wrapper_descriptors_renders_all_discoverable_entries_for_codex() -> None:
    surface = load_discoverable_entry_surface(ROOT)

    rendered = build_wrapper_descriptors(
        host_id='codex',
        surface=surface,
    )

    assert sorted(rendered) == ['vibe']
    assert rendered['vibe'].relpath.as_posix() == 'commands/vibe.md'
    assert 'Wrapper entry: Vibe (`vibe`)' in rendered['vibe'].content
    assert '"schema": "vibe-wrapper-trampoline/v1"' in rendered['vibe'].content
    assert '"launch_mode": "canonical-entry"' in rendered['vibe'].content
    assert '"host_id": "codex"' in rendered['vibe'].content
    assert '"entry_id": "vibe"' in rendered['vibe'].content
    assert '"progressive_stage_stops": [' in rendered['vibe'].content
    assert 'Progressive stop sequence: `requirement_doc`, `xl_plan`, `phase_cleanup`' in rendered['vibe'].content
    assert 'Do not consume `--continue-from-run-id` and `--bounded-reentry-token` in the same assistant turn' in rendered['vibe'].content
    assert 'Dispatch through canonical-entry runtime bridge.' in rendered['vibe'].content
    assert 'Do not preflight-scan the current workspace or repository for canonical proof files before launch.' in rendered['vibe'].content
    assert 'validate canonical proof artifacts only inside that launched session root.' in rendered['vibe'].content
    assert 'Wrapper labels only select the bounded terminal stage.' in rendered['vibe'].content


def test_build_wrapper_descriptors_renders_skill_wrappers_for_skill_only_hosts() -> None:
    surface = load_discoverable_entry_surface(ROOT)

    rendered = build_wrapper_descriptors(
        host_id='claude-code',
        surface=surface,
    )

    assert sorted(rendered) == ['vibe']
    assert rendered['vibe'].relpath.as_posix() == 'skills/vibe/SKILL.md'
    assert 'name: vibe' in rendered['vibe'].content
    assert 'Wrapper entry: Vibe (`vibe`)' in rendered['vibe'].content
    assert '"schema": "vibe-wrapper-trampoline/v1"' in rendered['vibe'].content
    assert '"launch_mode": "canonical-entry"' in rendered['vibe'].content
    assert '"host_id": "claude-code"' in rendered['vibe'].content
    assert '"entry_id": "vibe"' in rendered['vibe'].content
    assert '"progressive_stage_stops": [' in rendered['vibe'].content
    assert 'Progressive stop sequence: `requirement_doc`, `xl_plan`, `phase_cleanup`' in rendered['vibe'].content
    assert 'Dispatch through canonical-entry runtime bridge.' in rendered['vibe'].content
    assert 'Do not preflight-scan the current workspace or repository for canonical proof files before launch.' in rendered['vibe'].content
    assert 'validate canonical proof artifacts only inside that launched session root.' in rendered['vibe'].content
    assert 'Claude Code Bash-safe launch shape' in rendered['vibe'].content
    assert 'WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PWD}"' in rendered['vibe'].content
    assert '--artifact-root "$WORKSPACE_ROOT"' in rendered['vibe'].content
    assert 'DECISION_JSON="$WORKSPACE_ROOT/.vibeskills/tmp/host-decision.json"' in rendered['vibe'].content
    assert '--artifact-root "$PWD"' not in rendered['vibe'].content
    assert 'DECISION_JSON="$PWD/.vibeskills/tmp/host-decision.json"' not in rendered['vibe'].content
    assert '--host-decision-json-file "$DECISION_JSON"' in rendered['vibe'].content
    assert 'include a non-empty `revision_delta`' in rendered['vibe'].content
    assert '$ARGUMENTS' in rendered['vibe'].content


def test_build_wrapper_descriptors_fails_closed_when_canonical_contract_is_unresolved(monkeypatch) -> None:
    surface = load_discoverable_entry_surface(ROOT)

    def fail_contract(repo_root, host_id):  # type: ignore[no-untyped-def]
        raise ValueError(f"canonical_vibe contract missing for host: {host_id}")

    monkeypatch.setattr(discoverable_wrappers, "resolve_canonical_vibe_contract", fail_contract)

    with pytest.raises(ValueError, match="canonical_vibe contract missing"):
        build_wrapper_descriptors(
            host_id="codex",
            surface=surface,
        )


@pytest.mark.parametrize("destination_kind", ["relative", "absolute"])
def test_wrapper_writer_rejects_targets_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination_kind: str
) -> None:
    surface = load_discoverable_entry_surface(ROOT)
    target_root = tmp_path / "host"
    outside = tmp_path / "escaped.md"
    outside.write_text("user data\n", encoding="utf-8")
    destination = Path("../escaped.md") if destination_kind == "relative" else outside
    assert (target_root / destination).resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setattr(discoverable_wrappers, "_host_surface_targets", lambda host, descriptor: (destination,))

    with pytest.raises(RuntimeError, match="outside"):
        discoverable_wrappers.materialize_host_visible_wrappers(
            target_root=target_root, host_id="codex", surface=surface
        )

    assert outside.read_text(encoding="utf-8") == "user data\n"
    assert not target_root.exists()


@pytest.mark.parametrize("host_id", ["codex", "claude-code"])
@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_wrapper_writer_refuses_linked_surface_parent(
    tmp_path: Path, host_id: str, kind: str
) -> None:
    from tests.unit.test_materializer_path_safety import _directory_link

    surface = load_discoverable_entry_surface(ROOT)
    target_root = tmp_path / "host"
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "user.txt"
    marker.write_text("user data\n", encoding="utf-8")
    surface_directory = "commands" if host_id == "codex" else "skills"
    _directory_link(target_root / surface_directory, external, kind)

    with pytest.raises(RuntimeError, match="link|reparse|outside"):
        discoverable_wrappers.materialize_host_visible_wrappers(
            target_root=target_root, host_id=host_id, surface=surface
        )

    assert marker.read_text(encoding="utf-8") == "user data\n"
    assert not (external / "vibe.md").exists()
    assert not (external / "vibe/SKILL.md").exists()
