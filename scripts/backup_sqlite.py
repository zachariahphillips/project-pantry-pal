"""
Create a consistent SQLite backup using SQLite's online backup API.

Default paths match PantryPal's Fly deploy:

    python /app/scripts/backup_sqlite.py

Local usage:

    .venv/bin/python scripts/backup_sqlite.py \
        --source instance/pantrypal.sqlite3 \
        --dest-dir backups

GitHub Actions artifact capture:

    python /app/scripts/backup_sqlite.py --verify --emit-base64 --keep 14

Verify a backup file you already have (e.g. a decoded artifact):

    python scripts/backup_sqlite.py --verify-file pantrypal-backup.sqlite3
"""
from __future__ import annotations

import argparse
import base64
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO
from urllib.parse import quote


DEFAULT_SOURCE = Path("/data/pantrypal.sqlite3")
DEFAULT_DEST_DIR = Path("/data/backups")
BACKUP_FILENAME_PREFIX = "pantrypal"
BACKUP_FILE_GLOB = f"{BACKUP_FILENAME_PREFIX}-*.sqlite3"
BASE64_BEGIN_MARKER = "BEGIN_PANTRYPAL_SQLITE_BACKUP_BASE64"
BASE64_END_MARKER = "END_PANTRYPAL_SQLITE_BACKUP_BASE64"
BASE64_CHUNK_SIZE = 57 * 1024

# A required subset, deliberately not the full schema: verification should fail
# on "corrupt file" or "not a PantryPal database", not on "we added a table
# last week". An exact match would reject every artifact taken before a schema
# addition for as long as that artifact is still in retention.
REQUIRED_BACKUP_TABLES = ("households", "users", "pantry_items", "shopping_items")


class BackupVerificationError(RuntimeError):
    """A backup file is missing, empty, corrupt, or not a PantryPal database."""


