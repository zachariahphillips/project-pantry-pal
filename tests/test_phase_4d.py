"""
Phase 4D regression suite — pantry density toggle.

Chunk D of Theme 4 introduces a two-value density preference (roomy
vs compact) stored in the Flask session cookie. Roomy is the pre-4D
three-line layout; compact collapses qty/notes/attribution/time into
a single truncated meta line and tightens the card padding.

These tests guard:
  1. Default state — new user is Roomy; POST /pantry/density flips
     and persists the choice across requests.
  2. Session normalization — unknown session values silently fall
     back to the default so a stale/tampered cookie can't 500.
  3. Toggle route — POST accepts the target density, updates the
     session, returns the re-rendered list partial preserving the
     user's sort/filter/search context.
  4. Template layout — Roomy renders two paragraphs of meta info,
     Compact renders one truncated paragraph. Both preserve the
     Low pill, stale-age color, and attribution string. Padding
     shifts p-3 → p-2.
  5. UI wiring — toggle chip appears in the control row, carries
     the right hx-vals (posting the OPPOSITE density), and shows
     aria-pressed state that matches the current preference.
  6. Backward compat — 4A sort, 4B stale color, 4C low badge all
     continue to work in both densities.
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up

from app import (
    PANTRY_DENSITY_DEFAULT,
    PANTRY_DENSITY_OPTIONS,
    PANTRY_DENSITY_SESSION_KEY,
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
    """Extract a single pantry-item card block by item name."""
    for match in re.finditer(
        r'id="pantry-item-\d+"(.*?)(?=id="pantry-item-|\Z)',
        html, re.DOTALL,
    ):
        if name in match.group(1):
            return match.group(0)
    return ""


def _density_toggle_block(html: str) -> str:
    """The Pantry density labeled region (or "" if absent)."""
    match = re.search(
        r'<div [^>]*aria-label="Pantry density"[^>]*>(.*?)</div>',
        html, re.DOTALL,
    )
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# 1. Default state + session persistence
# ---------------------------------------------------------------------------

class TestDensityDefaultAndPersistence:
    def test_default_density_is_roomy(self, client):
        """A brand-new user sees the pre-4D Roomy layout. Locks in
        `PANTRY_DENSITY_DEFAULT = "roomy"`."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1", unit="gal")
        html = client.get("/pantry").get_data(as_text=True)
        block = _density_toggle_block(html)
        toggle = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Compact\s*</button>',
            block, re.DOTALL,
        )
        assert toggle, "Compact toggle button missing from density region"
        assert toggle.group(1) == "false", (
            "New users start in Roomy density; Compact toggle must be "
            "aria-pressed=false. If this fails, the default flipped "
            "to compact."
        )

    def test_toggle_route_flips_and_persists_session(self, client):
        """POST /pantry/density writes to the session; a subsequent GET
        /pantry sees the new value."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")

        # Flip to compact
        resp = client.post("/pantry/density", htmx=True, data={
            "density": "compact",
        })
        assert resp.status_code == 200

        # Verify the response reflects Compact
        block = _density_toggle_block(resp.get_data(as_text=True))
        toggle = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Compact\s*</button>',
            block, re.DOTALL,
        )
        assert toggle and toggle.group(1) == "true", (
            "After POST density=compact, the toggle should be pressed"
        )

        # A fresh GET must still see Compact — session persistence
        html = client.get("/pantry").get_data(as_text=True)
        toggle = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Compact\s*</button>',
            _density_toggle_block(html), re.DOTALL,
        )
        assert toggle and toggle.group(1) == "true", (
            "Density preference must survive across requests — it's "
            "stored in the session cookie. If this fails, the toggle "
            "route isn't writing to session."
        )

    def test_toggle_back_to_roomy(self, client):
        """Flipping back to roomy clears the pressed state."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        client.post("/pantry/density", htmx=True, data={"density": "compact"})
        resp = client.post("/pantry/density", htmx=True, data={
            "density": "roomy",
        })
        assert resp.status_code == 200
        toggle = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Compact\s*</button>',
            _density_toggle_block(resp.get_data(as_text=True)), re.DOTALL,
        )
        assert toggle and toggle.group(1) == "false"

    def test_unknown_session_value_falls_back_to_default(self, client):
        """A stale/tampered session value (e.g. from a future rename)
        must NOT 500 — silently normalize to the default. This is the
        canary for `_get_pantry_density` defensive fallback."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        # Inject a bogus session value directly
        with client._c.session_transaction() as sess:
            sess[PANTRY_DENSITY_SESSION_KEY] = "extra_dense_mode"
        # Should still render fine, falling back to Roomy
        resp = client.get("/pantry")
        assert resp.status_code == 200
        toggle = re.search(
            r'<button[^>]*aria-pressed="(true|false)"[^>]*>\s*Compact\s*</button>',
            _density_toggle_block(resp.get_data(as_text=True)), re.DOTALL,
        )
        assert toggle and toggle.group(1) == "false", (
            "Unknown session value 'extra_dense_mode' should render as "
            "the default (roomy). If pressed=true, the fallback broke."
        )

    def test_unknown_post_value_falls_back_to_default(self, client):
        """Same defensive story on the POST path — an unrecognized
        density value in the form gets normalized to the default
        rather than 500ing."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        resp = client.post("/pantry/density", htmx=True, data={
            "density": "banana_mode",
        })
        assert resp.status_code == 200
        # Session should now hold the default, not "banana_mode"
        with client._c.session_transaction() as sess:
            assert sess.get(PANTRY_DENSITY_SESSION_KEY) == PANTRY_DENSITY_DEFAULT

    def test_density_options_constant_shape(self):
        """Guard the constant so a future change (e.g. adding an
        'ultra-compact' option) has to also update the tests."""
        assert PANTRY_DENSITY_OPTIONS == {"roomy", "compact"}
        assert PANTRY_DENSITY_DEFAULT == "roomy"


