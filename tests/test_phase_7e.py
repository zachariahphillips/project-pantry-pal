"""
Phase 7E regression suite — GitHub Actions pytest CI.

The workflow is small but important: it should keep running the same full
pytest command that we run locally before pushing.

Tier-1 dev loop:

    pytest tests/test_phase_7e.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def test_pytest_workflow_runs_on_push_and_pull_request():
    workflow = WORKFLOW.read_text()

    assert "on:" in workflow
    assert "push:" in workflow
    assert "pull_request:" in workflow


def test_pytest_workflow_uses_project_python_and_full_suite():
    workflow = WORKFLOW.read_text()

    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "cache-dependency-path: requirements.txt" in workflow
    assert "python -m pip install -r requirements.txt" in workflow
    assert "python -m pytest -q" in workflow
