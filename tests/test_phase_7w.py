"""
Phase 7W regression suite — header brand mark polish.

Small visual-polish chunk from `PLANS/ux-improvements-plan.md` §2.6.
The header's old "P PantryPal" treatment was serviceable but generic,
especially on signup/login screens where it is the only branded surface.
7W keeps the compact mobile header shape while replacing the plain letter
tile with an inline pantry-bag mark and a more intentional wordmark.

Tier-1 dev loop:

    pytest tests/test_phase_7w.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import Client


BASE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "base.html"
)


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _brand_block(html: str) -> str:
    match = re.search(
        r'(<a [^>]*aria-label="PantryPal home"[\s\S]*?</a>)',
        html,
    )
    assert match, "header brand link not found"
    return match.group(1)


def test_header_brand_keeps_home_link_and_accessible_name(client: Client):
    block = _brand_block(_body(client.get("/signup")))

    assert 'href="/"' in block
    assert 'aria-label="PantryPal home"' in block
    assert ">PantryPal<" in block


def test_header_brand_uses_distinctive_inline_pantry_mark(client: Client):
    block = _brand_block(_body(client.get("/signup")))

    assert 'aria-hidden="true"' in block
    assert "bg-gradient-to-br from-emerald-500 via-green-600 to-lime-600" in block
    assert "rounded-2xl" in block
    assert "<svg" in block
    assert "M7.25 8.25h9.5l-.65 10.25" in block
    assert "M10 12h4M10 15.5h3" in block


def test_header_wordmark_gets_product_descriptor(client: Client):
    block = _brand_block(_body(client.get("/signup")))

    assert "font-extrabold" in block
    assert "Pantry + meals" in block
    assert "uppercase" in block
    assert "tracking-[0.16em]" in block


def test_plain_letter_tile_mark_is_retired():
    src = BASE_TEMPLATE.read_text()

    assert (
        'h-9 w-9 items-center justify-center rounded-xl bg-green-600 '
        'text-base font-bold text-white">P</span>'
    ) not in src