# ---------------------------------------------------------------------------
# 2. Toggle route context preservation
# ---------------------------------------------------------------------------

class TestToggleContextPreservation:
    def test_toggle_preserves_sort(self, client):
        """User is sorted A–Z, flips density. The response must still
        be A–Z. HX-Current-URL carries the sort key."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas")
        _add_pantry(client, "Apple")

        resp = client._c.post(
            "/pantry/density",
            data={
                "density": "compact",
                "csrf_token": client._token or "",
            },
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?sort=name",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        # Sort key survives — Apple should come before Bananas (A-Z)
        html = resp.get_data(as_text=True)
        # Only care about the ORDER of names, not exact regex — grab both
        names = re.findall(
            r'<p class="truncate text-sm font-medium text-stone-900">([^<]+)</p>',
            html,
        )
        assert names == ["Apple", "Bananas"], (
            f"Density toggle must preserve sort=name via HX-Current-URL; "
            f"got {names}"
        )

    def test_toggle_preserves_filter(self, client):
        """User has ?filter=low active. Toggle density → response must
        STILL be filtered to low items."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bananas", qty="1")  # low
        _add_pantry(client, "Eggs", qty="12")  # not low

        resp = client._c.post(
            "/pantry/density",
            data={
                "density": "compact",
                "csrf_token": client._token or "",
            },
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?filter=low",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        names = re.findall(
            r'<p class="truncate text-sm font-medium text-stone-900">([^<]+)</p>',
            resp.get_data(as_text=True),
        )
        assert names == ["Bananas"], (
            f"Density toggle must preserve filter=low; got {names}. "
            f"Eggs should NOT appear in a filtered-to-low response."
        )

    def test_toggle_preserves_query(self, client):
        """User has ?q=milk active. Toggle density → response only
        shows milk-matching items."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        _add_pantry(client, "Almond milk", qty="1")
        _add_pantry(client, "Eggs", qty="12")

        resp = client._c.post(
            "/pantry/density",
            data={
                "density": "compact",
                "csrf_token": client._token or "",
            },
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://localhost/pantry?q=milk",
                "X-CSRFToken": client._token or "",
            },
        )
        assert resp.status_code == 200
        names = re.findall(
            r'<p class="truncate text-sm font-medium text-stone-900">([^<]+)</p>',
            resp.get_data(as_text=True),
        )
        assert "Eggs" not in names, (
            f"Density toggle must preserve q=milk; got {names}. "
            f"Eggs should NOT appear in a milk-searched response."
        )
        assert set(names) == {"Milk", "Almond milk"}


# ---------------------------------------------------------------------------
# 3. Compact card layout
# ---------------------------------------------------------------------------

class TestCompactLayout:
    def setup_method(self):
        self._client = None  # set per-test via _make_compact_client

    def _make_compact_client(self, client):
        """Sign up + flip to compact density. Returns the client."""
        sign_up(client, "alice@example.com", "Alice")
        client.post("/pantry/density", htmx=True, data={"density": "compact"})
        return client

    def test_compact_uses_tighter_padding(self, client):
        """Compact cards go from p-3 to p-2 (12px → 8px). The visual
        payoff of compact mode leans heavily on this smaller padding."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Milk", qty="1", unit="gal")
        html = c.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Milk")
        assert " p-2" in block, (
            f"Compact card should use p-2 padding; got: {block[:400]}"
        )
        assert " p-3" not in block, (
            "Compact card must NOT retain p-3 padding — the density "
            "conditional class regressed."
        )

    def test_compact_merges_qty_and_time_into_one_line(self, client):
        """The whole point: qty + Low + notes + attribution + time all
        collapse into a single truncated paragraph. Rather than counting
        <p> tags in a broadly-extracted block (which over-grabs into
        the household share card below the list), we check for the
        signature classes of the Compact meta line AND the ABSENCE of
        the Roomy separate-timestamp paragraph."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Milk", qty="1", unit="gal", notes="whole")
        html = c.get("/pantry").get_data(as_text=True)
        # The compact meta paragraph signature: `truncate` on the meta line
        assert re.search(
            r'<p class="mt-0\.5 truncate text-xs text-stone-500">',
            html,
        ), "Compact card must render its combined truncated meta paragraph"
        # The Roomy separate timestamp paragraph signature is
        # `<p class="mt-1 text-[11px] ...">added ...</p>` — must NOT
        # appear when compact is active.
        assert not re.search(
            r'<p class="mt-1 text-\[11px\][^"]*">', html,
        ), (
            "Compact card must NOT render the Roomy separate-timestamp "
            "paragraph. If this appears, the density conditional isn't "
            "gating the two layouts properly."
        )
        # Sanity check the content actually made it into the compact line
        assert ">1 gal<" in html
        assert ">whole<" in html or "whole" in html
        assert ">Low<" in html

    def test_compact_meta_line_uses_truncate_class(self, client):
        """`truncate` = single-line ellipsis. Locks in the design
        decision that long notes get clipped in compact mode rather
        than wrapping to a second line."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Milk", qty="1")
        html = c.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Milk")
        # The meta line should have `truncate` on the second <p>
        meta_p = re.search(
            r'<p class="mt-0\.5 truncate [^"]*"',
            block,
        )
        assert meta_p, (
            f"Compact meta line must use `truncate`; block: {block[:500]}"
        )

    def test_compact_preserves_low_badge(self, client):
        """The 4C Low pill still renders in compact mode — density
        just repackages the layout, doesn't hide info."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Bananas", qty="1")
        html = c.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Bananas")
        assert ">Low<" in block, (
            "Compact mode must still show the Low badge"
        )
        # And the red styling
        assert "text-red-700" in block

    def test_compact_preserves_time_element(self, client):
        """The 4B <time> element still renders — accessible datetime
        attribute survives the layout change."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Milk", qty="1")
        html = c.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Milk")
        assert "<time datetime=" in block, (
            "Compact mode must preserve the semantic <time> element"
        )

    def test_compact_preserves_added_wording(self, client):
        """Phase 4B compat: 'added Xh ago' wording still present."""
        c = self._make_compact_client(client)
        _add_pantry(c, "Milk", qty="1")
        html = c.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Milk")
        assert "added" in block
        # And either "just now" or an "Nm ago"/"Nh ago" phrase
        assert (
            "just now" in block or "m ago" in block or "h ago" in block
        ), f"Compact time text missing; got: {block[:500]}"


