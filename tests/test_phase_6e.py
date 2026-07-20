"""
Phase 6E regression suite — checked-off shopping row visual bug fix.

Small bug-fix chunk from `PLANS/ux-improvements-plan.md` §0.1. Before
6E, checking off a shopping row painted the row as a pink/red block
with the word "Delete" visible under the checkbox and item name.

Root cause: the `data-swipe-row` outer wrapper renders TWO stacked
layers — a red `data-swipe-affordance` layer (fully opaque, painted
at rest) and a `data-swipe-content` layer above it (the actual row
UI, `bg-white`, `relative`). The affordance is normally invisible
because the content layer's white background occludes it.

Pre-6E, when a row was checked, the CSS applied `opacity-60` to the
outer `data-swipe-content` div. That reduces the ENTIRE stacking
context's alpha, including `bg-white`. Result: the red layer bled
through at 40%, and "Delete" text (the affordance's label) became
visible behind the row.

Fix: move the dim from the outer content wrapper onto its direct
children via Tailwind's `[&>*]:opacity-60` arbitrary variant. The
row background stays 100% opaque; only the checkbox / text /
action buttons dim. Same visual "checked-off" affordance for the
user, no red leak.

These tests guard:

  1. The outer `data-swipe-content` wrapper never carries the raw
     `opacity-60` class — that's the exact regression we're
     preventing. If a future refactor accidentally moves it back
     onto the wrapper, this test catches it.
  2. The child-scoped `[&>*]:opacity-60` variant IS present on
     checked rows and IS ABSENT on unchecked rows.
  3. The wrapper's `bg-white` background is unchanged on both
     states — the visual base of the row shouldn't flicker between
     checked and unchecked.
  4. Existing swipe scaffolding survives (data-swipe-row,
     data-swipe-content, data-delete-url) — this chunk is purely
     a Tailwind class swap on an existing element.

Tier-1 dev loop:

    pytest tests/test_phase_6e.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers — pattern-matched to test_phase_3e.py so grep-through-the-suite
# for shopping-row DOM assertions stays consistent.
# ---------------------------------------------------------------------------

def _add_shopping(c: Client, name: str, qty: str = ""):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": qty, "unit": "", "notes": "",
        "submit": "Add",
    })


def _first_shopping_id(html: str) -> int | None:
    m = re.search(r'id="shopping-item-(\d+)"', html)
    return int(m.group(1)) if m else None


def _swipe_content_opening_tag(html: str, item_id: int) -> str:
    """Extract JUST the opening tag of the `data-swipe-content` div for
    a given shopping item. All the class-name assertions in this suite
    live on this tag, and by scoping to it we avoid false positives
    from `opacity-60` / `bg-white` appearing on inner elements
    (e.g. the affordance layer's `text-white`, or a future child
    that legitimately needs its own opacity treatment).

    Regex care note: the fix from §0.1 introduces `[&>*]:opacity-60`,
    which contains a literal `>` inside a `class="..."` attribute
    value. That means we CAN'T use the usual `<div[^>]*>` trick to
    grab an opening tag — the `[^>]` would stop at that inner `>`
    and never reach the actual tag terminator. Instead we anchor on
    a well-known trailing attribute (`data-delete-url="/shopping/N"`)
    and use non-greedy matching."""
    row_pattern = (
        rf'id="shopping-item-{item_id}".*?'
        rf'(<div[^<]*?data-swipe-content[^<]*?'
        rf'data-delete-url="/shopping/{item_id}"[^<]*?>)'
    )
    match = re.search(row_pattern, html, re.DOTALL)
    assert match, (
        f"Could not locate data-swipe-content opening tag for "
        f"shopping-item-{item_id}"
    )
    return match.group(1)


# ---------------------------------------------------------------------------
# 1. Wrapper opacity — the exact regression we're preventing
# ---------------------------------------------------------------------------

class TestWrapperOpacity:
    def test_unchecked_wrapper_has_no_opacity_treatment(self, client):
        """An unchecked row has no dim treatment anywhere on the
        wrapper — no `opacity-60`, no `[&>*]:opacity-60`. Baseline
        for the checked-vs-unchecked contrast the next tests assert."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        tag = _swipe_content_opening_tag(html, item_id)
        assert "opacity-60" not in tag, (
            "Unchecked shopping rows must not carry any opacity dim "
            "on the swipe-content wrapper."
        )

    def test_checked_wrapper_uses_child_scoped_opacity(self, client, app):
        """The whole point of 6E — checked rows dim their CHILDREN,
        not the wrapper itself. `[&>*]:opacity-60` is the Tailwind
        arbitrary variant that targets direct children only, so the
        wrapper's own `bg-white` stays 100% opaque and continues to
        occlude the red affordance layer behind it."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")

        # Check the row off — same path a user takes tapping the
        # checkbox.
        body = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(body)
        client.post(f"/shopping/{item_id}/toggle", htmx=True)

        html = client.get("/shopping").get_data(as_text=True)
        tag = _swipe_content_opening_tag(html, item_id)
        assert "[&>*]:opacity-60" in tag, (
            "Checked shopping row must dim its CHILDREN via "
            "`[&>*]:opacity-60`, not its wrapper. This is the bug "
            "fix from PLANS/ux-improvements-plan.md §0.1."
        )

    def test_checked_wrapper_does_not_carry_raw_opacity_60(self, client, app):
        """The exact regression we're preventing. If a future
        refactor moves `opacity-60` back onto the swipe-content
        wrapper (either literally or via a Tailwind config that
        expands `[&>*]:opacity-60` to include the parent), the row's
        `bg-white` becomes 60% opaque and the red affordance bleeds
        through. This test locks the invariant in place."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")

        body = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(body)
        client.post(f"/shopping/{item_id}/toggle", htmx=True)

        html = client.get("/shopping").get_data(as_text=True)
        tag = _swipe_content_opening_tag(html, item_id)

        # We look for `opacity-60` as a STANDALONE class token
        # (surrounded by whitespace or a `"` at the class boundary)
        # so we don't false-positive on `[&>*]:opacity-60` which
        # legitimately contains the substring. Regex: opacity-60
        # preceded by whitespace or double-quote, followed by
        # whitespace or double-quote.
        standalone = re.search(r'(^|[\s"])opacity-60([\s"])', tag)
        assert not standalone, (
            f"Checked row's data-swipe-content wrapper must NOT carry "
            f"a bare `opacity-60` class — that's the exact bug from "
            f"PLANS/ux-improvements-plan.md §0.1 (red affordance "
            f"layer bleeds through at 40%). Found in tag: {tag}"
        )


