"""
Phase 6P regression suite — meal-planner cost pill polish.

Small visual-polish chunk from `PLANS/ux-improvements-plan.md` §2.3.
Before 6P, the quota indicator next to "Plan a meal" was a whisper-sized
`text-[11px]` span. Because it represents a daily AI budget, it should read
as an intentional budget indicator even before the amber/red warning states.

6P keeps the existing /cost fetch and color-state logic, but gives the
base pill a 12px text size plus subtle border/background treatment.

Tier-1 dev loop:

    pytest tests/test_phase_6p.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import Client, sign_up


PANTRY_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "pantry.html"
)


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _cost_pill_tag(html: str) -> str:
    match = re.search(r'(<span id="meal-plan-cost-pill"[^>]*>)', html)
    assert match, "cost pill span not found"
    return match.group(1)


def _pantry_source() -> str:
    return PANTRY_TEMPLATE.read_text()


def test_cost_pill_renders_as_budget_indicator(client: Client):
    """The quota indicator should look intentional even before warning colors."""
    sign_up(client, "costpill@example.com", "Cost Pill")

    tag = _cost_pill_tag(_body(client.get("/pantry")))

    for cls in (
        "whitespace-nowrap",
        "rounded-full",
        "border",
        "border-stone-200",
        "bg-stone-50",
        "px-2",
        "py-0.5",
        "text-xs",
        "tabular-nums",
    ):
        assert cls in tag


def test_cost_pill_old_whisper_size_is_retired(client: Client):
    sign_up(client, "costpill-old@example.com", "Cost Pill Old")

    tag = _cost_pill_tag(_body(client.get("/pantry")))

    assert "text-[11px]" not in tag


def test_cost_pill_color_transitions_are_preserved():
    """6P adds the shell, but the existing normal/low/exhausted colors stay."""
    src = _pantry_source()

    assert "text-stone-500" in src
    assert "text-amber-700" in src
    assert "text-red-700" in src
    assert "if (remaining === 0)        pill.classList.add('text-red-700');" in src
    assert "else if (remaining <= 3)    pill.classList.add('text-amber-700');" in src
    assert "else                        pill.classList.add('text-stone-500');" in src


def test_cost_pill_refresh_removes_prior_color_before_reapplying():
    """Repeated /cost refreshes should not accumulate stale color classes."""
    src = _pantry_source()

    assert re.search(
        r"pill\.classList\.remove\(\s*"
        r"'hidden', 'text-stone-500', 'text-amber-700', 'text-red-700'",
        src,
        re.DOTALL,
    )
