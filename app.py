"""
PantryPal — household-shared pantry + shopping list with AI meal planning.

Phase 1A: email/password auth (signup, login, logout).
Phase 1B: per-user pantry with add/edit/delete/search via htmx.
Phase 1C: per-user shopping list (with check-off + clear-checked) and a
          one-tap "Add to shopping" cross-link from any pantry row.
Phase 2A: households — items are owned by a household, with provenance
          (who added each item) preserved for the "added by X" stamps.
Phase 2B: invite/join — magic-link tokens let users share a household.
Phase 2C: deploy — Dockerfile + Fly.io config; app served via gunicorn
          with single worker (SQLite single-writer constraint) and a
          persistent volume mounted at /data for the DB file.
See PLAN.md for the full phased build plan.
"""

import os

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from extensions import csrf, db, login_manager
from forms import LoginForm, PantryItemForm, ShoppingItemForm, SignupForm
from models import Household, Invite, PantryItem, ShoppingItem, User

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get(
        "FLASK_SECRET_KEY", "dev-secret-change-me-in-env"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///pantrypal.sqlite3"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    csrf.init_app(app)  # exposes csrf_token() to Jinja and guards every POST
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    with app.app_context():
        # Phase 1A: bootstrap the schema on startup. We'll switch to
        # Flask-Migrate in Phase 2 when the schema needs to evolve without
        # dropping data. For Phase 2A's additive change (households table,
        # household_id columns) create_all is enough — see _run_phase_2a_migration
        # for the row-level backfill.
        db.create_all()
        _run_phase_2a_migration()

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    _register_routes(app)
    return app


def _register_routes(app: Flask) -> None:
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("pantry_list"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("pantry_list"))

        # Phase 2B: if the signup link came from /join/<token>, the URL is
        # `?invite=<token>`. Browsers POST forms back to the current URL
        # (including the query string) when the <form> has no action, so
        # the token survives the round-trip without a hidden field. We
        # still look it up explicitly here so we can validate it.
        invite_token = (request.args.get("invite") or "").strip()
        invite = (
            Invite.query.filter_by(token=invite_token).first()
            if invite_token else None
        )
        # Render-time context for the signup template
        invite_household = invite.household if invite and invite.is_active() else None

        form = SignupForm()
        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            if User.query.filter_by(email=email).first() is not None:
                flash(
                    "An account with that email already exists. Try signing in.",
                    "error",
                )
                return render_template(
                    "signup.html", form=form,
                    invite_household=invite_household, invite_token=invite_token,
                )

            user = User(email=email, name=form.name.data.strip())
            user.set_password(form.password.data)

            if invite is not None and invite.is_active():
                # Join the invited household instead of minting one.
                user.household_id = invite.household_id
                invite.consume()
                joined_household_name = invite.household.name
            else:
                # If they came in with a stale token, drop the invite + warn,
                # but don't block signup — falls back to household-of-one.
                if invite_token and (invite is None or not invite.is_active()):
                    flash(
                        "That invite link is no longer valid, so we created a "
                        "new household for you instead.",
                        "info",
                    )
                first_name = user.name.split()[0]
                household = Household(name=f"{first_name}'s home")
                db.session.add(household)
                db.session.flush()  # need household.id before linking
                user.household_id = household.id
                joined_household_name = None

            db.session.add(user)
            db.session.commit()

            login_user(user)
            if joined_household_name:
                flash(
                    f"Welcome to PantryPal, {user.name}! "
                    f"You've joined '{joined_household_name}'.",
                    "success",
                )
            else:
                flash(f"Welcome to PantryPal, {user.name}!", "success")
            return redirect(url_for("pantry_list"))

        return render_template(
            "signup.html", form=form,
            invite_household=invite_household, invite_token=invite_token,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        # Phase 2B: an existing user who clicked a /join/<token> link and
        # chose "Log in" lands here as /login?invite=<token>. After a
        # successful login we route them back to /join/<token> so they can
        # confirm the household switch. If they're already authenticated,
        # short-circuit straight to /join.
        invite_token = (request.args.get("invite") or "").strip()

        if current_user.is_authenticated:
            if invite_token:
                return redirect(url_for("join_landing", token=invite_token))
            return redirect(url_for("pantry_list"))

        invite = (
            Invite.query.filter_by(token=invite_token).first()
            if invite_token else None
        )
        invite_household = invite.household if invite and invite.is_active() else None

        form = LoginForm()
        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            user = User.query.filter_by(email=email).first()
            if user is None or not user.check_password(form.password.data):
                flash("Invalid email or password.", "error")
                return render_template(
                    "login.html", form=form,
                    invite_household=invite_household, invite_token=invite_token,
                )

            # `remember=True` issues Flask-Login's persistent remember-me
            # cookie (REMEMBER_COOKIE_DURATION default = 365 days). On a
            # phone this means PantryPal stays signed in across reboots.
            login_user(user, remember=form.remember.data)

            # Phase 2B priority: invite token > ?next= > /pantry. We send
            # them to /join/<token> rather than mutating their household
            # silently — they get a confirm step there.
            if invite_token:
                return redirect(url_for("join_landing", token=invite_token))

            # Honor Flask-Login's `?next=` redirect, but only if it's a safe
            # relative path (avoid open-redirect attacks).
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("pantry_list"))

        return render_template(
            "login.html", form=form,
            invite_household=invite_household, invite_token=invite_token,
        )

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("You've been signed out.", "info")
        return redirect(url_for("login"))

    @app.route("/pantry", methods=["GET"])
    @login_required
    def pantry_list():
        query = (request.args.get("q") or "").strip()
        items_q = current_user.household.pantry_items
        if query:
            items_q = items_q.filter(PantryItem.name.ilike(f"%{query}%"))
        items = items_q.all()

        if request.headers.get("HX-Request"):
            return render_template("_pantry_list.html", items=items, query=query)

        form = PantryItemForm()
        return render_template(
            "pantry.html", items=items, form=form, query=query,
            household=current_user.household,
            invites=_active_invites_for(current_user.household),
            members=current_user.household.members.all(),
        )

    @app.route("/pantry", methods=["POST"])
    @login_required
    def pantry_add():
        form = PantryItemForm()
        if form.validate_on_submit():
            item = PantryItem(
                added_by_user_id=current_user.id,
                household_id=current_user.household_id,
                name=form.name.data.strip(),
                quantity=form.quantity.data,
                unit=_clean_optional(form.unit.data),
                notes=_clean_optional(form.notes.data),
            )
            db.session.add(item)
            db.session.commit()

            if request.headers.get("HX-Request"):
                # Re-render the whole list so the empty state disappears
                # cleanly and ordering stays in sync with the DB.
                items = current_user.household.pantry_items.all()
                return render_template("_pantry_list.html", items=items, query="")
            return redirect(url_for("pantry_list"))

        if request.headers.get("HX-Request"):
            # Send field errors back to a dedicated error slot inside the
            # form so we don't lose the user's in-progress input.
            response = render_template("_pantry_form_errors.html", form=form)
            return response, 422, {
                "HX-Retarget": "#add-form-errors",
                "HX-Reswap": "innerHTML",
            }
        flash("Couldn't add that item — check the fields and try again.", "error")
        return redirect(url_for("pantry_list"))

    @app.route("/pantry/<int:item_id>", methods=["GET"])
    @login_required
    def pantry_item_get(item_id: int):
        item = _get_pantry_item_or_404(item_id)
        return render_template("_pantry_item.html", item=item)

    @app.route("/pantry/<int:item_id>/edit", methods=["GET"])
    @login_required
    def pantry_item_edit(item_id: int):
        item = _get_pantry_item_or_404(item_id)
        form = PantryItemForm(obj=item)
        return render_template("_pantry_item_edit.html", item=item, form=form)

    @app.route("/pantry/<int:item_id>", methods=["PUT", "POST"])
    @login_required
    def pantry_item_update(item_id: int):
        item = _get_pantry_item_or_404(item_id)
        form = PantryItemForm()
        if form.validate_on_submit():
            item.name = form.name.data.strip()
            item.quantity = form.quantity.data
            item.unit = _clean_optional(form.unit.data)
            item.notes = _clean_optional(form.notes.data)
            db.session.commit()
            return render_template("_pantry_item.html", item=item)
        return render_template("_pantry_item_edit.html", item=item, form=form), 422

    @app.route("/pantry/<int:item_id>", methods=["DELETE"])
    @login_required
    def pantry_item_delete(item_id: int):
        item = _get_pantry_item_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        items = current_user.household.pantry_items.all()
        return render_template("_pantry_list.html", items=items, query="")

    @app.route("/pantry/<int:item_id>/add-to-shopping", methods=["POST"])
    @login_required
    def pantry_item_to_shopping(item_id: int):
        """One-tap copy from pantry -> shopping list. Doesn't mutate pantry."""
        item = _get_pantry_item_or_404(item_id)
        shop = ShoppingItem(
            # current_user is the one tapping +Shop, so they're the "added by"
            # regardless of who originally added the pantry item.
            added_by_user_id=current_user.id,
            household_id=current_user.household_id,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            notes=None,  # notes are pantry-context, not shopping-context
        )
        db.session.add(shop)
        db.session.commit()
        # Empty body + an HX-Trigger header so the button can flash a
        # transient "Added" without us having to re-render anything.
        return "", 200, {"HX-Trigger": "shopping:added"}

    @app.route("/shopping", methods=["GET"])
    @login_required
    def shopping_list():
        query = (request.args.get("q") or "").strip()
        items_q = current_user.household.shopping_items
        if query:
            items_q = items_q.filter(ShoppingItem.name.ilike(f"%{query}%"))
        items = items_q.all()
        checked_count = sum(1 for i in items if i.checked)

        if request.headers.get("HX-Request"):
            return render_template(
                "_shopping_list.html", items=items, query=query,
                checked_count=checked_count,
            )

        form = ShoppingItemForm()
        return render_template(
            "shopping.html", items=items, form=form, query=query,
            checked_count=checked_count,
        )

    @app.route("/shopping", methods=["POST"])
    @login_required
    def shopping_add():
        form = ShoppingItemForm()
        if form.validate_on_submit():
            item = ShoppingItem(
                added_by_user_id=current_user.id,
                household_id=current_user.household_id,
                name=form.name.data.strip(),
                quantity=form.quantity.data,
                unit=_clean_optional(form.unit.data),
                notes=_clean_optional(form.notes.data),
            )
            db.session.add(item)
            db.session.commit()

            if request.headers.get("HX-Request"):
                items = current_user.household.shopping_items.all()
                checked_count = sum(1 for i in items if i.checked)
                return render_template(
                    "_shopping_list.html", items=items, query="",
                    checked_count=checked_count,
                )
            return redirect(url_for("shopping_list"))

        if request.headers.get("HX-Request"):
            response = render_template("_shopping_form_errors.html", form=form)
            return response, 422, {
                "HX-Retarget": "#shopping-add-form-errors",
                "HX-Reswap": "innerHTML",
            }
        flash("Couldn't add that item — check the fields and try again.", "error")
        return redirect(url_for("shopping_list"))

    @app.route("/shopping/<int:item_id>", methods=["GET"])
    @login_required
    def shopping_item_get(item_id: int):
        item = _get_shopping_item_or_404(item_id)
        return render_template("_shopping_item.html", item=item)

    @app.route("/shopping/<int:item_id>/edit", methods=["GET"])
    @login_required
    def shopping_item_edit(item_id: int):
        item = _get_shopping_item_or_404(item_id)
        form = ShoppingItemForm(obj=item)
        return render_template("_shopping_item_edit.html", item=item, form=form)

    @app.route("/shopping/<int:item_id>", methods=["PUT", "POST"])
    @login_required
    def shopping_item_update(item_id: int):
        item = _get_shopping_item_or_404(item_id)
        form = ShoppingItemForm()
        if form.validate_on_submit():
            item.name = form.name.data.strip()
            item.quantity = form.quantity.data
            item.unit = _clean_optional(form.unit.data)
            item.notes = _clean_optional(form.notes.data)
            db.session.commit()
            return render_template("_shopping_item.html", item=item)
        return render_template("_shopping_item_edit.html", item=item, form=form), 422

    @app.route("/shopping/<int:item_id>", methods=["DELETE"])
    @login_required
    def shopping_item_delete(item_id: int):
        item = _get_shopping_item_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        items = current_user.household.shopping_items.all()
        checked_count = sum(1 for i in items if i.checked)
        return render_template(
            "_shopping_list.html", items=items, query="",
            checked_count=checked_count,
        )

    @app.route("/shopping/<int:item_id>/toggle", methods=["POST"])
    @login_required
    def shopping_item_toggle(item_id: int):
        item = _get_shopping_item_or_404(item_id)
        item.checked = not item.checked
        db.session.commit()
        # Re-render the whole list so checked items re-sort to the bottom.
        items = current_user.household.shopping_items.all()
        checked_count = sum(1 for i in items if i.checked)
        return render_template(
            "_shopping_list.html", items=items, query="",
            checked_count=checked_count,
        )

    @app.route("/shopping/clear-checked", methods=["POST"])
    @login_required
    def shopping_clear_checked():
        deleted = current_user.household.shopping_items.filter_by(checked=True).all()
        for item in deleted:
            db.session.delete(item)
        db.session.commit()
        items = current_user.household.shopping_items.all()
        return render_template(
            "_shopping_list.html", items=items, query="",
            checked_count=0,
        )

    # ---- Phase 2B: invite/join ---------------------------------------

    @app.route("/household/invite", methods=["POST"])
    @login_required
    def household_invite_create():
        """Mint a new invite for the current user's household. Returns
        the refreshed share card via htmx (or a redirect for hard-POST)."""
        invite = Invite.mint(
            household_id=current_user.household_id,
            created_by_user_id=current_user.id,
        )
        db.session.add(invite)
        db.session.commit()
        if request.headers.get("HX-Request"):
            return render_template(
                "_household_share.html",
                household=current_user.household,
                invites=_active_invites_for(current_user.household),
                members=current_user.household.members.all(),
            )
        return redirect(url_for("pantry_list"))

    @app.route("/household/invite/<int:invite_id>", methods=["DELETE"])
    @login_required
    def household_invite_revoke(invite_id: int):
        invite = db.session.get(Invite, invite_id)
        if invite is None or invite.household_id != current_user.household_id:
            # 404 not 403 — don't leak existence of invites from other households
            abort(404)
        db.session.delete(invite)
        db.session.commit()
        return render_template(
            "_household_share.html",
            household=current_user.household,
            invites=_active_invites_for(current_user.household),
            members=current_user.household.members.all(),
        )

    @app.route("/join/<token>", methods=["GET"])
    def join_landing(token: str):
        """The shared URL. Renders different content depending on whether
        the visitor is anonymous, already a member, or a logged-in member
        of some other household who's about to switch."""
        invite = Invite.query.filter_by(token=token).first()
        if invite is None:
            return render_template(
                "join.html", invite=None, household=None,
                error="This invite link is not recognized.",
            ), 404
        if not invite.is_active():
            return render_template(
                "join.html", invite=invite, household=invite.household,
                error=invite.reason_inactive(),
            ), 410  # Gone

        if current_user.is_authenticated:
            already_member = current_user.household_id == invite.household_id
            return render_template(
                "join.html",
                invite=invite,
                household=invite.household,
                already_member=already_member,
                # the current_user-side household (so we can show
                # "Switch from X to Y?")
                current_household=current_user.household,
            )

        # Anonymous: show signup + login CTAs that carry the token through.
        return render_template(
            "join.html",
            invite=invite,
            household=invite.household,
            anonymous=True,
        )

    @app.route("/join/<token>", methods=["POST"])
    @login_required
    def join_commit(token: str):
        """Logged-in confirmation step. Swaps user.household_id and consumes
        the invite. The old household + items stay intact — no destructive
        merge in v1."""
        invite = Invite.query.filter_by(token=token).first()
        if invite is None or not invite.is_active():
            flash("That invite is no longer valid.", "error")
            return redirect(url_for("pantry_list"))
        if current_user.household_id == invite.household_id:
            flash("You're already a member of that household.", "info")
            return redirect(url_for("pantry_list"))

        old_name = current_user.household.name if current_user.household else None
        new_name = invite.household.name
        current_user.household_id = invite.household_id
        invite.consume()
        db.session.commit()

        if old_name:
            flash(
                f"Joined '{new_name}'. Your previous household '{old_name}' "
                "and its items are still saved.",
                "success",
            )
        else:
            flash(f"Joined '{new_name}'!", "success")
        return redirect(url_for("pantry_list"))

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "phase": "2C"}


