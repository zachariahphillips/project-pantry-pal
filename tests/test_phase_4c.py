"""
Phase 4C regression suite — low-stock badge + filter chip.

Chunk C of Theme 4 introduces the concept of "low stock" for tracked
pantry items:

  - Definition: `quantity is not None AND quantity <= 1.0`
    Untracked items (quantity is None) NEVER qualify — by design,
    the user opts into low-stock tracking by entering a quantity.
  - Inline "Low" pill renders next to the qty on each qualifying card.
  - "Low (N)" filter chip joins the sort row inside _pantry_list.html.
  - Chip hidden when N=0 AND filter is not currently active.
  - URL param `?filter=low` composes with `?q=` and `?sort=`.
  - Add + delete mutations preserve the active filter via
    HX-Current-URL, same pattern as sort in Phase 4A.

These tests guard the rule, the badge, the chip, the URL composition,
and the empty-state copy that branches on (query, filter_key).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from tests.conftest import Client, sign_up

from app import (
    PANTRY_LOW_STOCK_THRESHOLD,
    _is_pantry_item_low,
    _normalize_pantry_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = "", unit: str = "",
                notes: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _item_block(html: str, name: str) -> str:
    """Extract a single pantry-item card from rendered HTML by name.
    Same helper pattern as Phase 4B — iterate all row ids and pick
    the one whose block contains the target name."""
    for match in re.finditer(
        r'id="pantry-item-\d+"(.*?)(?=id="pantry-item-|\Z)',
        html, re.DOTALL,
    ):
        if name in match.group(1):
            return match.group(0)
    return ""


def _names_in_order(html: str) -> list[str]:
    return re.findall(
        r'<p class="truncate text-sm font-medium text-stone-900">([^<]+)</p>',
        html,
    )


def _filter_chip_block(html: str) -> str:
    """Extract the FILTER region (None if absent — hidden state)."""
    match = re.search(
        r'<div [^>]*aria-label="Filter pantry"[^>]*>(.*?)</div>',
        html, re.DOTALL,
    )
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# 1. _is_pantry_item_low — the core rule
# ---------------------------------------------------------------------------

class TestLowStockRule:
    def test_tracked_item_at_or_below_threshold_is_low(self):
        """The exact rule: quantity ≤ PANTRY_LOW_STOCK_THRESHOLD AND
        quantity is not None. We use SimpleNamespace mocks here so
        the rule can be exercised without a DB session."""
        for qty in [0, 0.25, 0.5, 1.0, PANTRY_LOW_STOCK_THRESHOLD]:
            item = SimpleNamespace(quantity=qty)
            assert _is_pantry_item_low(item), (
                f"qty={qty} should be low (threshold is "
                f"{PANTRY_LOW_STOCK_THRESHOLD})"
            )

    def test_tracked_item_above_threshold_is_not_low(self):
        for qty in [1.1, 2, 6, 100]:
            item = SimpleNamespace(quantity=qty)
            assert not _is_pantry_item_low(item), (
                f"qty={qty} should NOT be low"
            )

    def test_untracked_item_is_never_low(self):
        """The defining product decision: untracked items (qty is None)
        skip the low-stock rule entirely. Locks down the answer to
        the 'low_definition' AskQuestion on 2026-06-30 — users opt in
        by entering a quantity."""
        item = SimpleNamespace(quantity=None)
        assert not _is_pantry_item_low(item), (
            "Untracked (qty=None) items must NEVER be flagged Low. "
            "If this fails, the rule regressed to treating None as 0."
        )

    def test_none_item_is_defensively_not_low(self):
        """A None item argument shouldn't crash the template."""
        assert _is_pantry_item_low(None) is False

    def test_negative_quantity_is_low(self):
        """Defensive — shouldn't happen via the form but a stale row
        with a negative qty should still register as low (it's
        certainly not 'high stock')."""
        item = SimpleNamespace(quantity=-1)
        assert _is_pantry_item_low(item) is True


# ---------------------------------------------------------------------------
# 2. _normalize_pantry_filter — URL coercion
# ---------------------------------------------------------------------------

class TestFilterNormalization:
    def test_low_normalizes_canonically(self):
        assert _normalize_pantry_filter("low") == "low"
        assert _normalize_pantry_filter("LOW") == "low"
        assert _normalize_pantry_filter("  Low  ") == "low"

    def test_unknown_filter_returns_empty(self):
        for raw in [None, "", "high", "bananas", "?", "low'); DROP"]:
            assert _normalize_pantry_filter(raw) == "", (
                f"Unknown filter {raw!r} should normalize to '' (off)"
            )


# ---------------------------------------------------------------------------
# 3. Badge rendering on item cards
# ---------------------------------------------------------------------------

