"""
Phase 8F regression suite — system dark mode.

8F uses the compiled Tailwind stylesheet from 8E and follows the user's system
`prefers-color-scheme` setting. There is intentionally no manual toggle yet.

Tier-1 dev loop:

    npm run build:css
    pytest tests/test_phase_8f.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_INPUT = ROOT / "assets" / "css" / "app.css"
COMPILED_CSS = ROOT / "static" / "css" / "app.css"
TAILWIND_CONFIG = ROOT / "tailwind.config.js"
BASE_TEMPLATE = ROOT / "templates" / "base.html"
README = ROOT / "README.md"
PLAN = ROOT / "PLAN.md"
UX_PLAN = ROOT / "PLANS" / "ux-improvements-plan.md"


def test_tailwind_config_declares_system_dark_mode():
    config = TAILWIND_CONFIG.read_text()

    assert 'darkMode: "media"' in config


def test_css_entrypoint_defines_system_dark_mode_layer():
    source = ASSET_INPUT.read_text()

    assert "@media (prefers-color-scheme: dark)" in source
    assert "color-scheme: dark" in source
    assert "body {" in source
    assert ".bg-white" in source
    assert ".text-stone-950" in source
    assert ".supports-\\[backdrop-filter\\]\\:bg-white\\/80" in source
    assert "--tw-ring-color" in source


def test_compiled_css_contains_dark_mode_overrides():
    css = COMPILED_CSS.read_text()

    assert "@media (prefers-color-scheme:dark)" in css
    assert "color-scheme:dark" in css
    assert "body{background-color:#0c0a09;color:#f5f5f4}" in css
    assert ".bg-white,.bg-white\\/95{background-color:#1c1917}" in css
    for selector in (
        "text-stone-950",
        "text-stone-900",
        "text-stone-800",
        "text-stone-700",
    ):
        assert selector in css
    assert "color:#f5f5f4" in css
    assert "supports-\\[backdrop-filter\\]\\:bg-white\\/80" in css


def test_base_template_declares_light_and_dark_theme_colors():
    html = BASE_TEMPLATE.read_text()

    assert 'media="(prefers-color-scheme: light)"' in html
    assert 'media="(prefers-color-scheme: dark)"' in html
    assert 'content="#16a34a"' in html
    assert 'content="#0c0a09"' in html


def test_phase_8f_docs_mark_system_dark_mode_done():
    readme = README.read_text()
    plan = PLAN.read_text()
    ux_plan = UX_PLAN.read_text()

    assert "system dark mode" in readme
    assert "system dark mode" in plan
    assert "- **Phase 8F:** System dark mode — done" in readme
    assert "Shipped in Phase 8F" in ux_plan
