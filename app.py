"""
PantryPal — household-shared pantry + shopping list with AI meal planning.

Phase 1A: email/password auth (signup, login, logout).
Phase 1B: per-user pantry with add/edit/delete/search via htmx.
See PLAN.md for the full phased build plan.
"""

import os

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import csrf, db, login_manager
from forms import LoginForm, PantryItemForm, SignupForm
from models import PantryItem, User

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
        # dropping data.
        db.create_all()

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

        form = SignupForm()
        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            if User.query.filter_by(email=email).first() is not None:
                flash(
                    "An account with that email already exists. Try signing in.",
                    "error",
                )
                return render_template("signup.html", form=form)

            user = User(email=email, name=form.name.data.strip())
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash(f"Welcome to PantryPal, {user.name}!", "success")
            return redirect(url_for("pantry_list"))

        return render_template("signup.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("pantry_list"))

        form = LoginForm()
        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            user = User.query.filter_by(email=email).first()
            if user is None or not user.check_password(form.password.data):
                flash("Invalid email or password.", "error")
                return render_template("login.html", form=form)

            login_user(user)
            # Honor Flask-Login's `?next=` redirect, but only if it's a safe
            # relative path (avoid open-redirect attacks).
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("pantry_list"))

        return render_template("login.html", form=form)

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
        items_q = current_user.pantry_items
        if query:
            items_q = items_q.filter(PantryItem.name.ilike(f"%{query}%"))
        items = items_q.all()

        if request.headers.get("HX-Request"):
            return render_template("_pantry_list.html", items=items, query=query)

        form = PantryItemForm()
        return render_template("pantry.html", items=items, form=form, query=query)

    @app.route("/pantry", methods=["POST"])
    @login_required
    def pantry_add():
        form = PantryItemForm()
        if form.validate_on_submit():
            item = PantryItem(
                user_id=current_user.id,
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
                items = current_user.pantry_items.all()
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
        item = _get_item_or_404(item_id)
        return render_template("_pantry_item.html", item=item)

    @app.route("/pantry/<int:item_id>/edit", methods=["GET"])
    @login_required
    def pantry_item_edit(item_id: int):
        item = _get_item_or_404(item_id)
        form = PantryItemForm(obj=item)
        return render_template("_pantry_item_edit.html", item=item, form=form)

    @app.route("/pantry/<int:item_id>", methods=["PUT", "POST"])
    @login_required
    def pantry_item_update(item_id: int):
        item = _get_item_or_404(item_id)
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
        item = _get_item_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        items = current_user.pantry_items.all()
        return render_template("_pantry_list.html", items=items, query="")

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "phase": "1B"}


def _clean_optional(value) -> "str | None":
    """Turn empty strings and whitespace into None so SQLite stores NULL."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _get_item_or_404(item_id: int) -> PantryItem:
    """Fetch a pantry item the current user owns, or 404. Phase 2 swaps the
    ownership check from user_id to household membership."""
    item = db.session.get(PantryItem, item_id)
    if item is None or item.user_id != current_user.id:
        abort(404)
    return item


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="0.0.0.0")
