"""
Phase 8E regression suite — Tailwind CLI build pipeline.

8E replaces the Tailwind CDN with a pinned local CLI build that emits a
committed static stylesheet. That keeps PythonAnywhere deploys simple while
removing the client-side Tailwind compiler and its white-flash delay.

Tier-1 dev loop:

    npm run build:css
    pytest tests/test_phase_8e.py -q
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_INPUT = ROOT / "assets" / "css" / "app.css"
COMPILED_CSS = ROOT / "static" / "css" / "app.css"
PACKAGE = ROOT / "package.json"
PACKAGE_LOCK = ROOT / "package-lock.json"
TAILWIND_CONFIG = ROOT / "tailwind.config.js"
BASE_TEMPLATE = ROOT / "templates" / "base.html"
MAINTENANCE_TEMPLATE = ROOT / "templates" / "maintenance.html"
README = ROOT / "README.md"
PLAN = ROOT / "PLAN.md"
AGENTS = ROOT / "AGENTS.md"
UX_PLAN = ROOT / "PLANS" / "ux-improvements-plan.md"


def test_runtime_templates_use_compiled_css_not_tailwind_cdn():
    base = BASE_TEMPLATE.read_text()
    maintenance = MAINTENANCE_TEMPLATE.read_text()

    assert "cdn.tailwindcss.com" not in base
    assert "cdn.tailwindcss.com" not in maintenance
    assert "css/app.css" in base
    assert "css/app.css" in maintenance


def test_package_scripts_pin_tailwind_cli_build():
    package = json.loads(PACKAGE.read_text())
    lock = json.loads(PACKAGE_LOCK.read_text())

    assert package["private"] is True
    assert package["scripts"]["build:css"] == (
        "tailwindcss -c tailwind.config.js -i ./assets/css/app.css "
        "-o ./static/css/app.css --minify"
    )
    assert package["scripts"]["watch:css"].endswith("--watch")
    assert package["devDependencies"]["tailwindcss"] == "3.4.17"
    assert lock["packages"][""]["devDependencies"]["tailwindcss"] == "3.4.17"


def test_tailwind_config_scans_templates_and_python_sources():
    config = TAILWIND_CONFIG.read_text()

    assert '"./templates/**/*.html"' in config
    assert '"./app.py"' in config
    assert '"./forms.py"' in config


def test_css_entrypoint_keeps_app_specific_helpers_in_tailwind_layers():
    source = ASSET_INPUT.read_text()

    assert "@tailwind base;" in source
    assert "@tailwind components;" in source
    assert "@tailwind utilities;" in source
    assert "visibility: hidden" in source
    assert ".htmx-added" in source
    assert ".tab-bar" in source
    assert "[data-unit-option][data-active]" in source


def test_compiled_css_contains_representative_generated_utilities():
    css = COMPILED_CSS.read_text()

    assert "tailwindcss v3.4.17" in css
    assert "body{visibility:hidden}" in css
    assert ".tab-bar{padding-bottom:env(safe-area-inset-bottom)}" in css
    assert ".rounded-2xl" in css
    assert "text-\\[0\\.98rem\\]" in css
    assert "supports-\\[backdrop-filter\\]\\:bg-white\\/80" in css
    assert "group-open\\:rotate-90" in css


def test_phase_8e_docs_and_agent_test_count_are_current():
    readme = README.read_text()
    plan = PLAN.read_text()
    agents = AGENTS.read_text()
    ux_plan = UX_PLAN.read_text()

    assert "**Status:** Phase 8E current" in readme
    assert "compiled Tailwind CSS build" in readme
    assert "Full regression is **706 pytest tests** green" in readme
    assert "**Current status (Phase 8E" in plan
    assert "compiled Tailwind CSS build" in plan
    assert "full regression, 706 tests as of Phase 8E" in agents
    assert "- **Phase 8E:** Tailwind build pipeline — current" in readme
    assert "Shipped in Phase 8E" in ux_plan
