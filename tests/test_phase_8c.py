"""
Phase 8C regression suite — no-cost deploy runbook closeout.

Phases 7V-8B built the PythonAnywhere path a chunk at a time. 8C closes the
runbook loop by adding a short happy-path checklist at the top, then making the
legacy Fly material clearly ignorable unless old Fly volume data is needed.

Tier-1 dev loop:

    pytest tests/test_phase_8c.py -q
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _readme() -> str:
    return README.read_text()


def _happy_path_section() -> str:
    readme = _readme()
    match = re.search(
        r"### PythonAnywhere happy-path checklist \(Phase 8C\)([\s\S]*?)"
        r"\n### PythonAnywhere one-time setup",
        readme,
    )
    assert match, "Phase 8C happy-path checklist section not found"
    return match.group(1)


def test_pythonanywhere_happy_path_checklist_is_near_the_top():
    readme = _readme()

    assert "### PythonAnywhere happy-path checklist (Phase 8C)" in readme
    assert readme.index("### PythonAnywhere happy-path checklist (Phase 8C)") < (
        readme.index("### PythonAnywhere one-time setup")
    )


def test_pythonanywhere_happy_path_orders_the_operator_steps():
    section = _happy_path_section()

    assert section.index("Set up or update code") < section.index("Check config")
    assert section.index("Check config") < section.index("Reload")
    assert section.index("Reload") < section.index("Verify deploy")
    assert section.index("Verify deploy") < section.index("Check backups")


def test_pythonanywhere_happy_path_includes_the_phase_tools():
    section = _happy_path_section()

    assert "pip install -r requirements.txt" in section
    assert "python scripts/pythonanywhere_preflight.py --create-dirs" in section
    assert ".venv/bin/python scripts/verify_pythonanywhere_deploy.py" in section
    assert "python scripts/backup_reminder.py --backup-dir backups --max-age-days 7" in section
    assert "python scripts/backup_sqlite.py --verify --keep 14" in section


def test_legacy_fly_section_is_clearly_optional_for_pythonanywhere():
    readme = _readme()

    assert "If you are using PythonAnywhere" in readme
    assert "ignore the legacy Fly, Docker, and" in readme
    assert "GitHub Actions backup notes below" in readme
    assert "unless you need old Fly volume data" in readme
