"""
Phase 7V regression suite — PythonAnywhere free deploy path.

The deploy target changed because the project's actual goals are "free, easy,
low touch, personal app." These tests make sure the README now leads with the
PythonAnywhere path, the WSGI template is safe for PythonAnywhere's hosting
model, the old Fly backup workflow cannot keep failing on a schedule, and the
SQLite WAL default can be disabled for PythonAnywhere's network filesystem.

Tier-1 dev loop:

    pytest tests/test_phase_7v.py -q
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app import SQLITE_DEFAULT_JOURNAL_MODE, create_app


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"
WSGI_TEMPLATE = ROOT / "pythonanywhere_wsgi.py.example"


def test_readme_promotes_pythonanywhere_as_the_no_cost_deploy_path():
    readme = README.read_text()

    assert "## Deploy to PythonAnywhere (Phase 7V)" in readme
    assert "recommended no-cost deploy target" in readme
    assert "free PythonAnywhere web app" in readme
    assert "Legacy Fly.io deploy" in readme
    assert "no longer the recommended no-cost path" in readme


def test_readme_documents_pythonanywhere_web_tab_setup():
    readme = README.read_text()

    assert "Manual configuration" in readme
    assert "/home/<your-pythonanywhere-username>/project-pantry-pal" in readme
    assert "/home/<your-pythonanywhere-username>/.virtualenvs/pantrypal" in readme
    assert "/var/www/<your-pythonanywhere-username>_pythonanywhere_com_wsgi.py" in readme
    assert "pythonanywhere_wsgi.py.example" in readme


def test_readme_documents_pythonanywhere_sqlite_and_backup_path():
    readme = README.read_text()

    assert "DATABASE_URL=sqlite:////home/<your-pythonanywhere-username>" in readme
    assert "SQLITE_JOURNAL_MODE=DELETE" in readme
    assert "PythonAnywhere Bash console" in readme
    assert "--source data/pantrypal.sqlite3" in readme
    assert "scripts/restore_drill.py backups/pantrypal-YYYYMMDDTHHMMSSZ.sqlite3" in readme


def test_pythonanywhere_wsgi_template_imports_application_without_running_server():
    template = WSGI_TEMPLATE.read_text()

    assert "PROJECT_DIR = Path(" in template
    assert "from app import app as application" in template
    assert "app.run(" not in template
    assert "FLASK_ENV" in template


def test_pythonanywhere_wsgi_template_sets_safe_sqlite_defaults():
    template = WSGI_TEMPLATE.read_text()

    assert "sqlite:///" in template
    assert "data' / 'pantrypal.sqlite3'" in template
    assert 'os.environ.setdefault("SQLITE_JOURNAL_MODE", "DELETE")' in template


def test_legacy_fly_backup_workflow_is_manual_only():
    workflow = WORKFLOW.read_text()
    readme = README.read_text()

    assert "name: Legacy Fly SQLite Backup" in workflow
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "legacy `.github/workflows/backup.yml` workflow is manual-only" in readme


def test_pythonanywhere_can_disable_sqlite_wal(tmp_path, monkeypatch):
    db_file = tmp_path / "pythonanywhere.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "DELETE")

    app = create_app()

    with app.app_context():
        from extensions import db

        journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()

    assert journal_mode.lower() == "delete"


def test_invalid_sqlite_journal_mode_keeps_default_wal(tmp_path, monkeypatch):
    db_file = tmp_path / "fallback.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "banana")

    app = create_app()

    with app.app_context():
        from extensions import db

        journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()

    assert journal_mode.lower() == SQLITE_DEFAULT_JOURNAL_MODE.lower()