# ---------------------------------------------------------------------------
# 2. Wrapper background — must stay opaque in both states
# ---------------------------------------------------------------------------

class TestWrapperBackground:
    def test_unchecked_wrapper_is_bg_white(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        tag = _swipe_content_opening_tag(html, item_id)
        assert "bg-white" in tag, (
            "Shopping row wrapper must carry `bg-white` so the "
            "red swipe affordance layer is occluded at rest."
        )

    def test_checked_wrapper_stays_bg_white(self, client, app):
        """The row's background base must not flicker between
        checked / unchecked. The dim treatment lives on the
        children now — the wrapper stays visually identical
        (bg-white + solid border) whether or not the row is
        checked. This preserves the row's structural integrity
        against the swipe affordance behind it."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")

        body = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(body)
        client.post(f"/shopping/{item_id}/toggle", htmx=True)

        html = client.get("/shopping").get_data(as_text=True)
        tag = _swipe_content_opening_tag(html, item_id)
        assert "bg-white" in tag, (
            "Checked shopping row wrapper must STILL carry `bg-white` "
            "— that's what occludes the red affordance layer. "
            "Reintroducing any transparency here reopens the bug."
        )


# ---------------------------------------------------------------------------
# 3. Backward compat — 3E swipe scaffolding survives 6E's class swap
# ---------------------------------------------------------------------------

class TestSwipeScaffoldingPreserved:
    def test_data_swipe_row_still_present(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert "data-swipe-row" in html

    def test_data_swipe_content_still_present(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert "data-swipe-content" in html

    def test_data_delete_url_still_present(self, client, app):
        """The swipe JS uses `data-delete-url` to fire the commit
        DELETE — untouched by 6E's class swap, but guard it here
        so any future refactor of this file surfaces the invariant."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        expected = f'data-delete-url="/shopping/{item_id}"'
        assert expected in html, (
            f"Swipe commit endpoint missing from row — "
            f"expected {expected}"
        )

    def test_affordance_layer_still_bg_red(self, client, app):
        """The red affordance layer stays fully painted at rest —
        6E doesn't change that. The fix is on the CONTENT layer
        occluding it, not on the affordance itself."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert 'data-swipe-affordance' in html
        # The affordance layer's opening tag carries bg-red-600 —
        # pull it out and check it wasn't accidentally dimmed too.
        affordance_match = re.search(
            r'(<div[^>]*data-swipe-affordance[^>]*>)', html,
        )
        assert affordance_match, "affordance layer opening tag missing"
        assert "bg-red-600" in affordance_match.group(1)
