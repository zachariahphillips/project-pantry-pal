"""
Phase 3H regression suite — shopping quick-add bar.

Chunk A of Theme 3 (UX polish) restructures the /shopping add form
from a ~250px form-card (name + qty + unit + notes + a full-width
"Add to shopping list" button) into a single inline `[Item name]
[+]` bar with qty/unit/notes tucked behind a collapsible "More
details" expander. The route + ShoppingItemForm + model are
unchanged — these tests focus on the markup structure and the
expander behavior. End-to-end add/edit/delete flows are already
covered by test_phase_1c.py.
"""
from __future__ import annotations

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Quick-add bar structure
# ---------------------------------------------------------------------------

class TestQuickAddBar:
    def test_name_input_visible_by_default(self, client: Client):
        """The name input is the primary affordance and must be visible
        without any user interaction. We assert the textual placeholder
        we set in the template, which is the most fragile-to-regressions
        marker (it'd survive a class rename but not a structural revert)."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert 'placeholder="Add an item (e.g. tortillas)"' in body, (
            "Quick-add name input must be visible with the new placeholder."
        )

    def test_submit_button_is_icon_only_with_aria_label(self, client: Client):
        """Submit is icon-only ("+") — no visible text — so it relies on
        an aria-label for screen readers. Verify the aria-label is in
        place (accessibility regression would silently break voiceover).
        Also assert the old full-text button copy is gone, because that
        button is what got replaced by the icon."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert 'aria-label="Add to shopping list"' in body, (
            "Icon-only submit button must have an aria-label for "
            "screen-reader users."
        )
        # The full-width "Add to shopping list" TEXT button got replaced
        # by the icon. The aria-label still uses that phrase, but the
        # visible text inside a <button>...Add to shopping list...
        # </button> sequence should no longer appear.
        assert ">\n              Add to shopping list\n" not in body
        assert ">Add to shopping list<" not in body, (
            "The old full-width text button should be gone — replaced "
            "by the icon-only quick-add button."
        )

    def test_more_details_collapsed_by_default(self, client: Client):
        """The details element must exist (so qty/unit/notes are still
        SUBMITTABLE in the form body) but must NOT carry the `open`
        attribute — otherwise the page would render with the heavy
        full-form expanded, defeating the entire point of Chunk A."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert "<details " in body, "More-details expander is missing."
        assert "<details open" not in body, (
            "Details element must be collapsed by default — opening it "
            "by default re-introduces the pre-3H heavy form."
        )
        assert ">More details<" in body or ">More details</span>" in body, (
            "Summary text 'More details' must be present so users "
            "know how to access qty/unit/notes."
        )

    def test_qty_unit_notes_still_in_form(self, client: Client):
        """Critical regression check: collapsing the form behind details
        must NOT remove the qty/unit/notes inputs from the form. They
        stay in the DOM so a user who expands → fills out qty → hits
        Enter in the name field still submits qty in the POST body.

        We verify by looking for the WTForm-generated field names; the
        ShoppingItemForm gives us `quantity`, `unit`, `notes`."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert 'name="quantity"' in body, "Quantity field missing from form."
        assert 'name="unit"' in body, "Unit field missing from form."
        assert 'name="notes"' in body, "Notes field missing from form."

    def test_minimal_add_with_just_name_still_works(self, client: Client):
        """Smoke test the simplest add path through the new markup:
        the route accepts a POST with just `name` (no qty/unit/notes)
        and lands a row. End-to-end add behavior is covered exhaustively
        in test_phase_1c.py — this is just a guard that the form's
        backend contract didn't get broken by the template restructure."""
        sign_up(client, "alice@example.com", "Alice")
        resp = client.post(
            "/shopping",
            data={"name": "Milk", "quantity": "", "unit": "", "notes": ""},
            htmx=True,
        )
        assert resp.status_code == 200
        assert "Milk" in resp.get_data(as_text=True)

    def test_after_request_handler_resets_collapses_and_refocuses(
            self, client: Client):
        """The hx-on::after-request handler must do three things on
        success: reset() the form values, collapse the details element
        back to default, AND refocus the name input so the keyboard
        stays up on mobile for rapid-fire add. We can't actually drive
        a browser in pytest, so this is a markup assertion: each of the
        three behaviors must appear in the handler source so a future
        edit that drops one of them is caught."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        # Single hx-on::after-request handler on the form element.
        assert "hx-on::after-request" in body
        assert "this.reset()" in body, (
            "Handler must reset() the form so the next add starts "
            "from a blank state."
        )
        assert "det.open = false" in body, (
            "Handler must collapse the details element back to default "
            "so a one-off qty edit doesn't sticky for the next item."
        )
        assert ".focus()" in body, (
            "Handler must refocus the name input so the mobile "
            "keyboard stays up for rapid-fire add."
        )
