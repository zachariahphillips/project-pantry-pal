"""
PantryPal — household-shared pantry + shopping list with AI meal planning.

Phase 1A: email/password auth foundation (signup, login, logout).
See PLAN.md for the full phased build plan.
"""

import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import csrf, db, login_manager
from forms import LoginForm, SignupForm
from models import User

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
            return redirect(url_for("home"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

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
            return redirect(url_for("home"))

        return render_template("signup.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

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
            return redirect(url_for("home"))

        return render_template("login.html", form=form)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("You've been signed out.", "info")
        return redirect(url_for("login"))

    @app.route("/home")
    @login_required
    def home():
        return render_template("home.html")

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "phase": "1A"}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="0.0.0.0")
