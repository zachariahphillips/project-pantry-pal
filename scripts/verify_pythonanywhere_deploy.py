"""
Phase 7X: one-command PythonAnywhere deploy verification.

This is a thin operator-friendly wrapper around scripts/prod_smoke.py. The
generic smoke script still supports local gunicorn and legacy Fly targets; this
wrapper is only for the PythonAnywhere happy path, so it insists on HTTPS and
always enables secure-cookie checks.

Usage:

    .venv/bin/python scripts/verify_pythonanywhere_deploy.py <username>
    .venv/bin/python scripts/verify_pythonanywhere_deploy.py \
        https://<username>.pythonanywhere.com

or:

    PYTHONANYWHERE_BASE=https://<username>.pythonanywhere.com \
        .venv/bin/python scripts/verify_pythonanywhere_deploy.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

# Importable both as `python scripts/verify_pythonanywhere_deploy.py` and as
# `from scripts.verify_pythonanywhere_deploy import ...` under pytest.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import prod_smoke


PYTHONANYWHERE_BASE_ENV = "PYTHONANYWHERE_BASE"


class DeployVerificationError(RuntimeError):
    """The deploy verifier could not start because its target is invalid."""


def normalize_base_url(raw_target: str) -> str:
    """Return a canonical HTTPS base URL for the deployed app.

    Operators can pass the full PythonAnywhere URL, the host, or just the
    username. We deliberately reject HTTP here because the point of the deploy
    verifier is to exercise production HTTPS cookie behavior too.
    """
    target = raw_target.strip().rstrip("/")
    if not target:
        raise DeployVerificationError(
            "missing target; pass <username> or set PYTHONANYWHERE_BASE"
        )

    if "://" not in target:
        if "." not in target:
            target = f"{target}.pythonanywhere.com"
        target = f"https://{target}"

    parsed = urlsplit(target)
    if parsed.scheme != "https":
        raise DeployVerificationError(
            f"PythonAnywhere deploy verification requires HTTPS, got {target!r}"
        )
    if not parsed.netloc:
        raise DeployVerificationError(f"target has no host: {target!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise DeployVerificationError(
            "pass only the deploy origin, for example "
            "https://<username>.pythonanywhere.com"
        )

    return f"https://{parsed.netloc}"


def target_from_args(args: argparse.Namespace) -> str:
    raw = args.target or os.environ.get(PYTHONANYWHERE_BASE_ENV, "")
    return normalize_base_url(raw)


def verify_deploy(
        base_url: str,
        *,
        smoke: Callable[[], int] = prod_smoke.main,
) -> int:
    """Point prod_smoke at the deploy and run the full HTTPS smoke suite."""
    normalized = normalize_base_url(base_url)
    prod_smoke.BASE = normalized
    prod_smoke.EXPECT_SECURE_COOKIES = True
    prod_smoke.COOKIE_JAR.clear()
    prod_smoke.LAST_RESPONSE_HEADERS.clear()

    print("Phase 7X PythonAnywhere deploy verification")
    print(f"  target: {normalized}")
    print("  secure cookie checks: enabled")
    print()
    return int(smoke())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PantryPal's HTTPS smoke suite against PythonAnywhere.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help=(
            "PythonAnywhere username, host, or https://<username>.pythonanywhere.com. "
            f"Defaults to ${PYTHONANYWHERE_BASE_ENV}."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return verify_deploy(target_from_args(args))
    except DeployVerificationError as exc:
        print(f"DEPLOY VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
