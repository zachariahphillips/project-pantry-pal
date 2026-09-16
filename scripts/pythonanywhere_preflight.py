"""
Phase 8B: PythonAnywhere preflight check.

Run this from the PythonAnywhere Bash console before pressing Reload in the Web
tab. It catches the easy-to-miss setup mistakes: missing `.env`, dev-mode Flask
settings, a placeholder secret key, a non-absolute SQLite URL, WAL-mode SQLite
on PythonAnywhere, and missing `data/` or `backups/` directories.

Usage:

    python scripts/pythonanywhere_preflight.py
    python scripts/pythonanywhere_preflight.py --create-dirs
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


DEFAULT_ENV_FILE = Path(".env")
DEFAULT_PROJECT_DIR = Path(".")
REQUIRED_DIRECTORIES = (Path("data"), Path("backups"))
PLACEHOLDER_SECRET_KEY = "dev-secret-change-me-in-env"
FALSEY_ENV_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class PreflightResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _is_falsey_env(value: str | None) -> bool:
    return _clean(value).lower() in FALSEY_ENV_VALUES


def _required_dirs(project_dir: Path) -> tuple[Path, ...]:
    return tuple(project_dir / rel for rel in REQUIRED_DIRECTORIES)


def validate_pythonanywhere_settings(
        settings: dict[str, str | None],
        *,
        project_dir: Path = DEFAULT_PROJECT_DIR,
) -> PreflightResult:
    errors: list[str] = []
    warnings: list[str] = []

    flask_env = _clean(settings.get("FLASK_ENV"))
    if flask_env != "production":
        errors.append("set FLASK_ENV=production in the server-side .env")

    if not _is_falsey_env(settings.get("FLASK_DEBUG")):
        errors.append("set FLASK_DEBUG=0 in the server-side .env")

    secret_key = _clean(settings.get("FLASK_SECRET_KEY"))
    if not secret_key or secret_key == PLACEHOLDER_SECRET_KEY:
        errors.append("set FLASK_SECRET_KEY to a generated secret, not the dev placeholder")
    elif len(secret_key) < 32:
        errors.append("FLASK_SECRET_KEY should be at least 32 characters")

    database_url = _clean(settings.get("DATABASE_URL"))
    if not database_url:
        errors.append("set DATABASE_URL to the absolute PythonAnywhere SQLite path")
    elif not database_url.startswith("sqlite:////"):
        errors.append("DATABASE_URL must use sqlite://// for an absolute SQLite path")
    elif "/data/pantrypal.sqlite3" not in database_url:
        errors.append("DATABASE_URL should point at the project data/pantrypal.sqlite3 file")

    journal_mode = _clean(settings.get("SQLITE_JOURNAL_MODE")).upper()
    if journal_mode != "DELETE":
        errors.append("set SQLITE_JOURNAL_MODE=DELETE for PythonAnywhere")

    if not _clean(settings.get("OPENAI_API_KEY")):
        warnings.append("OPENAI_API_KEY is empty; AI meal planning will be disabled")

    missing_dirs = [
        path for path in _required_dirs(project_dir.expanduser())
        if not path.is_dir()
    ]
    if missing_dirs:
        joined = ", ".join(str(path) for path in missing_dirs)
        errors.append(f"missing required directories: {joined}; run mkdir -p data backups")

    return PreflightResult(tuple(errors), tuple(warnings))


def run_preflight(
        *,
        env_file: Path = DEFAULT_ENV_FILE,
        project_dir: Path = DEFAULT_PROJECT_DIR,
        create_dirs: bool = False,
) -> PreflightResult:
    env_file = env_file.expanduser()
    project_dir = project_dir.expanduser()
    if create_dirs:
        for directory in _required_dirs(project_dir):
            directory.mkdir(parents=True, exist_ok=True)

    if not env_file.is_file():
        return PreflightResult(
            errors=(
                f"missing {env_file}; create the server-side .env from the README",
            ),
        )

    settings = dict(dotenv_values(env_file))
    return validate_pythonanywhere_settings(settings, project_dir=project_dir)


def print_result(result: PreflightResult) -> None:
    if result.ok:
        print("PythonAnywhere preflight OK.")
    else:
        print("PythonAnywhere preflight FAILED.")
        for error in result.errors:
            print(f"  [error] {error}")

    for warning in result.warnings:
        print(f"  [warning] {warning}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check PantryPal's PythonAnywhere deploy settings.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Path to the server-side .env file. Default: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=DEFAULT_PROJECT_DIR,
        help=f"Project directory to check. Default: {DEFAULT_PROJECT_DIR}",
    )
    parser.add_argument(
        "--create-dirs",
        action="store_true",
        help="Create data/ and backups/ before checking.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_preflight(
        env_file=args.env_file,
        project_dir=args.project_dir,
        create_dirs=args.create_dirs,
    )
    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
