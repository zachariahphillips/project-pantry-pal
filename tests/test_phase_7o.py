"""
Phase 7O regression suite — scheduled backup workflow.

The workflow should stay manual/scheduled only and should run the tested Fly
backup helper with an explicit FLY_API_TOKEN secret.

Tier-1 dev loop:

    pytest tests/test_phase_7o.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"


def test_backup_workflow_is_manual_and_scheduled():
    workflow = WORKFLOW.read_text()

    assert "name: Backup SQLite" in workflow
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert 'cron: "23 10 * * *"' in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow


def test_backup_workflow_runs_fly_backup_helper():
    workflow = WORKFLOW.read_text()
    readme = (ROOT / "README.md").read_text()

    assert "FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}" in workflow
    assert "FLY_APP_NAME: pantrypal-riah" in workflow
    assert 'fly ssh console --app "$FLY_APP_NAME"' in workflow
    assert "python /app/scripts/backup_sqlite.py" in workflow
    assert "repository secret named `FLY_API_TOKEN`" in readme
    assert ".github/workflows/backup.yml" in readme
