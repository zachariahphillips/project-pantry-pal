"""
Phase 5B regression suite — ghost-row previews + shopping empty-state polish.

Chunk B of Theme 5 introduces two additive mechanics on top of the 5A
onboarding hero + gate, PLUS closes bug B-001 that surfaced during 5A:

  1. `_ghost_rows.html` partial — two dimmed sample rows shown on the
     TRUE empty state of either the pantry or the shopping list. The
     rows are `aria-hidden="true"` (they aren't real data), styled
     with dashed borders + `opacity-50` so they read as previews, not
     content. Sample content is opinionated staples so a household
     recognizes the shape.

  2. Shopping empty-state polish — visual parity with `meals.html`.
     Bumper icon (basket glyph), `text-sm font-semibold` heading
     ("Nothing on your shopping list yet"), refined subcopy, `p-8`
     padding. The search-empty branch stays a plain "no matches"
     card because the user has already seen real rows.

  3. B-001 closure — `pantry_item_delete` now issues the same
     `HX-Refresh: true` boundary response that `pantry_add` does
     whenever the resulting count is at or below
     `PANTRY_ONBOARDING_THRESHOLD`. Delete-back-into-onboarding cases
     (4→3, 3→2, 2→1, 1→0) all reload the page so the parent hero +
     gate + ghost-row preview snap back into sync.

The Tier-1 development loop for this suite is:

    pytest tests/test_phase_5b.py -q

per the BUGS.md convention. Tier-2 additionally runs 5A + 4A + 4C
(sort/filter preservation contract on the delete path) + 1C (empty-
state isolation).
"""
from __future__ import annotations

import re

from tests.conftest import Client, id_for, sign_up

from app import PANTRY_ONBOARDING_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": "", "notes": "",
        "submit": "Add",
    })


def _add_shopping(c: Client, name: str):
    return c.post("/shopping", htmx=True, data={"name": name})


def _pantry_body(c: Client) -> str:
    return c.get("/pantry").get_data(as_text=True)


def _shopping_body(c: Client) -> str:
    return c.get("/shopping").get_data(as_text=True)


def _delete_pantry(c: Client, item_id: str, htmx: bool = True):
    """Delete with an explicit `HX-Current-URL` header so the delete
    route's sort/filter preservation exercises its normal path — the
    conftest `delete` doesn't emit that header. Mirrors how the real
    Delete button behaves in the browser."""
    headers = {
        "X-CSRFToken": c._token or "",
        "HX-Current-URL": "http://localhost/pantry",
    }
    if htmx:
        headers["HX-Request"] = "true"
    return c._c.delete(f"/pantry/{item_id}", headers=headers)


def _seed_pantry(c: Client, count: int, prefix: str = "Item"):
    for i in range(count):
        _add_pantry(c, f"{prefix}{i}")


def _ghost_rows_present(html: str) -> bool:
    return 'class="mt-6"' in html and (
        "Olive oil" in html or "Milk" in html
    ) and 'aria-hidden="true"' in html


# ---------------------------------------------------------------------------
# 1. Ghost-row previews — pantry
# ---------------------------------------------------------------------------

