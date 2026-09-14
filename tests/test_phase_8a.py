"""
Phase 8A regression suite — no-cost hosting cleanup.

Phase 7V moved PantryPal's happy path from Fly to PythonAnywhere, but the
backup helper still defaulted to Fly's `/data/...` paths. 8A makes the helper
defaults match the no-cost PythonAnywhere layout and keeps legacy Fly explicit
where it still appears.

Tier-1 dev loop:

    pytest tests/test_phase_8a.py -q
"""
from __future__ import annotations

from pathlib import Path

from scripts.backup_sqlite import DEFAULT_DEST_DIR, DEFAULT_SOURCE, parse_args


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"
LEGACY_FLY_BACKUP_FLAGS = (
    "--source /data/pantrypal.sqlite3 "
    "--dest-dir /data/backups "
    "--verify --emit-base64 --keep 14"
)


def test_backup_helper_defaults_to_pythonanywhere_paths():
    assert DEFAULT_SOURCE == Path("data/pantrypal.sqlite3")
    assert DEFAULT_DEST_DIR == Path("backups")

    args = parse_args([])

    assert args.source == Path("data/pantrypal.sqlite3")
    assert args.dest_dir == Path("backups")


def test_readme_pythonanywhere_backup_command_uses_short_defaults():
    readme = README.read_text()

    assert "backup_sqlite.py` defaults to" in readme
    assert "`data/pantrypal.sqlite3` and `backups`" in readme
    assert "python scripts/backup_sqlite.py \\\n  --verify \\\n  --keep 14" in readme


def test_legacy_fly_workflow_pins_old_volume_paths_explicitly():
    workflow = WORKFLOW.read_text()

    assert LEGACY_FLY_BACKUP_FLAGS in workflow


def test_legacy_fly_runbook_pins_old_volume_paths_explicitly():
    readme = README.read_text()

    assert "--source /data/pantrypal.sqlite3 --dest-dir /data/backups" in readme
    assert LEGACY_FLY_BACKUP_FLAGS in readme