class TestLowBadge:
    def test_badge_renders_on_low_item(self, client):
        """qty=1, no unit → low. Card should carry a red 'Low' pill."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Bananas")
        assert ">Low<" in block, (
            f"Bananas (qty=1) should show inline 'Low' pill. Block: "
            f"{block[:500]}"
        )
        # Red color palette confirms the badge styling (not a wrong-color regression)
        assert "text-red-700" in block

    def test_no_badge_when_qty_above_threshold(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", qty="12")
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Eggs")
        assert ">Low<" not in block, (
            "Eggs (qty=12) must NOT show the Low badge"
        )

    def test_no_badge_when_qty_unset(self, client):
        """The defining 4C product rule — untracked items (qty=null)
        never show the badge. This is the canary that catches a
        regression to "treat None as 0"."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Soy sauce")  # no qty entered → null in DB
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Soy sauce")
        assert ">Low<" not in block, (
            "Untracked item (no qty) MUST NOT show the Low badge — "
            "the chosen product rule excludes None qty from low-stock."
        )

    def test_badge_position_after_qty_before_notes(self, client):
        """Badge sits between qty and notes on the same line. Asserts
        the visual hierarchy: qty → Low → notes (the badge modifies
        the qty, notes are secondary info)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil", qty="1", unit="bottle",
                    notes="extra virgin")
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Olive oil")
        # qty text "1 bottle" precedes "Low" precedes "extra virgin"
        qty_pos = block.find("1 bottle")
        low_pos = block.find(">Low<")
        notes_pos = block.find("extra virgin")
        assert 0 < qty_pos < low_pos < notes_pos, (
            f"Expected qty < Low < notes ordering on card; got "
            f"qty@{qty_pos}, Low@{low_pos}, notes@{notes_pos}"
        )


# ---------------------------------------------------------------------------
# 4. Filter chip + URL composition
# ---------------------------------------------------------------------------

class TestFilterChip:
    def test_chip_hidden_when_no_low_items(self, client):
        """A healthy pantry (no low items) shows no Filter region.
        Zero-noise behavior matches the Phase 3D 'Add again' chip
        suppression logic."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", qty="12")
        html = client.get("/pantry").get_data(as_text=True)
        assert 'aria-label="Filter pantry"' not in html, (
            "Filter region should be HIDDEN when there are zero low "
            "items and the filter isn't active. Otherwise the user "
            "sees a meaningless 'Low (0)' chip."
        )

    def test_chip_visible_with_low_items(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        html = client.get("/pantry").get_data(as_text=True)
        block = _filter_chip_block(html)
        assert block, "Filter region must render when low items exist"
        assert "Low (1)" in block, (
            f"Chip label should read 'Low (1)' for 1 low item; "
            f"got: {block[:400]}"
        )

    def test_chip_count_reflects_multiple_low_items(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        _add_pantry(client, "Olive oil", qty="0.5")
        _add_pantry(client, "Eggs", qty="12")  # not low — should not count
        _add_pantry(client, "Soy sauce")  # untracked — should not count
        html = client.get("/pantry").get_data(as_text=True)
        block = _filter_chip_block(html)
        assert "Low (2)" in block, (
            f"Expected Low (2) — only the two tracked-and-≤1 items "
            f"should count. Untracked + qty>1 items must be excluded. "
            f"Got: {block[:400]}"
        )

    def test_filter_url_param_narrows_results(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        _add_pantry(client, "Olive oil", qty="0.5")
        _add_pantry(client, "Eggs", qty="12")
        names = _names_in_order(
            client.get("/pantry?filter=low").get_data(as_text=True),
        )
        assert set(names) == {"Bananas", "Olive oil"}, (
            f"?filter=low must show ONLY low items; got {names}"
        )

    def test_filter_composes_with_search(self, client):
        """Search + filter both narrow. Asking 'low items containing
        oil' returns the intersection."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil", qty="0.5")
        _add_pantry(client, "Bananas", qty="1")
        _add_pantry(client, "Coconut oil", qty="5")  # has "oil" but not low
        names = _names_in_order(
            client.get("/pantry?q=oil&filter=low").get_data(as_text=True),
        )
        assert names == ["Olive oil"], (
            f"q=oil & filter=low should yield only 'Olive oil'; got {names}"
        )

    def test_filter_composes_with_sort(self, client):
        """Filtered list still honors the active sort. A-Z within low
        items should put 'Bananas' before 'Olive oil'."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil", qty="0.5")
        _add_pantry(client, "Bananas", qty="1")
        names = _names_in_order(
            client.get("/pantry?filter=low&sort=name").get_data(as_text=True),
        )
        assert names == ["Bananas", "Olive oil"], (
            f"filter=low + sort=name should yield A-Z within low items; "
            f"got {names}"
        )

    def test_chip_count_respects_search(self, client):
        """The chip count is scoped to the current search so 'Low (N)'
        always equals the count the user would see if they tapped it.
        Otherwise tapping 'Low (5)' while search='milk' could yield
        0 results and feel broken."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        _add_pantry(client, "Olive oil", qty="0.5")
        _add_pantry(client, "Milk", qty="0.5")
        # No search → 3 low items total
        block = _filter_chip_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert "Low (3)" in block

        # With search 'milk' → only Milk matches, low count drops to 1
        block = _filter_chip_block(
            client.get("/pantry?q=milk").get_data(as_text=True),
        )
        assert "Low (1)" in block, (
            f"Chip count must reflect search scope so tapping yields "
            f"the displayed count. Got: {block[:400]}"
        )

    def test_chip_stays_visible_when_filter_active_even_at_zero(
        self, client,
    ):
        """If the user activates Low filter, then resolves their last
        low item, the chip stays visible (just showing 'Low (0)') so
        they can tap to deactivate. Hiding it would strand them in a
        filter state with no way out short of editing the URL."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")  # low
        # User searches for something with zero matches AND keeps filter on
        html = client.get(
            "/pantry?q=xyz_nomatch&filter=low",
        ).get_data(as_text=True)
        assert 'aria-label="Filter pantry"' in html, (
            "Filter region must stay visible while filter_key='low' "
            "even if the current scope shows zero low items — gives "
            "the user a tap-out path."
        )

    def test_chip_active_styling(self, client):
        """Active filter chip carries aria-pressed=true and the
        filled red treatment."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        html = client.get("/pantry?filter=low").get_data(as_text=True)
        block = _filter_chip_block(html)
        # The Low button should be aria-pressed=true with bg-red-700 fill
        low_button = re.search(
            r'<button[^>]*>\s*Low \(\d+\)\s*</button>',
            block, re.DOTALL,
        )
        assert low_button, "Low button missing from filter region"
        button_html = low_button.group(0)
        assert 'aria-pressed="true"' in button_html
        assert "bg-red-700" in button_html, (
            f"Active filter chip should have filled red fill; got: "
            f"{button_html[:300]}"
        )


# ---------------------------------------------------------------------------
# 5. Mutation preservation (the bug class _current_pantry_filter_from_request
#    guards against)
# ---------------------------------------------------------------------------

class TestFilterPreservation:
    def test_add_preserves_active_filter(self, client):
        """User is on /pantry?filter=low, adds a new item via the form.
        The htmx swap response must STILL be the filtered view, not
        silently flip back to the full list.

        The POST /pantry request has no `?filter=` of its own — the
        filter lives in HX-Current-URL only. Without
        _current_pantry_filter_from_request, this regresses."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", qty="12")  # not low
        _add_pantry(client, "Bananas", qty="1")  # low

        # Simulate the user being on /pantry?filter=low when they
        # submit the add form (with another low item).
        resp = client._c.post(
            "/pantry",
            data={
                "name": "Milk", "quantity": "0.5", "unit": "gal",
                "notes": "", "submit": "Add",
                "csrf_token": client._token or "",
            },
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?filter=low",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        names = _names_in_order(resp.get_data(as_text=True))
        assert "Eggs" not in names, (
            "Add must preserve filter=low across the swap — Eggs (qty=12) "
            "should NOT be in the filtered response."
        )
        assert set(names) == {"Bananas", "Milk"}, (
            f"Filter must retain across mutation; got {names}"
        )

    def test_delete_preserves_active_filter(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", qty="12")
        _add_pantry(client, "Bananas", qty="1")
        _add_pantry(client, "Olive oil", qty="0.5")

        # Find Bananas' id via the filtered view
        html = client.get("/pantry?filter=low").get_data(as_text=True)
        bananas_id = None
        for match in re.finditer(
            r'id="pantry-item-(\d+)"(.*?)(?=id="pantry-item-|\Z)',
            html, re.DOTALL,
        ):
            if "Bananas" in match.group(2):
                bananas_id = match.group(1)
                break
        assert bananas_id, "couldn't find Bananas row id"

        resp = client._c.delete(
            f"/pantry/{bananas_id}",
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?filter=low",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        names = _names_in_order(resp.get_data(as_text=True))
        assert names == ["Olive oil"], (
            f"After deleting Bananas under filter=low, only Olive oil "
            f"(other low item) should remain. Got: {names}"
        )
        # Eggs (qty=12) must not have leaked into the filtered view
        assert "Eggs" not in names


# ---------------------------------------------------------------------------
# 6. Empty state copy
# ---------------------------------------------------------------------------

class TestEmptyStateCopy:
    def test_filter_with_no_low_items_shows_celebratory_copy(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", qty="12")
        # No low items, but user activated the filter anyway
        html = client.get("/pantry?filter=low").get_data(as_text=True)
        assert "Nothing low-stock right now" in html, (
            "Empty state for active filter + no low items should "
            "say so explicitly, not the generic 'pantry is empty' copy."
        )

    def test_filter_plus_search_with_no_match_shows_combined_copy(
        self, client,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")
        # Filter is on, but search narrows to nothing
        html = client.get(
            "/pantry?q=xyz_nomatch&filter=low",
        ).get_data(as_text=True)
        assert "No low-stock items match" in html, (
            "Empty state when filter + search both narrow to zero "
            "should reflect BOTH constraints, not just the search."
        )

    def test_pure_search_empty_keeps_old_copy(self, client):
        """Regression guard: the existing 'No matches for X' empty
        state survives the 4C copy branching."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="6")  # not low
        html = client.get("/pantry?q=xyz_nomatch").get_data(as_text=True)
        assert 'No matches for "xyz_nomatch"' in html
