"""
Phase 4A regression suite — pantry sort selector.

Chunk A of Theme 4 adds three sort options (Newest / Oldest / A–Z)
to /pantry as a pill row above the items list. The sort key flows:

  - through `?sort=` on the URL (so reload + bookmark stick),
  - via the pill row's hx-get + hx-push-url for sort changes,
  - via the search input's hx-vals (reading window.location at
    request time) so a keystroke doesn't reset to Newest,
  - via the `HX-Current-URL` header for mutation routes (add, delete)
    that don't carry sort in their own URL.

These tests guard:
  1. Sort behavior — Newest (default), Oldest, A–Z (case-insensitive)
     all produce the right DOM order; unknown keys fall back; ties
     break deterministically.
  2. Search composition — sort + ?q= compose correctly.
  3. Sort preservation — add and delete via htmx preserve the
     current sort when the request carries `HX-Current-URL`.
  4. UI — pills render in the right active state, hidden on a
     brand-new empty pantry, present on search-with-zero-results.
"""
from __future__ import annotations

import re
import time

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = "", unit: str = "",
                notes: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _names_in_order(html: str) -> list[str]:
    """Extract the user-visible item names from rendered pantry HTML, in
    DOM order. We anchor on the `<p class="...">{{ item.name }}</p>`
    selector that pantry_item.html uses for the name; that's stable
    across density/timestamp work in later chunks of Theme 4."""
    return re.findall(
        r'<p class="truncate text-sm font-medium text-stone-900">([^<]+)</p>',
        html,
    )


def _names_in_order_response(resp) -> list[str]:
    return _names_in_order(resp.get_data(as_text=True))


# ---------------------------------------------------------------------------
# 1. Sort behavior
# ---------------------------------------------------------------------------

class TestSortBehavior:
    def test_default_sort_is_newest(self, client):
        """No `?sort=` → most-recently-added at the top. Matches
        pre-Phase-4A behavior so the URL-clean entry point still feels
        right to existing users."""
        sign_up(client, "alice@example.com", "Alice")
        # Add in chronological order; sleep 10ms so added_at differs.
        for name in ["Apple", "Banana", "Cherry"]:
            _add_pantry(client, name)
            time.sleep(0.01)
        order = _names_in_order_response(client.get("/pantry"))
        assert order == ["Cherry", "Banana", "Apple"], (
            f"Newest-first should put Cherry on top; got {order}"
        )

    def test_oldest_sort_inverts(self, client):
        """`?sort=oldest` flips to earliest-added at the top — useful
        for finding "what's been sitting around"."""
        sign_up(client, "alice@example.com", "Alice")
        for name in ["Apple", "Banana", "Cherry"]:
            _add_pantry(client, name)
            time.sleep(0.01)
        order = _names_in_order_response(
            client.get("/pantry?sort=oldest"),
        )
        assert order == ["Apple", "Banana", "Cherry"], (
            f"Oldest-first should put Apple on top; got {order}"
        )

    def test_name_sort_is_case_insensitive(self, client):
        """`?sort=name` is A–Z, case-insensitive. SQLite collates with
        ASCII order by default ("Z" < "a"), so 'apple' would sort
        AFTER 'Banana' without the lower() coercion. This test exists
        to lock in the lower() wrap in _apply_pantry_sort.

        Order on disk: apple, Banana, cherry — all added in that order.
        Expected A–Z output: apple, Banana, cherry (regardless of case)."""
        sign_up(client, "alice@example.com", "Alice")
        for name in ["Banana", "apple", "cherry"]:  # mixed case
            _add_pantry(client, name)
            time.sleep(0.01)
        order = _names_in_order_response(
            client.get("/pantry?sort=name"),
        )
        assert order == ["apple", "Banana", "cherry"], (
            f"Case-insensitive A–Z should sort 'apple' before 'Banana'; "
            f"got {order}. If 'Banana' is first, the lower() wrap "
            f"in _apply_pantry_sort regressed."
        )

    def test_unknown_sort_key_falls_back_to_newest(self, client):
        """Defensive: a stale bookmark or URL tampering with
        `?sort=banana_score` must NOT 500. Normalize silently to the
        default and render."""
        sign_up(client, "alice@example.com", "Alice")
        for name in ["Apple", "Banana"]:
            _add_pantry(client, name)
            time.sleep(0.01)
        resp = client.get("/pantry?sort=banana_score")
        assert resp.status_code == 200, (
            f"Bad sort key should not error; got {resp.status_code}"
        )
        order = _names_in_order_response(resp)
        # Newest default → Banana on top
        assert order == ["Banana", "Apple"]

    def test_search_and_sort_compose(self, client):
        """`?q=` and `?sort=` are independent and combine. Search
        narrows the list to matching names; sort orders that subset."""
        sign_up(client, "alice@example.com", "Alice")
        # 3 items match "milk" (in different casings + insertion orders)
        for name in ["Milk", "Almond milk", "Whole milk"]:
            _add_pantry(client, name)
            time.sleep(0.01)
        _add_pantry(client, "Cheese")  # non-matching distractor

        # Search + name sort: only milk-matches, A–Z
        order = _names_in_order_response(
            client.get("/pantry?q=milk&sort=name"),
        )
        assert order == ["Almond milk", "Milk", "Whole milk"], (
            f"Search+sort should yield 3 milk items in A–Z order; "
            f"got {order}"
        )