def timestamped_backup_path(
        dest_dir: Path,
        *,
        now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return dest_dir / f"{BACKUP_FILENAME_PREFIX}-{stamp}.sqlite3"


def _sqlite_readonly_uri(source: Path) -> str:
    """Read a database that may have a live writer, e.g. the production file."""
    resolved = source.expanduser().resolve()
    return f"file:{quote(str(resolved), safe='/')}?mode=ro"


def _sqlite_immutable_uri(path: Path) -> str:
    """Read a *finished* database file that has no writer and no sidecars.

    `mode=ro` on its own cannot open a WAL-mode database unless a `-shm` file
    already exists, and a completed backup has none -- which made verification
    reject every real production backup (Phase 7K put prod in WAL mode).
    `immutable=1` promises SQLite the file cannot change, so it skips the
    WAL/shm machinery entirely.

    Only valid for a completed artifact. Pointing this at the live database
    would skip its `-wal` and silently read stale pages, so `backup_sqlite`
    deliberately keeps using `_sqlite_readonly_uri` instead.
    """
    resolved = path.expanduser().resolve()
    return f"file:{quote(str(resolved), safe='/')}?mode=ro&immutable=1"


def backup_sqlite(source: Path, dest: Path) -> Path:
    source = source.expanduser()
    dest = dest.expanduser()
    if not source.exists():
        raise FileNotFoundError(f"SQLite source database not found: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_sqlite_readonly_uri(source), uri=True) as src:
        with sqlite3.connect(dest) as dst:
            src.backup(dst)
    return dest


def verify_backup(
        backup_path: Path,
        *,
        required_tables: tuple[str, ...] = REQUIRED_BACKUP_TABLES,
) -> list[str]:
    """Confirm a backup file is a restorable PantryPal SQLite database.

    Returns the table names found. Raises BackupVerificationError with a
    human-readable reason on any failure, so callers can turn it into an exit
    code without picking apart sqlite3's exception types.
    """
    backup_path = backup_path.expanduser()
    if not backup_path.exists():
        raise BackupVerificationError(f"backup file not found: {backup_path}")
    if backup_path.stat().st_size == 0:
        raise BackupVerificationError(f"backup file is empty: {backup_path}")

    try:
        with sqlite3.connect(_sqlite_immutable_uri(backup_path), uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            table_names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError(
            f"backup file is not a readable SQLite database: {backup_path} ({exc})"
        ) from exc

    if integrity is None or integrity[0] != "ok":
        detail = "no result" if integrity is None else integrity[0]
        raise BackupVerificationError(
            f"PRAGMA integrity_check failed for {backup_path}: {detail}"
        )

    missing = sorted(set(required_tables) - table_names)
    if missing:
        raise BackupVerificationError(
            f"backup at {backup_path} is missing expected table(s): "
            f"{', '.join(missing)}"
        )

    return sorted(table_names)


def emit_backup_base64(backup_path: Path, output: TextIO | None = None) -> None:
    # Resolved at call time, not bound as a default: a default would freeze
    # whatever sys.stdout was at import, which silently writes past any later
    # redirection of the stream this protocol depends on.
    output = sys.stdout if output is None else output
    print(BASE64_BEGIN_MARKER, file=output)
    with backup_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(BASE64_CHUNK_SIZE), b""):
            output.write(base64.b64encode(chunk).decode("ascii"))
            output.write("\n")
    print(BASE64_END_MARKER, file=output)


def prune_old_backups(dest_dir: Path, keep: int) -> list[Path]:
    if keep < 0:
        raise ValueError("--keep must be zero or greater")

    candidates = [
        path for path in dest_dir.expanduser().glob(BACKUP_FILE_GLOB)
        if path.is_file()
    ]
    newest_first = sorted(
        candidates,
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    to_delete = newest_first[keep:]
    for path in to_delete:
        path.unlink()
    return to_delete


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a consistent SQLite backup.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"SQLite database to back up. Default: {DEFAULT_SOURCE}",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        help="Exact backup file to write. Overrides --dest-dir.",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=DEFAULT_DEST_DIR,
        help=f"Directory for timestamped backups. Default: {DEFAULT_DEST_DIR}",
    )
    parser.add_argument(
        "--emit-base64",
        action="store_true",
        help=(
            "After creating the backup, write it to stdout between markers "
            "as base64 for GitHub Actions artifact capture."
        ),
    )
    parser.add_argument(
        "--keep",
        type=int,
        help=(
            "After creating the backup, keep only the newest N "
            f"{BACKUP_FILE_GLOB} files in the backup directory."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "After creating the backup, run an integrity check and confirm "
            "the required tables are present. Exits non-zero without emitting "
            "or pruning anything if the check fails."
        ),
    )
    parser.add_argument(
        "--verify-file",
        type=Path,
        help=(
            "Verify an existing backup file, then exit. Skips creating a new "
            "backup; used to check an artifact after it is decoded."
        ),
    )
    return parser.parse_args(argv)


def _verify_or_report(backup_path: Path) -> bool:
    """Verify a backup, reporting on stderr so stdout stays base64-clean."""
    try:
        table_names = verify_backup(backup_path)
    except BackupVerificationError as exc:
        print(f"Backup verification FAILED: {exc}", file=sys.stderr)
        return False
    print(
        f"Backup verification passed for {backup_path} "
        f"({len(table_names)} tables)",
        file=sys.stderr,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.verify_file is not None:
        return 0 if _verify_or_report(args.verify_file) else 1

    dest = args.dest or timestamped_backup_path(args.dest_dir)
    backup_path = backup_sqlite(args.source, dest)

    # Before emitting or pruning: a bad backup should never reach the artifact
    # upload, and should never count toward --keep.
    if args.verify and not _verify_or_report(backup_path):
        return 1

    if args.emit_base64:
        print(f"Created backup at {backup_path}", file=sys.stderr)
        emit_backup_base64(backup_path)
    else:
        print(backup_path)
    if args.keep is not None:
        deleted = prune_old_backups(backup_path.parent, args.keep)
        print(f"Pruned {len(deleted)} old backup(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
