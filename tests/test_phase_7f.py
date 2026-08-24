"""
Phase 7F regression suite — PWA manifest + app icons.

The app should advertise enough install metadata for "Add to Home Screen"
to use the PantryPal name, theme color, and generated icons.

Tier-1 dev loop:

    pytest tests/test_phase_7f.py -q
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "static" / "site.webmanifest"
ICON_192 = ROOT / "static" / "icons" / "pantrypal-192.png"
ICON_512 = ROOT / "static" / "icons" / "pantrypal-512.png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def test_manifest_has_install_metadata_and_icons():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["name"] == "PantryPal"
    assert manifest["short_name"] == "PantryPal"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#16a34a"
    assert manifest["background_color"] == "#fafaf9"
    assert manifest["icons"] == [
        {
            "src": "/static/icons/pantrypal-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any maskable",
        },
        {
            "src": "/static/icons/pantrypal-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ]


def test_manifest_icon_files_exist_and_are_pngs():
    assert ICON_192.read_bytes().startswith(PNG_MAGIC)
    assert ICON_512.read_bytes().startswith(PNG_MAGIC)


def test_base_template_links_manifest_and_home_screen_icon(client):
    html = _body(client.get("/login"))

    assert 'rel="manifest" href="/static/site.webmanifest"' in html
    assert 'rel="apple-touch-icon" href="/static/icons/pantrypal-192.png"' in html
    assert 'name="theme-color" content="#16a34a"' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert 'name="apple-mobile-web-app-title" content="PantryPal"' in html
