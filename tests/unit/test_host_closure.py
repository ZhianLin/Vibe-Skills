from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "packages/contracts/src", ROOT / "packages/installer-core/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from vgo_installer.host_closure import (
    install_claude_managed_settings,
    sanitize_legacy_opencode_config,
)


def test_claude_settings_preserve_existing_fields_with_utf8_bom(tmp_path: Path) -> None:
    target_root = tmp_path / ".claude"
    target_root.mkdir()
    settings_path = target_root / "settings.json"
    settings_path.write_text('{"existing": true}\n', encoding="utf-8-sig")

    materialized = install_claude_managed_settings(
        tmp_path,
        target_root,
        track_created_path=lambda path: None,
        record_managed_json=lambda path: None,
        record_merged_file=lambda path, **kwargs: None,
    )

    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    assert materialized == [str(settings_path.resolve())]
    assert settings["existing"] is True
    assert settings["vibeskills"]["managed"] is True


def test_opencode_cleanup_accepts_utf8_bom_and_preserves_foreign_fields(tmp_path: Path) -> None:
    settings_path = tmp_path / "opencode.json"
    settings_path.write_text(
        '{"existing": true, "vibeskills": {"managed": true}}\n',
        encoding="utf-8-sig",
    )

    receipt = sanitize_legacy_opencode_config(tmp_path)

    assert receipt["status"] == "removed-owned-node"
    assert json.loads(settings_path.read_text(encoding="utf-8-sig")) == {"existing": True}
