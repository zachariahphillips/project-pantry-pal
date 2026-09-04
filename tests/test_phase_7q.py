"""
Phase 7Q regression suite — backup retention pruning.

Scheduled backups should keep recent restore points without letting
/data/backups grow forever. Pruning must only touch PantryPal backup files.

Tier-1 dev loop:

    pytest tests/test_phase_7q.py -q
"""
from __future__ import annotations

import os
from pathlib import Path

from scripts.backup_sqlite import prune_old_backups


ROOT = Path(__file__).resolve().parents[1]


def _write_backup(path: Path, mtime: int) -> Path:
    path.write_text("backup")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_old_backups_keeps_newest_and_ignores_unrelated_files(tmp_path):
    oldest = _write_backup(tmp_path / "pantrypal-20260901T000000Z.sqlite3", 1)
    middle = _write_backup(tmp_path / "pantrypal-20260902T000000Z.sqlite3", 2)
    newest = _write_backup(tmp_path / "pantrypal-20260903T000000Z.sqlite3", 3)
    unrelated = _write_backup(tmp_path / "other-20260901T000000Z.sqlite3", 0)
    notes = _write_backup(tmp_path / "notes.txt", 0)

    deleted = prune_old_backups(tmp_path, keep=2)

    assert deleted == [oldest]
    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()
    assert unrelated.exists()
    assert notes.exists()


def test_backup_workflow_prunes_fly_volume_backups():
    workflow = (ROOT / ".github" / "workflows" / "backup.yml").read_text()
    readme = (ROOT / "README.md").read_text()

    assert "--emit-base64 --keep 14" in workflow
    assert "keeps only the newest 14 backups" in readme
