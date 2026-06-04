"""
Phase 2B regression suite — invite/join flow.

Covers the three branches of /join/<token> (anonymous, already-member,
switch-confirm) plus signup-with-invite, login-with-invite, mint + revoke,
and the inactive-invite paths (expired / used-up / unknown).

Tests intentionally drop the dynamic relationship's order_by before
bulk operations (the Phase 2A gotcha) and use direct DB writes to set
up scenarios that the UI doesn't have a path to yet — e.g. forcing an
invite to be expired without waiting 7 real days.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

import pytest

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    """Decoded response body with HTML entities unescaped, so substring
    matches don't need to know that Jinja autoescapes `'` to `&#39;` etc.
    Jinja autoescape stays *on* for security — we only unescape inside
    test assertions."""
    return html.unescape(resp.get_data(as_text=True))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mint_invite_for(app, user_email: str) -> str:
    """Programmatically mint an invite for the given user's household. Used
    when tests need a token without going through the HTTP route."""
    with app.app_context():
        from extensions import db
        from models import Invite, User
        u = User.query.filter_by(email=user_email).first()
        inv = Invite.mint(
            household_id=u.household_id, created_by_user_id=u.id,
        )
        db.session.add(inv)
        db.session.commit()
        return inv.token


# ---------------------------------------------------------------------------
# Mint + render the share card
# ---------------------------------------------------------------------------

class TestShareCard:
    def test_pantry_renders_household_share_card(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        body = _body(client.get("/pantry"))
        assert "household-share" in body
        assert "Alice's home" in body
        assert "Just you for now" in body
        # No invites until they mint one
        assert "Revoke" not in body

    def test_post_invite_returns_share_card_partial_with_url(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.post("/household/invite", htmx=True)
        assert resp.status_code == 200
        body = _body(resp)
        # The partial replaces #household-share, so it's the outer
        # wrapper that comes back.
        assert 'id="household-share"' in body
        assert "/join/" in body, "share card should expose the joinable URL"
        assert "Revoke" in body
        # Exactly one invite was created
        with app.app_context():
            from models import Invite, User
            u = User.query.filter_by(email="alice@example.com").first()
            invites = Invite.query.filter_by(household_id=u.household_id).all()
            assert len(invites) == 1
            assert invites[0].is_active()
            assert invites[0].used_count == 0

    def test_revoke_invite_deletes_it(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/household/invite", htmx=True)
        with app.app_context():
            from models import Invite, User
            u = User.query.filter_by(email="alice@example.com").first()
            inv = Invite.query.filter_by(household_id=u.household_id).first()
            invite_id = inv.id

        resp = client.delete(f"/household/invite/{invite_id}")
        assert resp.status_code == 200
        body = _body(resp)
        assert "Revoke" not in body, "share card should no longer show that invite"

        with app.app_context():
            from extensions import db
            from models import Invite
            assert db.session.get(Invite, invite_id) is None

    def test_cant_revoke_other_households_invite(
            self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        alice.post("/household/invite", htmx=True)
        with app.app_context():
            from models import Invite, User
            a = User.query.filter_by(email="alice@example.com").first()
            inv = Invite.query.filter_by(household_id=a.household_id).first()
            invite_id = inv.id

        resp = bob.delete(f"/household/invite/{invite_id}")
        # 404 not 403 — we don't leak existence of other households' invites
        assert resp.status_code == 404
        with app.app_context():
            from extensions import db
            from models import Invite
            assert db.session.get(Invite, invite_id) is not None, (
                "bob's failed revoke should not have deleted alice's invite"
            )


# ---------------------------------------------------------------------------
# /join/<token> — landing page state machine
# ---------------------------------------------------------------------------

class TestJoinLandingAnonymous:
    def test_valid_invite_shows_signup_and_login_ctas(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")

        # Anonymous visitor
        anon = Client(app.test_client())
        resp = anon.get(f"/join/{token}")
        assert resp.status_code == 200
        body = _body(resp)
        assert "Alice's home" in body
        assert "Alice" in body  # who invited them
        assert "Create account" in body
        assert "Sign in to join" in body
        # Both CTAs forward the token
        assert f"invite={token}" in body

    def test_unknown_token_404(self, app):
        anon = Client(app.test_client())
        resp = anon.get("/join/garbage-token-doesnt-exist")
        assert resp.status_code == 404
        assert "not recognized" in _body(resp)

    def test_expired_invite_410(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")
        # Backdate so it's expired
        with app.app_context():
            from extensions import db
            from models import Invite
            inv = Invite.query.filter_by(token=token).first()
            inv.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.session.commit()

        anon = Client(app.test_client())
        resp = anon.get(f"/join/{token}")
        assert resp.status_code == 410
        assert "expired" in _body(resp).lower()

    def test_used_up_invite_410(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")
        with app.app_context():
            from extensions import db
            from models import Invite
            inv = Invite.query.filter_by(token=token).first()
            inv.used_count = inv.max_uses
            db.session.commit()

        anon = Client(app.test_client())
        resp = anon.get(f"/join/{token}")
        assert resp.status_code == 410
        assert "maximum number" in _body(resp).lower()


class TestJoinLandingLoggedIn:
    def test_logged_in_member_sees_already_member_state(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")
        # alice visits her own invite
        resp = client.get(f"/join/{token}")
        assert resp.status_code == 200
        body = _body(resp)
        assert "already in" in body
        assert "Open pantry" in body

    def test_logged_in_other_household_sees_switch_confirm(
            self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        token = mint_invite_for(app, "alice@example.com")

        resp = bob.get(f"/join/{token}")
        assert resp.status_code == 200
        body = _body(resp)
        # Confirm-switch UI cues
        assert "Join \"Alice's home\"" in body
        assert "Bob's home" in body, "should mention bob's current household"
        assert "non-destructive" in body or "previous items stay" in body


# ---------------------------------------------------------------------------
# POST /join/<token> — commit the switch
# ---------------------------------------------------------------------------

class TestJoinCommit:
    def test_bob_switches_into_alices_household(self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        # Alice adds a pantry item BEFORE bob joins
        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        token = mint_invite_for(app, "alice@example.com")

        with app.app_context():
            from models import User
            a = User.query.filter_by(email="alice@example.com").first()
            b = User.query.filter_by(email="bob@example.com").first()
            assert b.household_id != a.household_id, "precondition"
            old_bob_household = b.household_id
            alice_household = a.household_id

        # Bob commits the switch
        resp = bob.post(f"/join/{token}", follow_redirects=True)
        assert resp.status_code == 200

        # Bob now sees alice's pantry
        body = _body(bob.get("/pantry"))
        assert "Olive oil" in body
        assert "Alice's home" in body

        # DB-level: bob.household_id moved, invite consumed
        with app.app_context():
            from models import Invite, User
            b = User.query.filter_by(email="bob@example.com").first()
            assert b.household_id == alice_household
            inv = Invite.query.filter_by(token=token).first()
            assert inv.used_count == 1

            # Bob's old household + any items there are untouched in the DB
            # (just no longer visible to bob)
            from extensions import db as _db
            from models import Household
            old_h = _db.session.get(Household, old_bob_household)
            assert old_h is not None, (
                "bob's old household should still exist after the switch"
            )

    def test_join_post_with_expired_token_redirects_to_pantry_with_flash(
            self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        token = mint_invite_for(app, "alice@example.com")
        with app.app_context():
            from extensions import db
            from models import Invite
            inv = Invite.query.filter_by(token=token).first()
            inv.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.session.commit()

        resp = bob.post(f"/join/{token}", follow_redirects=True)
        body = _body(resp)
        assert "no longer valid" in body.lower()
        # Bob still in his original household
        with app.app_context():
            from models import User
            b = User.query.filter_by(email="bob@example.com").first()
            assert b.household.name == "Bob's home"


# ---------------------------------------------------------------------------
# Signup with ?invite=<token>
# ---------------------------------------------------------------------------

class TestSignupWithInvite:
    def test_new_user_signup_joins_invited_household_instead_of_minting_one(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")

        anon = Client(app.test_client())
        # GET shows the banner
        body = _body(anon.get(f"/signup?invite={token}"))
        assert "Alice's home" in body
        assert "joining" in body.lower()

        # POST creates bob, joining alice's household (no Bob's home)
        resp = anon.post(
            f"/signup?invite={token}",
            data={
                "name": "Bob",
                "email": "bob@example.com",
                "password": "bobpass123",
                "submit": "Create",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            from models import Household, User
            a = User.query.filter_by(email="alice@example.com").first()
            b = User.query.filter_by(email="bob@example.com").first()
            assert b.household_id == a.household_id
            # No "Bob's home" was created — the invite path skipped that step
            assert Household.query.filter_by(name="Bob's home").first() is None

    def test_stale_invite_falls_back_to_household_of_one_with_warning(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")
        # Kill the invite
        with app.app_context():
            from extensions import db
            from models import Invite
            inv = Invite.query.filter_by(token=token).first()
            inv.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.session.commit()

        anon = Client(app.test_client())
        resp = anon.post(
            f"/signup?invite={token}",
            data={
                "name": "Bob",
                "email": "bob@example.com",
                "password": "bobpass123",
                "submit": "Create",
            },
            follow_redirects=True,
        )
        body = _body(resp)
        assert "no longer valid" in body.lower()
        with app.app_context():
            from models import User
            b = User.query.filter_by(email="bob@example.com").first()
            # Stale token: bob got his OWN household
            assert b.household.name == "Bob's home"


# ---------------------------------------------------------------------------
# Login with ?invite=<token>
# ---------------------------------------------------------------------------

class TestLoginWithInvite:
    def test_login_with_invite_redirects_to_join_landing(
            self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        token = mint_invite_for(app, "alice@example.com")

        # Bob logs out first
        bob_anon = Client(app.test_client())

        # Then logs back in via the invite URL
        resp = bob_anon.post(
            f"/login?invite={token}",
            data={
                "email": "bob@example.com",
                "password": "testpass123",
                "remember": "y",
                "submit": "Sign in",
            },
            follow_redirects=False,  # we want to inspect the redirect
        )
        assert resp.status_code == 302
        assert f"/join/{token}" in resp.headers.get("Location", "")

    def test_login_with_invite_banner_visible_on_get(
            self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        token = mint_invite_for(app, "alice@example.com")

        anon = Client(app.test_client())
        body = _body(anon.get(f"/login?invite={token}"))
        assert "Alice's home" in body
        # The signup link in the footer should also forward the token
        m = re.search(rf'href="[^"]*signup\?invite={re.escape(token)}', body)
        assert m, "signup link in login.html should forward the invite token"
