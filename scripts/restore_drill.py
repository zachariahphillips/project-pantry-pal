"""
Prove a backup is restorable by actually restoring it.

Phase 7T verifies that a backup file is a well-formed PantryPal database, but
that is not the same claim as "the current code can serve traffic from it": a
schema that predates a model change passes an integrity check and still fails
to boot. This script closes that gap end to end -- verify the file, serve a
copy of it under gunicorn, and run the prod-shape smoke suite against it.

    .venv/bin/python scripts/restore_drill.py backups/pantrypal-backup.sqlite3

Exit code 0 means that backup is a usable restore point. Nothing touches the
backup file itself; gunicorn is always pointed at a throwaway copy, because
the smoke suite signs users up and would otherwise write into your restore
point.

Like scripts/prod_smoke.py this is deliberately not a pytest test -- it needs a
real gunicorn. tests/test_phase_7u.py covers the machinery around it.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# Importable both as `python scripts/restore_drill.py` (where sys.path[0] is
# scripts/) and as `from scripts.restore_drill import ...` under pytest.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_sqlite import BackupVerificationError, verify_backup

DEFAULT_READY_TIMEOUT_SECONDS = 30.0
HEALTHZ_PATH = "/healthz"
SMOKE_SCRIPT = ROOT / "scripts" / "prod_smoke.py"
TERMINATE_GRACE_SECONDS = 10.0


class DrillError(RuntimeError):
    """The drill could not be completed (as distinct from a failing check)."""


def sqlite_url_for_path(db_path: Path) -> str:
    """Build an absolute SQLite URL.

    Four slashes, not three: three is relative to Flask's instance folder,
    which would silently serve a different database than the one we restored.
    See the README's Phase 2C notes and tests/test_phase_2c.py.
    """
    return f"sqlite:///{Path(db_path).expanduser().resolve()}"


def pick_free_port() -> int:
    """Ask the kernel for an unused port so drills don't collide with 5001/8080."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _default_gunicorn_bin() -> str:
    alongside_python = Path(sys.executable).with_name("gunicorn")
    if alongside_python.exists():
        return str(alongside_python)
    found = shutil.which("gunicorn")
    if found is None:
        raise DrillError(
            "gunicorn not found; run this with the venv interpreter "
            "(.venv/bin/python scripts/restore_drill.py ...)"
        )
    return found


def build_gunicorn_command(port: int, *, gunicorn_bin: str | None = None) -> list[str]:
    """Mirror the Dockerfile so the drill exercises the real prod WSGI shape."""
    return [
        gunicorn_bin or _default_gunicorn_bin(),
        "--bind", f"127.0.0.1:{port}",
        "--workers", "1",
        "--threads", "4",
        "--timeout", "60",
        "app:app",
    ]


def drill_environment(
        db_path: Path,
        *,
        base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env["DATABASE_URL"] = sqlite_url_for_path(db_path)
    # A throwaway key: the drill's sessions must not outlive it.
    env["FLASK_SECRET_KEY"] = secrets.token_hex(32)
    # The restore runbook tells you to turn maintenance mode on, so an operator
    # mid-restore plausibly has it exported. Left set, every smoke check would
    # hit the maintenance page and the drill would prove nothing.
    env.pop("MAINTENANCE_MODE", None)
    env.pop("MAINTENANCE_MESSAGE", None)
    return env


def _fetch_status(url: str, timeout: float = 2.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except OSError:
        return None


def wait_for_healthz(
        base_url: str,
        *,
        is_alive: Callable[[], bool],
        timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
        fetch: Callable[[str], int | None] = _fetch_status,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
) -> None:
    """Block until the restored app answers /healthz, or explain why it never did."""
    url = f"{base_url}{HEALTHZ_PATH}"
    deadline = now() + timeout
    while now() < deadline:
        if not is_alive():
            raise DrillError(
                "gunicorn exited before it answered /healthz -- the restored "
                "database is probably not loadable by this version of the app"
            )
        if fetch(url) == 200:
            return
        sleep(0.25)
    raise DrillError(f"timed out after {timeout:g}s waiting for {url}")


def _run_prod_smoke(base_url: str) -> int:
    return subprocess.call(
        [sys.executable, str(SMOKE_SCRIPT)],
        env={**os.environ, "BASE": base_url},
        cwd=str(ROOT),
    )


def _terminate(process) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=TERMINATE_GRACE_SECONDS)


def run_drill(
        backup_path: Path,
        *,
        port: int | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
        launch: Callable[..., object] | None = None,
        smoke: Callable[[str], int] | None = None,
        fetch: Callable[[str], int | None] = _fetch_status,
) -> int:
    launch = subprocess.Popen if launch is None else launch
    smoke = _run_prod_smoke if smoke is None else smoke

    backup_path = Path(backup_path).expanduser()
    table_names = verify_backup(backup_path)
    print(f"Verified {backup_path} ({len(table_names)} tables).", flush=True)

    port = pick_free_port() if port is None else port
    base_url = f"http://127.0.0.1:{port}"
    workdir = Path(tempfile.mkdtemp(prefix="pantrypal-restore-drill-"))
    db_path = workdir / "restore-drill.sqlite3"
    # Copy, never serve the backup in place: the smoke suite writes.
    shutil.copy2(backup_path, db_path)

    process = None
    try:
        print(f"Serving a copy under gunicorn on {base_url} ...", flush=True)
        process = launch(
            build_gunicorn_command(port),
            env=drill_environment(db_path),
            cwd=str(ROOT),
        )
        wait_for_healthz(
            base_url,
            is_alive=lambda: process.poll() is None,
            timeout=ready_timeout,
            fetch=fetch,
        )
        print("Restored app is up. Running prod-shape smoke checks:\n", flush=True)
        exit_code = int(smoke(base_url))
        print()
        if exit_code == 0:
            print(
                f"RESTORE DRILL PASSED -- {backup_path} is a usable restore point.",
                flush=True,
            )
        else:
            print(
                f"RESTORE DRILL FAILED -- smoke checks exited {exit_code}. "
                "The file is a valid database but this code cannot serve it.",
                flush=True,
            )
        return exit_code
    finally:
        _terminate(process)
        shutil.rmtree(workdir, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore a backup into a throwaway app and smoke-test it.",
    )
    parser.add_argument("backup", type=Path, help="Backup file to drill.")
    parser.add_argument(
        "--port",
        type=int,
        help="Port for the drill's gunicorn. Default: an unused one.",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=DEFAULT_READY_TIMEOUT_SECONDS,
        help=(
            "Seconds to wait for /healthz before giving up. "
            f"Default: {DEFAULT_READY_TIMEOUT_SECONDS:g}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_drill(
            args.backup,
            port=args.port,
            ready_timeout=args.ready_timeout,
        )
    except (BackupVerificationError, DrillError) as exc:
        print(f"RESTORE DRILL FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
