"""
Phase 9A regression suite — real-use beta readiness.

9A moves PantryPal from polished app to "ready to use for the household" by
turning the existing PythonAnywhere/preflight/backup tools into a concise
real-use beta checklist.

Tier-1 dev loop:

    pytest tests/test_phase_9a.py -q
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PLAN = ROOT / "PLAN.md"
AGENTS = ROOT / "AGENTS.md"


def _readme() -> str:
    return README.read_text()


def _beta_section() -> str:
    readme = _readme()
    match = re.search(
        r"### Real-use beta checklist \(Phase 9A\)([\s\S]*?)"
        r"\n### PythonAnywhere one-time setup",
        readme,
    )
    assert match, "Phase 9A real-use beta checklist section not found"
    return match.group(1)


def test_real_use_beta_checklist_is_near_pythonanywhere_happy_path():
    readme = _readme()

    assert "### PythonAnywhere happy-path checklist (Phase 8C)" in readme
    assert "### Real-use beta checklist (Phase 9A)" in readme
    assert readme.index("### PythonAnywhere happy-path checklist (Phase 8C)") < (
        readme.index("### Real-use beta checklist (Phase 9A)")
    )
    assert readme.index("### Real-use beta checklist (Phase 9A)") < (
        readme.index("### PythonAnywhere one-time setup")
    )


def test_real_use_beta_checklist_orders_safety_steps():
    section = _beta_section()

    assert section.index("Start clean") < section.index("Preflight PythonAnywhere")
    assert section.index("Preflight PythonAnywhere") < section.index("Reload and verify")
    assert section.index("Reload and verify") < section.index("Phone smoke")
    assert section.index("Phone smoke") < section.index("Protect the first real data")
    assert section.index("Protect the first real data") < section.index("Set the weekly habit")


def test_real_use_beta_checklist_includes_existing_phase_tools():
    section = _beta_section()

    assert "python -m pytest -q" in section
    assert "python scripts/pythonanywhere_preflight.py --create-dirs" in section
    assert ".venv/bin/python scripts/verify_pythonanywhere_deploy.py" in section
    assert "python scripts/backup_sqlite.py --verify --keep 14" in section
    assert ".venv/bin/python scripts/restore_drill.py backups/pantrypal-" in section
    assert "python scripts/backup_reminder.py --backup-dir backups --max-age-days 7" in section
    assert "only invite the household once it exits 0" in section


def test_phase_9a_docs_and_agent_test_count_are_current():
    readme = _readme()
    plan = PLAN.read_text()
    agents = AGENTS.read_text()

    assert "**Status:** Phase 9A current" in readme
    assert "real-use beta readiness checklist" in readme
    assert "Full regression is **718 pytest tests** green" in readme
    assert "**Current status (Phase 9A" in plan
    assert "real-use beta readiness checklist" in plan
    assert "full regression, 718 tests as of Phase 9A" in agents
    assert "- **Phase 9A:** Real-use beta readiness — current" in readme