def _ensure_phase_2a_columns() -> None:
    """
    `db.create_all()` will create the new `households` table, but it does
    NOT add new columns to existing tables — that's a SQLAlchemy gotcha
    (see: https://docs.sqlalchemy.org/en/20/core/metadata.html). For our
    additive Phase 2A change (new `household_id` FK columns on users +
    items) we issue plain `ALTER TABLE ADD COLUMN` for any column that's
    missing. SQLite supports this since 3.2.0 (2005), so no version dance.
    """
    inspector = db.inspect(db.engine)

    def col_names(table: str) -> set:
        if not inspector.has_table(table):
            return set()
        return {c["name"] for c in inspector.get_columns(table)}

    # NOTE: SQLite's ALTER TABLE ADD COLUMN can add a FOREIGN KEY constraint
    # at the column level, but it can't be NOT NULL without a default. We
    # leave these nullable in the DB — the application always sets them on
    # row create, and the backfill below populates legacy rows.
    statements = []
    if inspector.has_table("users") and "household_id" not in col_names("users"):
        statements.append(
            'ALTER TABLE users ADD COLUMN household_id INTEGER '
            'REFERENCES households(id)'
        )
    if (inspector.has_table("pantry_items")
            and "household_id" not in col_names("pantry_items")):
        statements.append(
            'ALTER TABLE pantry_items ADD COLUMN household_id INTEGER '
            'REFERENCES households(id)'
        )
    if (inspector.has_table("shopping_items")
            and "household_id" not in col_names("shopping_items")):
        statements.append(
            'ALTER TABLE shopping_items ADD COLUMN household_id INTEGER '
            'REFERENCES households(id)'
        )

    if statements:
        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)


