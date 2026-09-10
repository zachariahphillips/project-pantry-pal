"""
Phase 7X regression suite — PythonAnywhere deploy verification.

Phase 7V documented PythonAnywhere as the new free deploy path. 7X makes the
post-deploy verification step harder to run incorrectly: use one wrapper
command, accept a username or full URL, force HTTPS, and always run the secure
cookie checks that matter on the deployed app.

Tier-1 dev loop:

    pytest tests/test_phase_7x.py -q
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import prod_smoke
from scripts.verify_pythonanywhere_deploy import (
    DeployVerificationError,
    normalize_base_url,
    target_from_args,
    verify_deploy,
)


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def test_normalize_base_url_accepts_pythonanywhere_username():
    assert normalize_base_url("ZachariahPhillips") == (
        "https://ZachariahPhillips.pythonanywhere.com"
    )


def test_normalize_base_url_accepts_full_https_origin():
    assert normalize_base_url("https://ZachariahPhillips.pythonanywhere.com/") == (
        "https://ZachariahPhillips.pythonanywhere.com"
    )


def test_normalize_base_url_rejects_http_targets():
    with pytest.raises(DeployVerificationError, match="requires HTTPS"):
        normalize_base_url("http://ZachariahPhillips.pythonanywhere.com")


def test_normalize_base_url_rejects_path_query_or_fragment():
    with pytest.raises(DeployVerificationError, match="deploy origin"):
        normalize_base_url("https://ZachariahPhillips.pythonanywhere.com/pantry")


def test_target_from_args_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv(
        "PYTHONANYWHERE_BASE",
        "https://ZachariahPhillips.pythonanywhere.com",
    )

    target = target_from_args(argparse.Namespace(target=None))

    assert target == "https://ZachariahPhillips.pythonanywhere.com"


def test_verify_deploy_configures_prod_smoke_for_https_cookie_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(prod_smoke, "BASE", "http://127.0.0.1:8080")
    monkeypatch.setattr(prod_smoke, "EXPECT_SECURE_COOKIES", False)

    exit_code = verify_deploy(
        "ZachariahPhillips",
        smoke=lambda: calls.append(
            (prod_smoke.BASE, prod_smoke.EXPECT_SECURE_COOKIES)
        ) or 0,
    )

    assert exit_code == 0
    assert calls == [("https://ZachariahPhillips.pythonanywhere.com", True)]


def test_readme_documents_the_phase_7x_verifier_command():
    readme = README.read_text()

    assert "PythonAnywhere deploy verification (Phase 7X)" in readme
    assert ".venv/bin/python scripts/verify_pythonanywhere_deploy.py" in readme
    assert (
        "PYTHONANYWHERE_BASE=https://<your-pythonanywhere-username>."
        "pythonanywhere.com"
    ) in readme
    assert "forces HTTPS and secure-cookie checks" in readme
