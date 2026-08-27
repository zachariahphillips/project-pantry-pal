"""
Phase 7J regression suite — deploy smoke runbook polish.

The smoke test covers real runtime shape outside pytest. Keep the runbook
commands and expected coverage visible in docs so they don't drift.

Tier-1 dev loop:

    pytest tests/test_phase_7j.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_local_and_https_smoke_commands():
    readme = (ROOT / "README.md").read_text()

    assert "### Post-deploy smoke check" in readme
    assert "DATABASE_URL=sqlite:////tmp/pantrypal-prod-smoke.sqlite3" in readme
    assert ".venv/bin/gunicorn --bind 127.0.0.1:8080" in readme
    assert ".venv/bin/python scripts/prod_smoke.py" in readme
    assert "BASE=https://<your-app>.fly.dev EXPECT_SECURE_COOKIES=1" in readme
    assert "Secure`, `HttpOnly`, and `SameSite=Lax" in readme


def test_prod_smoke_header_lists_expected_runtime_coverage():
    script = (ROOT / "scripts" / "prod_smoke.py").read_text()

    assert "Phase 7I secure cookie flags on HTTPS deploys" in script
    assert "Expected PASS coverage" in script
    assert "remember-me login" in script
    assert "hardened cookie flags" in script