def _run_phase_2a_migration() -> None:
    """
    Backfill households for any user that doesn't have one yet, and point
    every existing pantry / shopping item at its owner's household.

    Idempotent: a startup where nothing needs migrating is a few cheap
    SELECTs and a no-op commit. Safe to run on every boot.

    Strategy: each pre-Phase-2A user becomes their own "household of one"
    named "<First name>'s home". Phase 2B's invite flow lets multiple users
    join the same household afterward.
    """
    # First, make sure the schema has the new columns. SQLAlchemy's
    # create_all() handles new TABLES but never adds COLUMNS to existing
    # tables — the upgrade path from Phase 1C to 2A needs this explicit ALTER.
    _ensure_phase_2a_columns()

    needs_household = User.query.filter(User.household_id.is_(None)).all()
    if needs_household:
        for user in needs_household:
            first_name = (user.name or user.email).split()[0]
            hh = Household(name=f"{first_name}'s home")
            db.session.add(hh)
            db.session.flush()  # need hh.id before we can point at it
            user.household_id = hh.id
        db.session.commit()

    # Now any item that still has household_id IS NULL belongs to its
    # added_by user's household. We do this *after* the user pass so the
    # ownership join below always resolves.
    orphan_pantry = PantryItem.query.filter(PantryItem.household_id.is_(None)).all()
    orphan_shopping = ShoppingItem.query.filter(
        ShoppingItem.household_id.is_(None)).all()
    if orphan_pantry or orphan_shopping:
        for item in orphan_pantry:
            item.household_id = item.added_by.household_id
        for item in orphan_shopping:
            item.household_id = item.added_by.household_id
        db.session.commit()


def _active_invites_for(household: Household) -> list:
    """Active = not expired AND has uses remaining. Sorted newest-first by
    the relationship's order_by. Dead invites are kept in the DB for now
    (Phase 2C deploy gets a periodic cleanup job)."""
    return [i for i in household.invites.all() if i.is_active()]


def _clean_optional(value) -> "str | None":
    """Turn empty strings and whitespace into None so SQLite stores NULL."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _get_pantry_item_or_404(item_id: int) -> PantryItem:
    """Fetch a pantry item the current user's HOUSEHOLD owns, or 404.
    Phase 2A: ownership moved from `item.user_id` to `item.household_id`,
    so a member who didn't add the item can still edit/delete it."""
    item = db.session.get(PantryItem, item_id)
    if item is None or item.household_id != current_user.household_id:
        abort(404)
    return item


def _get_shopping_item_or_404(item_id: int) -> ShoppingItem:
    """Same as `_get_pantry_item_or_404` but for shopping items."""
    item = db.session.get(ShoppingItem, item_id)
    if item is None or item.household_id != current_user.household_id:
        abort(404)
    return item


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="0.0.0.0")
