"""
Create a consistent SQLite backup using SQLite's online backup API.

Default paths match PantryPal's Fly deploy:

    python /app/scripts/backup_sqlite.py

Local usage:

    .venv/bin/python scripts/backup_sqlite.py \
        --source instance/pantrypal.sqlite3 \
        --dest-dir backups

GitHub Actions artifact capture:

    python /app/scripts/backup_sqlite.py --emit-base64
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
BASE64_BEGIN_MARKER = "BEGIN_PANTRYPAL_SQLITE_BACKUP_BASE64"
BASE64_END_MARKER = "END_PANTRYPAL_SQLITE_BACKUP_BASE64"
BASE64_CHUNK_SIZE = 57 * 1024


def timestamped_backup_path(
        dest_dir: Path,
        *,
        now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return dest_dir / f"{BACKUP_FILENAME_PREFIX}-{stamp}.sqlite3"


def _sqlite_readonly_uri(source: Path) -> str:
    resolved = source.expanduser().resolve()
    return f"file:{quote(str(resolved), safe='/')}?mode=ro"


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


def emit_backup_base64(backup_path: Path, output: TextIO = sys.stdout) -> None:
    print(BASE64_BEGIN_MARKER, file=output)
    with backup_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(BASE64_CHUNK_SIZE), b""):
            output.write(base64.b64encode(chunk).decode("ascii"))
            output.write("\n")
    print(BASE64_END_MARKER, file=output)


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dest = args.dest or timestamped_backup_path(args.dest_dir)
    backup_path = backup_sqlite(args.source, dest)
    if args.emit_base64:
        print(f"Created backup at {backup_path}", file=sys.stderr)
        emit_backup_base64(backup_path)
    else:
        print(backup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
