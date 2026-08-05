"""
Phase 6Q regression suite — nudge banner icon polish.

Small visual-polish chunk from `PLANS/ux-improvements-plan.md` §2.4.
The shared nudge banner used a radial spark/sun glyph that could be read
as a loading spinner. Nudges are static teaching signposts, so the icon
should read as a tip instead of in-flight work.

Tier-1 dev loop:

    pytest tests/test_phase_6q.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


OLD_RADIAL_SPARK_PATH = (
    "M10 2v3M10 15v3M2 10h3M15 10h3M4.6 4.6l2.1 2.1"
)
LIGHTBULB_PATH = (
    "M10 2.75a5 5 0 0 0-3 9c.55.37 1 .95 1 1.62V14h4v-.63"
)
LIGHTBULB_BASE_PATH = "M8 16h4M8.5 18h3"


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _seed_starter(c: Client):
    return c.post("/pantry/seed-starter", htmx=True, data={})


def _nudge_block(html: str, nudge_id: str) -> str:
    match = re.search(
        rf'(<div id="{re.escape(nudge_id)}"[\s\S]*?</div>)',
        html,
    )
    assert match, f"{nudge_id} not found"
    return match.group(1)


def test_planner_nudge_uses_static_lightbulb_icon(client: Client):
    sign_up(client, "nudge-icon@example.com", "Nudge Icon")
    _seed_starter(client)

    block = _nudge_block(_body(client.get("/pantry")), "nudge-planner")

    assert LIGHTBULB_PATH in block
    assert LIGHTBULB_BASE_PATH in block
    assert 'aria-hidden="true"' in block


def test_nudge_icon_retired_radial_spinner_like_glyph(client: Client):
    sign_up(client, "nudge-old@example.com", "Nudge Old")
    _seed_starter(client)

    block = _nudge_block(_body(client.get("/pantry")), "nudge-planner")

    assert OLD_RADIAL_SPARK_PATH not in block


def test_nudge_icon_has_no_motion_or_spinner_class(client: Client):
    """The nudge glyph is decorative, not an in-flight status indicator."""
    sign_up(client, "nudge-motion@example.com", "Nudge Motion")
    _seed_starter(client)

    block = _nudge_block(_body(client.get("/pantry")), "nudge-planner")

    assert "animate-" not in block
    assert "spin" not in block.lower()
    assert "spinner" not in block.lower()
