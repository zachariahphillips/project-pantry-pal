"""
Phase 3E regression suite — swipe-to-delete on shopping rows.

Chunk E adds a mobile swipe gesture that fires the existing DELETE
endpoint against a shopping item. The visible Delete button stays
in place; swipe is an additive accelerator, not a replacement.

Since pytest can't reliably simulate touch events, these tests cover
the DOM contract and the JS ships intact:
  1. Row structure — data-swipe-row wrapper preserves the stable id;
     inner data-swipe-content carries data-delete-url; affordance
     layer is present and aria-hidden.
  2. Backward compat — checkbox / Edit / Delete buttons still work
     the same way; existing selectors (`id="shopping-item-N"`) still
     locate items.
  3. Edit mode is swipe-free — swapping to the edit form must NOT
     carry a data-swipe-row (you don't want a mid-edit swipe to
     nuke the form).
  4. JS contract — the swipe script is present in shopping.html
     with the documented constants intact so future refactors that
     accidentally strip the block get caught.
  5. Delete URL correctness — data-delete-url matches the actual
     route the visible Delete button posts to, so the JS commit
     hits the same undo-eligible endpoint (Phase 3C wiring stays
     in play).
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_shopping(c: Client, name: str, qty: str = ""):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": qty, "unit": "", "notes": "",
        "submit": "Add",
    })


def _shopping_item_block(html: str, item_id: int) -> str:
    """Extract everything from the item's opening tag through the next
    item id (or end of string). Same pattern the existing 1c/2a tests
    use so we're consistent."""
    match = re.search(
        rf'id="shopping-item-{item_id}"(.*?)(?=id="shopping-item-|\Z)',
        html, re.DOTALL,
    )
    return match.group(0) if match else ""


def _first_shopping_id(html: str) -> int | None:
    m = re.search(r'id="shopping-item-(\d+)"', html)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# 1. Row structure — swipe scaffolding
# ---------------------------------------------------------------------------

class TestSwipeRowStructure:
    def test_row_wraps_content_in_swipe_row(self, client):
        """Each shopping item renders inside `[data-swipe-row]`. The
        outer div keeps its stable id (backward compat with tests
        1c/2a which locate items by `id="shopping-item-N"`)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        assert item_id is not None, "No shopping item found in response"
        block = _shopping_item_block(html, item_id)
        # The outer element must both carry the id AND advertise the
        # swipe hook.
        assert "data-swipe-row" in block, (
            "Shopping row outer wrapper must carry `data-swipe-row` so "
            "the swipe JS can find it via event delegation."
        )
        # The relative+overflow-hidden pair is essential — without them
        # the sliding content would extend past the card edge and
        # break the visual clip.
        assert "relative" in block, "Swipe wrapper must be relative"
        assert "overflow-hidden" in block, (
            "Swipe wrapper needs overflow-hidden so the sliding "
            "content is clipped to the card boundary"
        )

    def test_swipe_content_carries_delete_url(self, client):
        """The inner `[data-swipe-content]` div must carry
        `data-delete-url` — that's how the JS knows what endpoint
        to POST when a swipe commits. If this attribute goes missing,
        swipe-to-delete silently no-ops."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        assert "data-swipe-content" in block
        # Must reference the same delete endpoint as the visible button
        expected = f"/shopping/{item_id}"
        assert f'data-delete-url="{expected}"' in block, (
            f"Swipe delete URL missing or wrong — expected "
            f"data-delete-url=\"{expected}\""
        )

    def test_affordance_layer_present_and_hidden_from_at(self, client):
        """The red 'Delete' affordance layer sits behind the sliding
        content. It's aria-hidden so screen readers ignore the
        duplicate signal — the visible Delete button remains the
        canonical entry point for AT users."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        # There's exactly one affordance layer and it's aria-hidden.
        affordance_match = re.search(
            r'<div [^>]*data-swipe-affordance[^>]*>',
            block,
        )
        assert affordance_match, "Missing swipe affordance layer"
        aff_tag = affordance_match.group(0)
        assert 'aria-hidden="true"' in aff_tag, (
            "Affordance layer must be aria-hidden to avoid double-"
            "announcing Delete to screen readers."
        )
        # Should be non-interactive (pointer-events:none) so taps
        # in the visible white area of the row can't accidentally
        # dispatch on the red layer.
        assert "pointer-events-none" in aff_tag

    def test_delete_affordance_reads_delete(self, client):
        """The affordance label must say 'Delete' (uppercase or not
        — CSS handles case) so once revealed by a swipe the user has
        a clear signal about the impending action."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        # Isolate the affordance region — the outer Delete BUTTON
        # also contains the word Delete, so we scope by attribute.
        aff = re.search(
            r'<div [^>]*data-swipe-affordance[^>]*>(.*?)</div>',
            block, re.DOTALL,
        )
        assert aff, "Affordance region missing"
        assert "Delete" in aff.group(1), (
            "Affordance label must read 'Delete' when the row is "
            "swiped open. If this fails, someone renamed the label "
            "or removed the SPAN inside the affordance layer."
        )


