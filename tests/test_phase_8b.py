"""
Phase 8B regression suite — PythonAnywhere preflight.

Phase 8A made the backup defaults match PythonAnywhere. 8B simplifies the
deploy/redeploy routine one more step: run a preflight before pressing Reload
and catch the common no-cost-hosting mistakes while still in the Bash console.

Tier-1 dev loop:

    pytest tests/test_phase_8b.py -q
"""
from __future__ import annotations

from pathlib import Path

from scripts.pythonanywhere_preflight import (
    PLACEHOLDER_SECRET_KEY,
    main,
    run_preflight,
    validate_pythonanywhere_settings,
)


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _valid_settings() -> dict[str, str]:
    return {
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "0",
        "FLASK_SECRET_KEY": "x" * 64,
        "DATABASE_URL": (
            "sqlite:////home/username/project-pantry-pal/data/pantrypal.sqlite3"
        ),
        "SQLITE_JOURNAL_MODE": "DELETE",
        "OPENAI_API_KEY": "sk-test",
    }


def _write_env(path: Path, settings: dict[str, str]) -> Path:
    path.write_text("\n".join(f"{key}={value}" for key, value in settings.items()))
    return path


def test_valid_pythonanywhere_settings_pass_when_dirs_exist(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()

    result = validate_pythonanywhere_settings(
        _valid_settings(),
        project_dir=tmp_path,
    )

    assert result.ok is True
    assert result.errors == ()
    assert result.warnings == ()


def test_preflight_reports_common_pythonanywhere_misconfigurations(tmp_path):
    settings = _valid_settings() | {
        "FLASK_ENV": "development",
        "FLASK_DEBUG": "1",
        "FLASK_SECRET_KEY": PLACEHOLDER_SECRET_KEY,
        "DATABASE_URL": "sqlite:///relative.sqlite3",
        "SQLITE_JOURNAL_MODE": "WAL",
    }

    result = validate_pythonanywhere_settings(settings, project_dir=tmp_path)

    assert result.ok is False
    assert "set FLASK_ENV=production" in "\n".join(result.errors)
    assert "set FLASK_DEBUG=0" in "\n".join(result.errors)
    assert "not the dev placeholder" in "\n".join(result.errors)
    assert "sqlite:////" in "\n".join(result.errors)
    assert "SQLITE_JOURNAL_MODE=DELETE" in "\n".join(result.errors)
    assert "mkdir -p data backups" in "\n".join(result.errors)


def test_preflight_warns_but_passes_when_openai_key_is_missing(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    settings = _valid_settings()
    settings["OPENAI_API_KEY"] = ""

    result = validate_pythonanywhere_settings(settings, project_dir=tmp_path)

    assert result.ok is True
    assert result.errors == ()
    assert result.warnings == (
        "OPENAI_API_KEY is empty; AI meal planning will be disabled",
    )


def test_run_preflight_can_create_required_directories(tmp_path):
    env_file = _write_env(tmp_path / ".env", _valid_settings())

    result = run_preflight(
        env_file=env_file,
        project_dir=tmp_path,
        create_dirs=True,
    )

    assert result.ok is True
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "backups").is_dir()


def test_run_preflight_reports_missing_env_file(tmp_path):
    result = run_preflight(env_file=tmp_path / ".env", project_dir=tmp_path)

    assert result.ok is False
    assert "missing" in result.errors[0]
    assert ".env" in result.errors[0]


def test_main_prints_errors_and_returns_nonzero(tmp_path, capsys):
    exit_code = main([
        "--env-file", str(tmp_path / ".env"),
        "--project-dir", str(tmp_path),
    ])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PythonAnywhere preflight FAILED" in captured.out
    assert "[error]" in captured.out


def test_main_prints_ok_for_valid_env(tmp_path, capsys):
    env_file = _write_env(tmp_path / ".env", _valid_settings())

    exit_code = main([
        "--env-file", str(env_file),
        "--project-dir", str(tmp_path),
        "--create-dirs",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PythonAnywhere preflight OK" in captured.out


def test_readme_documents_phase_8b_preflight():
    readme = README.read_text()

    assert "PythonAnywhere preflight (Phase 8B)" in readme
    assert "python scripts/pythonanywhere_preflight.py --create-dirs" in readme
    assert "FLASK_ENV=production" in readme
    assert "SQLITE_JOURNAL_MODE=DELETE" in readme
    assert "Before pressing Reload" in readme