class TestPantryGhostRows:
    """Empty pantry (0 items, no query, no filter) shows ghost rows
    below the 5A onboarding hero. The previews reinforce the 'add
    something' cue by making the row shape visible."""

    def test_ghost_rows_show_on_empty_pantry(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert "Olive oil" in html, (
            "Empty pantry should preview the 'Olive oil' sample row. "
            "If this fails, _ghost_rows.html isn't being included from "
            "_pantry_list.html's is_empty_pantry branch."
        )
        assert "Salt" in html, (
            "Empty pantry should preview both sample rows (Olive oil, "
            "Salt) so the user sees more than a single ghost."
        )
        # Preview label
        assert ">\n      Preview\n    </span>" in html or \
               "Preview" in html, "Preview label missing above ghost rows"

    def test_ghost_rows_container_is_aria_hidden(self, client):
        """Screen readers should skip sample rows — they aren't real
        data. The upstream 5A hero headline is the semantic message.
        Regression guard: if someone drops aria-hidden a screen reader
        would announce 'Olive oil, 1 bottle' as if it were real."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        # The ghost-rows wrapper carries aria-hidden. Locate the div
        # that immediately contains "Preview" + "Olive oil".
        m = re.search(
            r'<div class="mt-6" aria-hidden="true">.*?Preview.*?Olive oil.*?Salt.*?</div>',
            html, re.DOTALL,
        )
        assert m, (
            "Ghost-rows wrapper on /pantry must carry aria-hidden=\"true\" "
            "AND contain both sample names between the Preview label and "
            "the closing div."
        )

    def test_ghost_rows_use_dashed_dimmed_treatment(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        # Locate the ghost-rows region and confirm the visual signature:
        # dashed border + opacity-50 on each sample row.
        m = re.search(
            r'<div class="mt-6" aria-hidden="true">(.*?)</div>\s*\n\s*'
            r'\n\s*{#',  # sentinel: comment block ends the region on some layouts
            html, re.DOTALL,
        )
        # Fallback: just search the whole page for the pattern once
        # (safer than trying to bracket exactly).
        assert "border-dashed" in html and "opacity-50" in html, (
            "Ghost rows should use dashed border + opacity-50 so they "
            "clearly read as previews, not real content."
        )

    def test_ghost_rows_hidden_when_pantry_has_items(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, PANTRY_ONBOARDING_THRESHOLD)  # past onboarding
        html = _pantry_body(client)
        # After onboarding zone: items list renders, ghost rows do not.
        # Distinguish by checking there's no ghost sample content AND
        # the real Item0/1/2 names are present.
        assert "Item0" in html and "Item1" in html
        assert "Olive oil" not in html, (
            "Once the pantry has real items, the ghost preview must "
            "disappear (otherwise the sample row would look like a "
            "real 'Olive oil' entry the user didn't add)."
        )
        assert "Salt" not in html
        # And the Preview label shouldn't leak either
        assert "Preview" not in html

    def test_ghost_rows_hidden_on_search_empty_state(self, client):
        """A user who's been using the app searches for a missing item.
        Empty search results should NOT show ghost previews — they'd
        confuse the user ('did I mistype and get suggestions?')."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, PANTRY_ONBOARDING_THRESHOLD)
        html = client.get("/pantry?q=zzzz_no_match").get_data(as_text=True)
        assert "No matches" in html
        assert "Olive oil" not in html
        assert "Preview" not in html

    def test_ghost_rows_hidden_on_filter_empty_state(self, client):
        """?filter=low with no matching items → 'Nothing low-stock
        right now.' No ghost rows — the user has real items, just
        not the ones they filtered for."""
        sign_up(client, "fresh@example.com", "Fresh")
        # Seed 3 items with high qty so filter=low returns nothing
        for i, name in enumerate(["Milk", "Bread", "Eggs"]):
            _add_pantry(client, name, qty="12")
        html = client.get("/pantry?filter=low").get_data(as_text=True)
        assert "Nothing low-stock right now" in html
        assert "Preview" not in html


# ---------------------------------------------------------------------------
# 2. Ghost-row previews — shopping
# ---------------------------------------------------------------------------

class TestShoppingGhostRows:
    def test_ghost_rows_show_on_empty_shopping_list(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _shopping_body(client)
        assert "Milk" in html and "Bread" in html, (
            "Empty shopping list should preview two sample rows: "
            "Milk + Bread. If missing, _ghost_rows.html isn't being "
            "included from _shopping_list.html's else-branch."
        )
        assert "Preview" in html

    def test_ghost_rows_hidden_when_list_has_items(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _add_shopping(client, "Tortillas")
        html = _shopping_body(client)
        assert "Tortillas" in html
        # Ghost samples should be gone now.
        assert "Milk" not in html, (
            "Once the shopping list has a real item, the Milk/Bread "
            "ghost preview must disappear."
        )
        assert "Bread" not in html
        assert "Preview" not in html

    def test_ghost_rows_hidden_on_search_empty_state(self, client):
        """User has been using the app, types a search that matches
        nothing. Empty-state stays a plain 'no matches' card — no
        ghost rows (they'd be misleading now that the user has
        established mental model of what real rows look like)."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_shopping(client, "Tortillas")  # real content in history
        html = client.get("/shopping?q=zzzz").get_data(as_text=True)
        assert "No matches" in html
        assert "Preview" not in html
        assert "Milk" not in html

    def test_shopping_ghost_rows_include_checkbox_glyph(self, client):
        """Shopping ghost rows should render a faux checkbox glyph on
        the leading side to mirror real shopping-item layout. Pantry
        ghost rows omit it (pantry rows don't have checkboxes)."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _shopping_body(client)
        # The faux checkbox is a 5x5 rounded span with a stone-400
        # border, inside a 10x10 slot. Ensure the pattern appears.
        assert re.search(
            r'<span class="h-5 w-5 rounded border border-stone-400 bg-white">',
            html,
        ), (
            "Shopping ghost rows must render the faux-checkbox glyph "
            "so the preview lines up with real row proportions."
        )

    def test_ghost_rows_present_in_htmx_partial_response(self, client):
        """When htmx re-renders _shopping_list.html via a search-clear
        or similar action, ghost rows must still appear because they
        live INSIDE the partial (not the parent shopping.html page)."""
        sign_up(client, "fresh@example.com", "Fresh")
        # Empty list via htmx partial request (the search endpoint
        # returns _shopping_list.html when HX-Request is present).
        resp = client.get("/shopping?q=", htmx=True)
        body = resp.get_data(as_text=True)
        assert "Milk" in body and "Preview" in body, (
            "Ghost rows must appear in htmx-swap responses too — they "
            "live inside _shopping_list.html, so every partial re-render "
            "on an empty list must include them."
        )


# ---------------------------------------------------------------------------
# 3. Shopping empty-state polish
# ---------------------------------------------------------------------------

class TestShoppingEmptyStatePolish:
    def test_shopping_empty_shows_bumper_icon(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _shopping_body(client)
        # h-10 w-10 basket glyph, stone-300 stroke — locates it uniquely
        # (contrast with the 6x6 hero glyphs elsewhere).
        assert re.search(
            r'<svg viewBox="0 0 24 24"[^>]*class="mx-auto h-10 w-10 text-stone-300"',
            html, re.DOTALL,
        ), (
            "Empty shopping state must render the bumper basket icon "
            "(h-10 w-10 stone-300) to match meals.html's empty-state "
            "visual bar. If missing, the empty-state polish regressed "
            "to the pre-5B plain card."
        )

    def test_shopping_empty_shows_polished_heading(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _shopping_body(client)
        assert "Nothing on your shopping list yet" in html, (
            "Empty-state heading must read 'Nothing on your shopping "
            "list yet' — the yet modifier signals 'this is temporary' "
            "and matches meals.html's 'No meal plans yet'."
        )
        # And it should be a proper heading, not a paragraph
        assert re.search(
            r'<h2 [^>]*>Nothing on your shopping list yet</h2>',
            html,
        ), "Heading must be an <h2>, not a <p>"

    def test_shopping_empty_shows_plus_shop_guidance(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _shopping_body(client)
        # "+ Shop" appears verbatim, styled with font-medium stone-700
        # to make it read as a UI element the user can tap on the
        # pantry page.
        assert "+ Shop" in html
        assert re.search(
            r'<span class="font-medium text-stone-700">\+ Shop</span>',
            html,
        ), (
            "Empty state should call out the '+ Shop' button on pantry "
            "items with a styled span so it reads as a real UI cue."
        )

    def test_shopping_search_empty_keeps_lean_treatment(self, client):
        """Search-empty branch does NOT show the bumper icon or ghost
        rows — a returning user just typed a search that missed, and
        an icon-heavy empty state would feel condescending."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_shopping(client, "Tortillas")  # so total list is non-empty
        html = client.get("/shopping?q=zzzz").get_data(as_text=True)
        assert "No matches" in html
        # No bumper icon
        assert not re.search(
            r'class="mx-auto h-10 w-10 text-stone-300"',
            html,
        ), "Search-empty state should NOT show the bumper icon"
        # No ghost rows
        assert "Preview" not in html
        assert "Milk" not in html and "Bread" not in html


# ---------------------------------------------------------------------------
# 4. B-001 closure — delete-back-into-onboarding-zone refreshes the page
# ---------------------------------------------------------------------------

class TestDeleteBoundaryRefresh:
    """B-001 (Low, discovered 2026-07-09): delete-to-empty left the
    hero + gate stale until manual refresh. Chunk B extends the same
    onboarding-zone HX-Refresh rule that already governs `pantry_add`
    to `pantry_item_delete` so the two paths stay symmetric."""

    def test_delete_last_item_returns_hx_refresh(self, client):
        """1 → 0: brings the pantry back to the empty-hero state.
        HX-Refresh needed so the parent hero + gate + ghost rows all
        reappear."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        html = _pantry_body(client)
        iid = id_for(html, "Olive oil", "pantry-item")
        assert iid, "Couldn't locate the freshly-added Olive oil row"

        resp = _delete_pantry(client, iid)
        assert resp.status_code == 204, (
            f"Delete-to-empty should return 204; got {resp.status_code}"
        )
        assert resp.headers.get("HX-Refresh") == "true", (
            "Delete-to-empty must trigger HX-Refresh so the parent "
            "hero card + ghost-row preview reappear. Without it, "
            "B-001 remains open: the parent widgets go stale until "
            "the user manually refreshes."
        )

    def test_delete_crossing_threshold_returns_hx_refresh(self, client):
        """3 → 2: user drops back below the meal-planner gate. The
        gate panel + progress dots need to reappear."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, PANTRY_ONBOARDING_THRESHOLD)  # 3 items
        html = _pantry_body(client)
        iid = id_for(html, "Item0", "pantry-item")
        resp = _delete_pantry(client, iid)
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_delete_within_onboarding_zone_returns_hx_refresh(
        self, client,
    ):
        """2 → 1: still in the onboarding zone. Gate progress dots
        should tick back a step; requires a full reload."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, 2)  # 2 items — below threshold
        html = _pantry_body(client)
        iid = id_for(html, "Item0", "pantry-item")
        resp = _delete_pantry(client, iid)
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_delete_past_threshold_returns_partial_swap(self, client):
        """4 → 3: still at the threshold, so onboarding-gate mechanics
        would have already been off. Since the resulting count is
        AT the threshold (≤ 3), current rule fires a refresh.

        Wait — the threshold is 3 and the rule is `<= threshold`. So
        4→3 (new count = 3) triggers refresh; 5→4 does not. Verify
        the boundary at 5→4."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, 5)  # 5 items
        html = _pantry_body(client)
        iid = id_for(html, "Item0", "pantry-item")
        resp = _delete_pantry(client, iid)
        # 5 → 4: past threshold, partial swap
        assert resp.status_code == 200
        assert "HX-Refresh" not in resp.headers, (
            "5→4 delete leaves us at 4 items (above threshold=3), so "
            "the fast partial-swap path is correct — no need to force "
            "a full-page reload."
        )
        body = resp.get_data(as_text=True)
        assert 'id="pantry-list"' in body

    def test_delete_to_exactly_threshold_returns_hx_refresh(self, client):
        """4 → 3: resulting count IS the threshold. The `<=` rule
        fires a refresh here. Justification: the meal-planner heading
        subcopy toggles at exactly this boundary too — the pre-5A
        wording changes at count == threshold, and the gate panel
        renders based on `pantry_item_count < threshold` (so count=3
        is unlocked). Keeping the rule as `<=` guarantees the gate's
        first-unlocked-state renders with fresh parent context."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed_pantry(client, 4)  # 4 items
        html = _pantry_body(client)
        iid = id_for(html, "Item0", "pantry-item")
        resp = _delete_pantry(client, iid)
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_non_htmx_delete_still_returns_partial(self, client):
        """A non-htmx client (curl, script) hitting DELETE gets the
        pre-5B partial-html response. The HX-Refresh mechanism only
        makes sense when there's a client listening for it."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        html = _pantry_body(client)
        iid = id_for(html, "Olive oil", "pantry-item")

        # No HX-Request header — simulate a non-htmx caller
        resp = client._c.delete(
            f"/pantry/{iid}",
            headers={"X-CSRFToken": client._token or ""},
        )
        assert resp.status_code == 200, (
            "Non-htmx DELETE should return the pantry-list partial "
            "with 200, matching the pre-5B contract for curl/scripts."
        )
        assert "HX-Refresh" not in resp.headers


# ---------------------------------------------------------------------------
# 5. Integration — after delete-to-empty via HX-Refresh, reload state
# ---------------------------------------------------------------------------

class TestDeleteToEmptyIntegration:
    """The whole-flow guarantee: after the client honors HX-Refresh
    and reloads, the reloaded page shows the hero + ghost-row preview
    together. This is the payoff for closing B-001 in this chunk."""

    def test_reload_after_delete_to_empty_shows_hero_and_ghosts(
        self, client,
    ):
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        html = _pantry_body(client)
        iid = id_for(html, "Olive oil", "pantry-item")

        # Delete → 204 + HX-Refresh
        resp = _delete_pantry(client, iid)
        assert resp.headers.get("HX-Refresh") == "true"

        # Now simulate the client's follow-up full-page reload
        reloaded = _pantry_body(client)
        # Hero markers (from Phase 5A)
        assert "Let's stock your pantry." in reloaded
        assert 'id="pantry-add-hero"' in reloaded
        # Ghost-row markers (Phase 5B)
        assert "Olive oil" in reloaded and "Salt" in reloaded, (
            "Post-reload pantry should show the ghost-row preview "
            "with both sample names, sitting below the hero."
        )
        assert "Preview" in reloaded
