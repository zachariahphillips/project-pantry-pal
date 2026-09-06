"""
Phase 7R regression suite — backup artifact restore docs.

GitHub Actions artifacts are the off-volume restore path. Keep the README
specific enough that restoring from one is mechanical.

Tier-1 dev loop:

    pytest tests/test_phase_7r.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_actions_artifact_download():
    readme = (ROOT / "README.md").read_text()

    assert "#### Restoring from a GitHub Actions artifact" in readme
    assert "Actions -> Backup SQLite" in readme
    assert "pantrypal-sqlite-backup-<run_id>" in readme
    assert "pantrypal-backup.sqlite3" in readme
    assert "unzip ~/Downloads/pantrypal-sqlite-backup-*.zip -d backups/" in readme


def test_readme_documents_artifact_restore_drill_and_upload():
    readme = (ROOT / "README.md").read_text()

    # Phase 7U replaced the hand-rolled gunicorn + prod_smoke dance here with
    # the scripted drill; the runbook step it stood for is unchanged.
    assert (
        ".venv/bin/python scripts/restore_drill.py backups/pantrypal-backup.sqlite3"
        in readme
    )
    assert "sftp> put backups/pantrypal-backup.sqlite3 /data/restore.sqlite3" in readme
