"""
Phase 7S regression suite — backup workflow failure docs.

A failed backup run is silent: the app keeps serving traffic while restore
points quietly stop accumulating. These tests guard the triage runbook so the
"what do I do about a red backup run" answer stays in the README, and so the
symptoms it tells you to match keep matching what backup.yml actually emits.

Tier-1 dev loop:

    pytest tests/test_phase_7s.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_backup_workflow_failure_triage():
    readme = (ROOT / "README.md").read_text()

    assert "#### When the backup workflow fails" in readme
    assert "Actions -> Backup SQLite" in readme
    assert "fly tokens create deploy" in readme
    assert "fly machine start <machine-id>" in readme


def test_readme_failure_symptoms_match_the_backup_workflow():
    """The triage table is only useful if its symptoms are real.

    Each string below is quoted from the runbook, so renaming a step or the
    token guard in backup.yml without updating the README fails here instead of
    at 3am during a restore.
    """
    readme = (ROOT / "README.md").read_text()
    workflow = (ROOT / ".github" / "workflows" / "backup.yml").read_text()

    for quoted_from_readme in (
        "Create timestamped backup on Fly volume",
        "Upload SQLite backup artifact",
        "Set the FLY_API_TOKEN repository secret before running backups.",
        "test -s pantrypal-backup.sqlite3",
        "if-no-files-found: error",
        "23 10 * * *",
    ):
        assert quoted_from_readme in readme
        assert quoted_from_readme in workflow

    assert "workflow_dispatch" in workflow


def test_readme_documents_manual_backup_fallback_and_escalation():
    readme = (ROOT / "README.md").read_text()

    assert "no activity for 60 days" in readme
    assert 'fly ssh console -C "python /app/scripts/backup_sqlite.py --keep 14"' in readme
    assert "two consecutive nights fail" in readme