# ---------------------------------------------------------------------------
# 2. Sort preservation across mutations (the bug that drove
# _current_pantry_sort_from_request)
# ---------------------------------------------------------------------------

class TestSortPreservation:
    def test_add_preserves_active_sort(self, client):
        """The user is sorted A–Z (URL: /pantry?sort=name). They add a
        new item via the form. The htmx swap re-renders the list — and
        it must STILL be A–Z, not silently flip back to Newest.

        Without `_current_pantry_sort_from_request` reading from
        `HX-Current-URL`, this regressed because the POST /pantry
        request has no `?sort=` of its own to inspect.

        Phase 5A note: seed 3 filler items with a "zzzz" prefix so the
        tested add is well past the onboarding threshold. Without this
        primer the third add would cross the meal-planner-gate
        boundary and return 204 HX-Refresh instead of the list
        partial we want to inspect. The filler items are filtered
        out of the order assertion so the tested subset (Apple,
        Banana, Cherry) still reads clean."""
        sign_up(client, "alice@example.com", "Alice")
        # Primer: get past the onboarding threshold before the tested
        # behavior. Names use a "zzzz" prefix so they sort after every
        # tested item, keeping the alphabetical assertion below tidy.
        for name in ["zzzz-primer-1", "zzzz-primer-2", "zzzz-primer-3"]:
            _add_pantry(client, name)
        for name in ["Banana", "Apple"]:
            _add_pantry(client, name)
            time.sleep(0.01)

        # Simulate the user being on /pantry?sort=name when they
        # submit the add form — htmx adds HX-Current-URL automatically.
        # We mimic it explicitly here since the test client doesn't.
        resp = client._c.post(
            "/pantry",
            data={
                "name": "Cherry", "quantity": "", "unit": "",
                "notes": "", "submit": "Add",
                "csrf_token": client._token or "",
            },
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?sort=name",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        order = _names_in_order_response(resp)
        # Strip the primer items — they exist only to bump past the
        # onboarding threshold, they're not part of what we're
        # asserting about here.
        order = [n for n in order if not n.startswith("zzzz-primer")]
        assert order == ["Apple", "Banana", "Cherry"], (
            f"Add must preserve A–Z sort across the swap; got {order}. "
            f"If it returns Newest order ['Cherry', 'Banana', 'Apple'], "
            f"_current_pantry_sort_from_request is not reading "
            f"HX-Current-URL correctly."
        )

    def test_delete_preserves_active_sort(self, client):
        """Same regression class as add — deleting must keep the
        list sorted the user's way.

        Phase 5B note: primer past the onboarding threshold so the
        tested delete stays on the partial-swap path (not the 204
        HX-Refresh path fired when the resulting count is at or below
        the threshold). Primer names use a 'zzzz' prefix so they sort
        AFTER the tested items in A–Z order and can be filtered out
        of the assertion cleanly."""
        sign_up(client, "alice@example.com", "Alice")
        # Primer past PANTRY_ONBOARDING_THRESHOLD so the tested delete
        # leaves > threshold items behind (partial-swap path).
        for name in ["zzzz-primer-1", "zzzz-primer-2", "zzzz-primer-3"]:
            _add_pantry(client, name)
        for name in ["Banana", "Apple", "Cherry"]:
            _add_pantry(client, name)
            time.sleep(0.01)

        # Find Banana's id from a sorted-by-name fetch. Iterate all
        # row ids and locate the one whose block contains "Banana" —
        # a single regex with `.*?` would lock onto the first row id
        # then greedily match across to the first "Banana" string,
        # returning the wrong id.
        html = client.get("/pantry?sort=name").get_data(as_text=True)
        banana_id = None
        for match in re.finditer(
            r'id="pantry-item-(\d+)"(.*?)(?=id="pantry-item-|\Z)',
            html, re.DOTALL,
        ):
            if "Banana" in match.group(2):
                banana_id = match.group(1)
                break
        assert banana_id is not None, "couldn't find Banana row id"

        resp = client._c.delete(
            f"/pantry/{banana_id}",
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?sort=name",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        order = _names_in_order_response(resp)
        # Filter out the primer items so the assertion reads clean.
        order = [n for n in order if not n.startswith("zzzz-primer")]
        assert order == ["Apple", "Cherry"], (
            f"Delete must preserve A–Z sort across the swap; got {order}"
        )

    def test_add_without_hx_current_url_falls_back_to_default(
        self, client,
    ):
        """If the htmx request somehow doesn't carry HX-Current-URL
        (a stripped proxy, an older htmx version), the swap must
        gracefully default to Newest rather than crash. Defensive
        guarantee from `_current_pantry_sort_from_request`.

        Phase 5A note: primer past the onboarding threshold so the
        tested add is a real partial swap (not a 204 HX-Refresh).
        Primer names use a "zzzz" prefix so they sort AFTER the
        tested items in Newest order and can be filtered out."""
        sign_up(client, "alice@example.com", "Alice")
        for name in ["zzzz-primer-1", "zzzz-primer-2", "zzzz-primer-3"]:
            _add_pantry(client, name)
        _add_pantry(client, "Apple")  # no HX-Current-URL via normal helper
        time.sleep(0.01)
        resp = _add_pantry(client, "Banana")
        # No HX-Current-URL header is sent by the conftest helper, so we
        # expect the response sorted Newest (the fallback) — Banana first.
        order = _names_in_order_response(resp)
        order = [n for n in order if not n.startswith("zzzz-primer")]
        assert order == ["Banana", "Apple"]


# ---------------------------------------------------------------------------
# 3. UI rendering
# ---------------------------------------------------------------------------

class TestSortPillUI:
    def _pill_block(self, html: str) -> str:
        """Extract just the Sort-pills section so we can assert on its
        markup without false positives elsewhere on the page."""
        match = re.search(
            r'<div [^>]*aria-label="Sort pantry"[^>]*>.*?</div>',
            html, re.DOTALL,
        )
        return match.group(0) if match else ""

    def test_pills_render_with_three_options(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Apple")
        block = self._pill_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert block, "Sort pill row should render when items exist"
        # All three labels present. Jinja's whitespace between tags
        # and label text makes a literal `>Newest<` brittle, so we
        # collapse whitespace before checking.
        compact = re.sub(r"\s+", " ", block)
        assert "> Newest <" in compact or ">Newest<" in compact, (
            f"Newest pill missing from sort row: {block[:300]}..."
        )
        assert "> Oldest <" in compact or ">Oldest<" in compact
        # A–Z uses an en-dash so the assertion uses the literal char.
        # Just check the label is present somewhere in the block.
        assert "A\u2013Z" in block

    def test_active_pill_is_highlighted(self, client):
        """Active pill carries `aria-pressed="true"` AND a distinct
        bg-stone-800 style class. Asserts on the accessible attribute
        (durable) plus the visual class (so a regression to "all pills
        look the same" gets caught)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Apple")

        block = self._pill_block(
            client.get("/pantry?sort=oldest").get_data(as_text=True),
        )
        # Find the Oldest button block specifically
        oldest_match = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Oldest\s*</button>',
            block, re.DOTALL,
        )
        assert oldest_match, "Oldest pill should exist as a button"
        assert oldest_match.group(1) == "true", (
            "With ?sort=oldest, the Oldest pill must be aria-pressed=true"
        )
        # And the active visual class lands on the same button
        oldest_button = re.search(
            r'<button[^>]*>\s*Oldest\s*</button>',
            block, re.DOTALL,
        ).group(0)
        assert "bg-stone-800" in oldest_button, (
            "Active pill should have the dark bg-stone-800 highlight"
        )

        # Inactive pills should be aria-pressed=false and lack the bg-stone-800
        newest_button = re.search(
            r'<button[^>]*>\s*Newest\s*</button>',
            block, re.DOTALL,
        ).group(0)
        assert 'aria-pressed="false"' in newest_button
        assert "bg-stone-800" not in newest_button, (
            "Inactive pills must NOT carry the active highlight class"
        )

    def test_pills_hidden_on_brand_new_empty_pantry(self, client):
        """No items, no query → no pills. Pills with nothing to sort
        are noise on first impression."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        assert 'aria-label="Sort pantry"' not in html, (
            "Empty-pantry first-run should not render sort pills"
        )

    def test_pills_visible_on_empty_search_results(self, client):
        """Search returning 0 matches still shows pills — gives the
        user a way to navigate (e.g. clear search + browse by name)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Apple")
        html = client.get("/pantry?q=xyz_no_match").get_data(as_text=True)
        assert 'aria-label="Sort pantry"' in html, (
            "Sort pills should still render even when search yields 0 "
            "results — they're navigation, not just decoration."
        )

    def test_pill_links_include_hx_push_url(self, client):
        """Tapping a pill MUST update window.location via hx-push-url so
        reloads + bookmarks stick AND the search input's hx-vals JS can
        read the active sort. Without push-url, the URL stays stale
        and the search input would fall back to default Newest."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Apple")
        block = self._pill_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert 'hx-push-url="true"' in block, (
            'Sort pills must carry hx-push-url="true" so the URL '
            'updates on tap. Without this, the URL falls out of sync '
            'with the active sort and downstream wiring breaks.'
        )

    def test_search_input_carries_sort_via_hx_vals(self, client):
        """Search input must include the current sort via hx-vals (JS
        reading window.location), otherwise a keystroke during a custom
        sort would silently reset to Newest."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Apple")
        html = client.get("/pantry").get_data(as_text=True)
        # The exact hx-vals expression is fragile if rewritten, but the
        # invariant is: the search input reads `sort` from the URL.
        assert 'hx-vals=' in html and "window.location" in html, (
            "Search input must read the active sort from window.location "
            "via hx-vals='js:...' so it composes with sort changes. "
            "Otherwise sort silently resets on every keystroke."
        )
