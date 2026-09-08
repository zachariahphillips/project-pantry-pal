"""
Phase 7S regression suite — legacy Fly backup workflow failure docs.

The Fly workflow used to be scheduled while Fly was the primary deploy target.
Phase 7V moved the README's happy path to PythonAnywhere, so these tests now
guard the manual legacy troubleshooting path instead of nightly alerts.

Tier-1 dev loop:

    pytest tests/test_phase_7s.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_backup_workflow_failure_triage():
    readme = (ROOT / "README.md").read_text()

    assert "#### When the legacy Fly backup workflow fails" in readme
    assert "Actions -> Legacy Fly SQLite Backup" in readme
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
    ):
        assert quoted_from_readme in readme
        assert quoted_from_readme in workflow

    assert "workflow_dispatch" in workflow
    assert "schedule:" not in workflow


def test_readme_documents_manual_backup_fallback_and_escalation():
    readme = (ROOT / "README.md").read_text()

    assert 'fly ssh console -C "python /app/scripts/backup_sqlite.py --keep 14"' in readme
    assert "Escalate only if you are actively using Fly again" in readme
