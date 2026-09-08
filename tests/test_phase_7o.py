"""
Phase 7O regression suite — legacy Fly backup workflow.

The workflow used to be scheduled while Fly was the primary deploy target.
Phase 7V moved the app to PythonAnywhere for no-cost hosting, so the Fly
workflow should stay manual-only while still running the tested helper if
someone intentionally dispatches it.

Tier-1 dev loop:

    pytest tests/test_phase_7o.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"


def test_legacy_fly_backup_workflow_is_manual_only():
    workflow = WORKFLOW.read_text()

    assert "name: Legacy Fly SQLite Backup" in workflow
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow
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
