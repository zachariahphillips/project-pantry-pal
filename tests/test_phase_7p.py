"""
Phase 7P regression suite — off-volume backup artifacts.

The scheduled backup workflow uploads a short-retention GitHub Actions
artifact. The helper emits marker-delimited base64 so workflow logs can skip
printing database contents while still decoding the artifact file.

Tier-1 dev loop:

    pytest tests/test_phase_7p.py -q
"""
from __future__ import annotations

import base64
from io import StringIO
from pathlib import Path

from scripts.backup_sqlite import (
    BASE64_BEGIN_MARKER,
    BASE64_END_MARKER,
    emit_backup_base64,
)


ROOT = Path(__file__).resolve().parents[1]


def test_backup_helper_emits_marker_delimited_base64(tmp_path):
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(b"sqlite backup bytes")
    output = StringIO()

    emit_backup_base64(backup, output)

    lines = output.getvalue().splitlines()
    assert lines[0] == BASE64_BEGIN_MARKER
    assert lines[-1] == BASE64_END_MARKER
    encoded = "".join(lines[1:-1])
    assert base64.b64decode(encoded) == b"sqlite backup bytes"


def test_backup_workflow_uploads_short_retention_artifact():
    workflow = (ROOT / ".github" / "workflows" / "backup.yml").read_text()
    readme = (ROOT / "README.md").read_text()

    assert "--emit-base64" in workflow
    assert "base64 --decode > pantrypal-backup.sqlite3" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "path: pantrypal-backup.sqlite3" in workflow
    assert "retention-days: 14" in workflow
    assert "14-day GitHub Actions artifact" in readme
