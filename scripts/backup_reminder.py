"""
Phase 7Y: remind the operator when manual PythonAnywhere backups are stale.

PythonAnywhere is intentionally low-touch and no-cost for PantryPal, which
means backups are manual. This helper is a tiny check you can run after deploys
or whenever you open a PythonAnywhere Bash console:

    python scripts/backup_reminder.py

Exit code 0 means the latest backup is recent enough. Exit code 1 means no
backup exists or the newest one is older than the threshold, and the output
prints the backup command to run next.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Importable both as `python scripts/backup_reminder.py` and as
# `from scripts.backup_reminder import ...` under pytest.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_sqlite import BACKUP_FILE_GLOB


DEFAULT_BACKUP_DIR = Path("backups")
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_SOURCE = Path("data/pantrypal.sqlite3")
DEFAULT_KEEP = 14


@dataclass(frozen=True)
class BackupReminderStatus:
    ok: bool
    message: str
    latest_backup: Path | None = None
    age_days: float | None = None


def backup_command(
        *,
        source: Path = DEFAULT_SOURCE,
        backup_dir: Path = DEFAULT_BACKUP_DIR,
        keep: int = DEFAULT_KEEP,
) -> str:
    return (
        "python scripts/backup_sqlite.py "
        f"--source {source} "
        f"--dest-dir {backup_dir} "
        "--verify "
        f"--keep {keep}"
    )


def latest_backup(backup_dir: Path) -> Path | None:
    candidates = [
        path for path in backup_dir.expanduser().glob(BACKUP_FILE_GLOB)
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def backup_reminder_status(
        backup_dir: Path = DEFAULT_BACKUP_DIR,
        *,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        now: datetime | None = None,
) -> BackupReminderStatus:
    if max_age_days < 1:
        raise ValueError("max_age_days must be at least 1")

    backup_dir = backup_dir.expanduser()
    newest = latest_backup(backup_dir)
    command = backup_command(backup_dir=backup_dir)
    if newest is None:
        return BackupReminderStatus(
            ok=False,
            message=(
                f"BACKUP REMINDER: no {BACKUP_FILE_GLOB} files found in "
                f"{backup_dir}. Run: {command}"
            ),
        )

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    modified = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    age_days = (now_utc - modified).total_seconds() / 86400
    if age_days > max_age_days:
        return BackupReminderStatus(
            ok=False,
            latest_backup=newest,
            age_days=age_days,
            message=(
                f"BACKUP REMINDER: latest backup {newest} is "
                f"{age_days:.1f} days old (limit: {max_age_days}). "
                f"Run: {command}"
            ),
        )

    return BackupReminderStatus(
        ok=True,
        latest_backup=newest,
        age_days=age_days,
        message=(
            f"Backup reminder OK: latest backup {newest} is "
            f"{age_days:.1f} days old (limit: {max_age_days})."
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Warn when PantryPal's latest SQLite backup is stale.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help=f"Directory containing {BACKUP_FILE_GLOB}. Default: {DEFAULT_BACKUP_DIR}",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Warn when the newest backup is older than this. Default: {DEFAULT_MAX_AGE_DAYS}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        status = backup_reminder_status(
            args.backup_dir,
            max_age_days=args.max_age_days,
        )
    except ValueError as exc:
        print(f"BACKUP REMINDER FAILED: {exc}", file=sys.stderr)
        return 2

    print(status.message)
    return 0 if status.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
