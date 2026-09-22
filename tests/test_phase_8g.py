"""
Phase 8G regression suite — dark-mode real-device polish.

The 8F system dark-mode pass worked, but a phone-sized dark shopping screen
showed checked rows reading too dimly because the existing `opacity-60`
treatment stacked on a dark card. 8G gently raises that dimmed state in dark
mode while leaving the light-mode styling alone.

Tier-1 dev loop:

    npm run build:css
    pytest tests/test_phase_8g.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_INPUT = ROOT / "assets" / "css" / "app.css"
COMPILED_CSS = ROOT / "static" / "css" / "app.css"
README = ROOT / "README.md"
PLAN = ROOT / "PLAN.md"
AGENTS = ROOT / "AGENTS.md"
UX_PLAN = ROOT / "PLANS" / "ux-improvements-plan.md"


def test_dark_mode_checked_row_opacity_is_lifted_in_source_css():
    source = ASSET_INPUT.read_text()

    assert "@media (prefers-color-scheme: dark)" in source
    assert ".\\[\\&\\>\\*\\]\\:opacity-60 > *" in source
    assert "opacity: 0.72 !important;" in source


def test_dark_mode_checked_row_opacity_is_in_compiled_css():
    css = COMPILED_CSS.read_text()

    assert "@media (prefers-color-scheme:dark)" in css
    assert "\\[\\&\\>\\*\\]\\:opacity-60>*" in css
    assert "opacity:.72" in css


def test_phase_8g_docs_and_agent_test_count_are_current():
    readme = README.read_text()
    plan = PLAN.read_text()
    agents = AGENTS.read_text()
    ux_plan = UX_PLAN.read_text()

    assert "**Status:** Phase 8G current" in readme
    assert "dark-mode real-device polish" in readme
    assert "Full regression is **714 pytest tests** green" in readme
    assert "**Current status (Phase 8G" in plan
    assert "dark-mode real-device polish" in plan
    assert "full regression, 714 tests as of Phase 8G" in agents
    assert "- **Phase 8G:** Dark-mode real-device polish — current" in readme
    assert "Phase 8G" in ux_plan