# ---------------------------------------------------------------------------
# 2. Backward compat — existing controls untouched
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_id_still_locates_the_item(self, client):
        """The classic `id="shopping-item-N"` selector — used by
        tests/test_phase_1c.py, 2a.py, and countless htmx targets —
        still works. If this fails, the id moved off the outer div."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert re.search(r'id="shopping-item-\d+"', html), (
            "Shopping row is missing the stable id selector"
        )

    def test_checkbox_still_toggles(self, client):
        """The tap-to-check flow — Phase 1B — must survive the swipe
        wrapper restructure. Regression canary."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        # The checkbox must still POST to the toggle endpoint.
        assert f"/shopping/{item_id}/toggle" in block, (
            "Checkbox toggle endpoint missing — swipe wrapper broke "
            "the tap-to-check flow"
        )

    def test_visible_delete_button_still_present(self, client):
        """Chunk E's design decision: keep the Delete BUTTON visible
        even after adding swipe. Deleting the button in a future
        refactor is a scope decision, not a mechanical restructure —
        so make sure it hasn't happened accidentally."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        # An hx-delete button with the delete endpoint must still be
        # present inside data-swipe-content.
        content_match = re.search(
            r'data-swipe-content[^>]*>(.*?)(?=</div>\s*</div>\s*$)',
            block, re.DOTALL,
        )
        # Even if the greedy match above is imprecise, the block-level
        # assertion is enough to catch removal.
        assert (
            f'hx-delete="/shopping/{item_id}"' in block
        ), (
            "The visible Delete button is missing. Chunk E keeps it "
            "in place; swipe is additive. Removing it needs a "
            "separate product decision."
        )

    def test_edit_button_still_present(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)
        block = _shopping_item_block(html, item_id)
        assert f"/shopping/{item_id}/edit" in block, (
            "Edit button endpoint missing after swipe wrapper"
        )

    def test_delete_endpoint_still_works_end_to_end(self, client):
        """Highest-signal regression: swipe or no swipe, hitting DELETE
        against the item must still 200-and-remove it. Guards against
        wrapper changes breaking the actual delete path."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)

        resp = client.delete(f"/shopping/{item_id}", htmx=True)
        assert resp.status_code == 200
        # After delete, the item should be gone from the DOM.
        html_after = resp.get_data(as_text=True)
        assert f'id="shopping-item-{item_id}"' not in html_after, (
            "DELETE didn't remove the item from the swapped list"
        )


# ---------------------------------------------------------------------------
# 3. Edit mode is swipe-free
# ---------------------------------------------------------------------------

class TestEditModeNoSwipe:
    def test_edit_form_has_no_swipe_row(self, client):
        """When the user hits Edit, the row swaps to a form with the
        same id. That form must NOT be `data-swipe-row` — otherwise
        a mid-edit swipe would delete the item the user is editing."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        item_id = _first_shopping_id(html)

        edit_html = client.get(
            f"/shopping/{item_id}/edit", htmx=True,
        ).get_data(as_text=True)
        assert "data-swipe-row" not in edit_html, (
            "The edit form must not carry data-swipe-row — swipe "
            "during edit would nuke the item and lose the user's "
            "in-progress edits."
        )
        # Sanity: this is definitely the edit view
        assert 'hx-put=' in edit_html or 'hx-post=' in edit_html


# ---------------------------------------------------------------------------
# 4. JS contract — swipe script ships intact
# ---------------------------------------------------------------------------

class TestSwipeScriptContract:
    def test_shopping_page_ships_the_swipe_script(self, client):
        """The initShoppingSwipe IIFE must be present on /shopping.
        We check by function name rather than a code-shape match so
        formatting tweaks don't break the test."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert "initShoppingSwipe" in html, (
            "Swipe script IIFE not present on /shopping. If this "
            "fails, someone stripped or moved the <script> block "
            "in shopping.html."
        )

    def test_swipe_thresholds_documented_in_script(self, client):
        """Guardrail on the numeric contract. If a future refactor
        drops the SWIPE_THRESHOLD constant name entirely (say by
        inlining it as a magic number), we want to know because
        the constant is what makes the behavior tunable."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        for name in ("SWIPE_THRESHOLD", "MAX_SWIPE", "SCROLL_LOCK_DELTA"):
            assert name in html, (
                f"Swipe constant `{name}` missing from shopping.html. "
                f"Rename or inline it if intentional — then update this "
                f"assertion."
            )

    def test_swipe_script_targets_shopping_list(self, client):
        """The commit path must fire htmx.ajax with target=#shopping-list
        so the response swaps the whole list (including any undo
        toast the server emits). If the script targets something
        else, undo won't work."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        # Look inside a `htmx.ajax(...)` call for target: '#shopping-list'
        assert re.search(
            r"htmx\.ajax\([^)]*['\"]#shopping-list['\"]",
            html, re.DOTALL,
        ), (
            "Swipe commit must target #shopping-list so the swapped "
            "response drives the Phase 3C undo toast."
        )

    def test_swipe_script_hidden_on_other_pages(self, client):
        """Swipe JS is scoped to /shopping. If it ever leaked into
        /pantry or /meals it could get invoked on rows that don't
        share the swipe contract."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")  # Have something so /pantry
                                       # still returns a full page
        pantry = client.get("/pantry").get_data(as_text=True)
        assert "initShoppingSwipe" not in pantry, (
            "Swipe IIFE leaked into /pantry — it should live only "
            "in shopping.html"
        )
        meals = client.get("/meals").get_data(as_text=True)
        assert "initShoppingSwipe" not in meals, (
            "Swipe IIFE leaked into /meals — it should live only "
            "in shopping.html"
        )