# ---------------------------------------------------------------------------
# 4. Roomy layout backward compatibility
# ---------------------------------------------------------------------------

class TestRoomyLayoutUnchanged:
    def test_roomy_retains_two_meta_paragraphs(self, client):
        """Roomy density (default) still uses the pre-4D layout —
        qty/notes on one <p>, timestamp on another. Same signature-
        based approach as the compact test: check for the presence of
        the Roomy separate-timestamp paragraph AND the absence of the
        Compact truncated meta line."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1", unit="gal", notes="whole")
        html = client.get("/pantry").get_data(as_text=True)
        # Roomy timestamp paragraph must be present
        assert re.search(
            r'<p class="mt-1 text-\[11px\][^"]*">', html,
        ), (
            "Roomy card must render its separate timestamp paragraph "
            "(class starts with 'mt-1 text-[11px]'). If missing, the "
            "density conditional broke the default layout."
        )
        # Compact-signature truncated meta paragraph must NOT appear
        assert not re.search(
            r'<p class="mt-0\.5 truncate text-xs text-stone-500">', html,
        ), (
            "Roomy card must NOT render the compact combined-meta "
            "paragraph — regressed the default layout."
        )

    def test_roomy_uses_p3_padding(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Milk")
        assert " p-3" in block, (
            f"Roomy card must retain p-3 padding; got: {block[:400]}"
        )


# ---------------------------------------------------------------------------
# 5. UI wiring — toggle button + control row
# ---------------------------------------------------------------------------

class TestDensityToggleUI:
    def test_toggle_hidden_on_empty_pantry(self, client):
        """No items, no query, no filter → control row hidden entirely,
        so the density toggle is also hidden. Nothing to make compact."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        assert 'aria-label="Pantry density"' not in html, (
            "Density toggle should be hidden on a brand-new empty "
            "pantry — the whole control row is suppressed."
        )

    def test_toggle_visible_with_items(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        html = client.get("/pantry").get_data(as_text=True)
        block = _density_toggle_block(html)
        assert block, "Density toggle should render when items exist"
        # Label is 'Compact' with a state indicator, not a verb toggling
        # between 'Compact'/'Roomy'
        assert ">\n          Compact\n        <" in block or \
               ">Compact<" in block or \
               "Compact" in block

    def test_toggle_hx_vals_targets_opposite_density(self, client):
        """Tapping the toggle posts the OPPOSITE of the current
        density. In Roomy (default), the button posts 'compact'; in
        Compact, it posts 'roomy'. This is the on/off toggle
        semantics."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        # Roomy state
        block = _density_toggle_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert '"density": "compact"' in block, (
            "In Roomy state, tapping the toggle should POST density=compact"
        )
        # Flip to compact
        client.post("/pantry/density", htmx=True, data={"density": "compact"})
        block = _density_toggle_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert '"density": "roomy"' in block, (
            "In Compact state, tapping the toggle should POST "
            "density=roomy (flip back)"
        )

    def test_toggle_uses_hx_post_not_hx_get(self, client):
        """The density mutation is a POST (session write), so the
        button must use hx-post — hx-get would 405."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        block = _density_toggle_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert "hx-post=" in block, (
            "Density toggle should use hx-post (session mutation)"
        )
        assert "hx-get=" not in block

    def test_toggle_targets_pantry_list_partial(self, client):
        """Response is the full _pantry_list.html partial, so the
        button must swap #pantry-list outerHTML."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", qty="1")
        block = _density_toggle_block(
            client.get("/pantry").get_data(as_text=True),
        )
        assert 'hx-target="#pantry-list"' in block
        assert 'hx-swap="outerHTML"' in block
